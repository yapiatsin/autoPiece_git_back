"""Orchestration FNE : certification DGI des ventes encaissées en caisse.

Appelé après l'encaissement, hors transaction : le paiement est déjà enregistré
quand la DGI est sollicitée. Un refus ou une panne FNE n'annule donc jamais une
vente ; il reste une FactureFNE en échec, que la caisse peut relancer.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from stock.fne import (
    FNEError,
    TAXES,
    _env,
    base_url,
    certifier_facture,
    environnement,
    est_configuree,
)
from stock.models import Commande, FactureFNE, PanierItem, Ticket
from stock.stock_local_service import get_prix_unitaire
from stock.timbre_service import moyen_paiement_est_espece

logger = logging.getLogger(__name__)

CLIENT_COMPTOIR = 'Client comptoir'
TAXE_HORS_TVA_DEFAUT = 'TVAD'

# Une certification en cours depuis plus longtemps a forcément échoué sans
# laisser de trace (processus tué) : on autorise alors à la relancer.
DELAI_EN_COURS = timedelta(minutes=2)

LIBELLES_TAXE = {
    'TVA': 'TVA 18%',
    'TVAB': 'TVA 9%',
    'TVAC': 'TVA exo. conv. 0%',
    'TVAD': 'TVA exo. leg. 0%',
    'TVAE': 'TVA 0%',
}


def fne_active() -> bool:
    """FNE_ENABLED=True et une clé API présente dans le .env."""
    return _env('FNE_ENABLED', 'False').lower() in ('1', 'true', 'yes', 'on') and est_configuree()


def commande_eligible(commande: Commande) -> bool:
    """Vente caisse payée en espèces : seul parcours certifié pour l'instant."""
    return (
        bool(commande.paye)
        and not commande.commande_en_ligne
        and moyen_paiement_est_espece(commande.moyen_paiement)
    )


def code_taxe(commande: Commande) -> str:
    """
    TVA cochée en caisse → taux normal (18 %) ou réduit (9 %).
    Sinon, code d'exonération de l'entreprise (FNE_TAXE_HORS_TVA, TVAD par défaut) :
    la facture certifiée doit rester égale au montant réellement encaissé.
    """
    if commande.tva_appliquee and Decimal(str(commande.montant_tva or 0)) > 0:
        from stock.tva_service import get_taux_tva
        return 'TVAB' if get_taux_tva() == Decimal('9') else 'TVA'
    code = (_env('FNE_TAXE_HORS_TVA', TAXE_HORS_TVA_DEFAUT) or TAXE_HORS_TVA_DEFAUT).upper()
    return code if code in TAXES else TAXE_HORS_TVA_DEFAUT


def telephone_local(raw) -> str:
    """Format attendu par la FNE : 10 chiffres ivoiriens (ex. 0709080765)."""
    digits = re.sub(r'\D', '', str(raw or ''))
    if digits.startswith('225') and len(digits) == 13:
        digits = digits[3:]
    return digits if len(digits) == 10 else ''


def _nombre(value):
    """Montant JSON : entier si rond (XOF), sinon deux décimales."""
    d = Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return int(d) if d == d.to_integral_value() else float(d)


def pourcentage_remise(commande: Commande) -> Decimal:
    """La FNE attend la remise globale en pourcentage du total HT."""
    brut = Decimal(str(commande.total_sans_remise or 0))
    remise = Decimal(str(commande.remise or 0))
    if brut <= 0 or remise <= 0:
        return Decimal('0')
    return (remise / brut * Decimal('100')).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)


def construire_facture(commande: Commande, panier_items=None, caissier=None) -> dict:
    """Corps de la requête « Certification de facture de vente » (API #1)."""
    panier = commande.panier
    loc = getattr(panier, 'local_entrepot', None)
    if panier_items is None:
        panier_items = list(PanierItem.objects.filter(panier=panier).select_related('piece'))
    ticket = Ticket.objects.filter(commande=commande).first()

    etablissement = _env('FNE_ETABLISSEMENT') or ''
    if not etablissement:
        raise FNEError(
            "Établissement FNE non défini : renseignez FNE_ETABLISSEMENT dans le fichier .env "
            "(nom exact de l'établissement dans l'espace FNE)."
        )

    # Une localité = un point de vente FNE (déclaré sur LocalEntrepot).
    # FNE_POINT_DE_VENTE reste un repli optionnel pour un site unique / migration.
    point_de_vente = ''
    if loc is not None:
        point_de_vente = loc.point_de_vente_fne
    if not point_de_vente:
        point_de_vente = (_env('FNE_POINT_DE_VENTE') or '').strip()
    if not point_de_vente:
        loc_nom = loc.nom if loc else 'cette localité'
        raise FNEError(
            f"Point de vente FNE non configuré pour « {loc_nom} ». "
            "Ouvrez Localités, renseignez le champ « Point de vente FNE » "
            "avec le nom EXACT déclaré dans l'espace FNE, puis relancez."
        )

    telephone = (
        telephone_local(panier.telephone_livraison)
        or telephone_local(_env('FNE_CLIENT_TELEPHONE'))
        or telephone_local(getattr(loc, 'contact', ''))
    )
    email = _env('FNE_CLIENT_EMAIL')
    if not telephone or not email:
        raise FNEError(
            "Coordonnées client FNE manquantes : renseignez FNE_CLIENT_TELEPHONE "
            "et FNE_CLIENT_EMAIL dans le fichier .env (utilisés pour les clients comptoir)."
        )

    taxe = code_taxe(commande)
    items = []
    for item in panier_items:
        prix = get_prix_unitaire(item.piece, loc, item.new_price)
        items.append({
            'taxes': [taxe],
            'reference': (item.piece.numero_piece or '')[:100],
            'description': (item.piece.designation or '')[:255],
            'quantity': item.quantite,
            'amount': _nombre(prix),
            'measurementUnit': 'pcs',
        })
    if not items:
        raise FNEError('Aucun article à certifier sur cette commande.')

    vendeur = caissier or commande.utilisateur
    client = (panier.nom_client or '').strip() or (
        (ticket.client_name or '').strip() if ticket else ''
    )
    body = {
        'invoiceType': 'sale',
        'paymentMethod': 'cash',
        'template': 'B2C',
        'isRne': False,
        'clientCompanyName': (client or CLIENT_COMPTOIR)[:120],
        'clientPhone': telephone,
        'clientEmail': email,
        'clientSellerName': getattr(vendeur, 'username', '') or '',
        'pointOfSale': point_de_vente,
        'establishment': etablissement,
        'foreignCurrency': '',
        'foreignCurrencyRate': 0,
        'items': items,
    }
    message = _env('FNE_MESSAGE_COMMERCIAL')
    if message:
        body['commercialMessage'] = message[:200]
    if ticket:
        # Rapproche la facture DGI du reçu de caisse (spécimens à transmettre à la DGI).
        body['footer'] = f'Ref. caisse {ticket.numero}'
    remise = pourcentage_remise(commande)
    if remise > 0:
        body['discount'] = float(remise)
    return body


def _url_verification(data: dict, invoice: dict) -> str:
    token = str(data.get('token') or '').strip()
    if token.startswith('http'):
        return token
    token = token or str(invoice.get('token') or '').strip()
    if not token:
        return ''
    host = base_url()
    if host.endswith('/ws'):
        host = host[:-3]
    return f'{host}/fr/verification/{token}'


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except Exception:
        return Decimal('0')


def _reserver(commande: Commande, forcer: bool):
    """
    Réserve la certification de cette commande (une seule à la fois).
    Retourne (facture, a_certifier). La ligne n'est verrouillée que le temps de
    la réservation : l'appel HTTP à la DGI se fait hors transaction.
    """
    with transaction.atomic():
        facture, created = FactureFNE.objects.select_for_update().get_or_create(
            commande=commande,
        )
        if not created:
            if facture.est_certifiee:
                return facture, False
            en_vol = (
                facture.statut == FactureFNE.STATUT_EN_COURS
                and facture.tentatives > 0
                and timezone.now() - facture.date_maj < DELAI_EN_COURS
            )
            if en_vol and not forcer:
                return facture, False
        facture.statut = FactureFNE.STATUT_EN_COURS
        facture.tentatives += 1
        facture.erreur = ''
        facture.save(update_fields=['statut', 'tentatives', 'erreur', 'date_maj'])
        return facture, True


def certifier_commande(commande: Commande, *, panier_items=None, caissier=None, forcer=False):
    """
    Certifie la vente auprès de la FNE (idempotent : une facture certifiée ne
    l'est jamais deux fois, la numérotation DGI étant une série ininterrompue).
    Retourne la FactureFNE, ou None si la FNE est désactivée / la vente non éligible.
    Ne lève pas d'exception : un échec est consigné sur la FactureFNE.
    """
    if not fne_active() or not commande_eligible(commande):
        return None

    facture, a_certifier = _reserver(commande, forcer)
    if not a_certifier:
        return facture

    try:
        body = construire_facture(commande, panier_items=panier_items, caissier=caissier)
    except FNEError as exc:
        facture.statut = FactureFNE.STATUT_ECHEC
        facture.erreur = str(exc)
        facture.save(update_fields=['statut', 'erreur', 'date_maj'])
        return facture

    facture.payload = body
    facture.etablissement = body['establishment']
    facture.point_de_vente = body['pointOfSale']
    facture.environnement = environnement()
    try:
        data = certifier_facture(body)
    except FNEError as exc:
        logger.warning('FNE commande %s non certifiée : %s', commande.pk, exc)
        facture.statut = FactureFNE.STATUT_ECHEC
        facture.erreur = str(exc)
        facture.raw_response = {'http_status': exc.http_status, 'errors': exc.details}
        facture.save()
        return facture

    invoice = data.get('invoice') if isinstance(data.get('invoice'), dict) else {}
    reference = data.get('reference') or invoice.get('reference') or ''
    facture.raw_response = data
    if not reference:
        facture.statut = FactureFNE.STATUT_ECHEC
        facture.erreur = "La FNE n'a pas renvoyé de numéro de facture."
        facture.save()
        return facture

    date_fne = parse_datetime(str(invoice.get('date') or ''))
    facture.statut = FactureFNE.STATUT_CERTIFIEE
    facture.reference = reference
    facture.fne_invoice_id = str(invoice.get('id') or '')
    facture.ncc = str(data.get('ncc') or _env('FNE_NCC') or '')
    facture.url_verification = _url_verification(data, invoice)
    facture.montant_ttc = _decimal(invoice.get('amount'))
    facture.montant_tva = _decimal(invoice.get('vatAmount'))
    facture.timbre = _decimal(invoice.get('fiscalStamp'))
    facture.alerte_sticker = bool(data.get('warning'))
    balance = data.get('balance_sticker')
    facture.solde_sticker = int(balance) if isinstance(balance, (int, float)) else None
    facture.date_certification = date_fne or timezone.now()
    facture.erreur = ''
    facture.save()
    if facture.alerte_sticker:
        logger.warning('FNE : stock de stickers bas (solde %s).', facture.solde_sticker)
    return facture


def certifier_apres_encaissement(request, result: dict) -> dict | None:
    """
    Suite de finaliser_encaissement_caisse : certifie la vente, puis imprime le
    reçu FNE après le reçu de caisse quand le serveur pilote lui-même
    l'imprimante USB (poste local). En caisse distante, c'est le navigateur qui
    l'imprime via WebUSB à partir du résumé renvoyé.
    """
    commande = result['commande']
    facture = certifier_commande(
        commande,
        panier_items=result.get('panier_items'),
        caissier=getattr(request, 'user', None),
    )
    if facture is not None and facture.est_certifiee and not result.get('already_paid'):
        try:
            from stock import printer_service
            if printer_service.HAS_USB and not printer_service.impression_par_le_poste(request):
                printer_service.print_fne_receipt_for_request(request, facture)
        except Exception as exc:
            logger.warning('Impression thermique reçu FNE: %s', exc)
    return resume_fne(facture)


def resume_fne(facture: FactureFNE | None) -> dict | None:
    """Données FNE renvoyées à l'écran de caisse après encaissement."""
    if facture is None:
        return None
    if facture.est_certifiee:
        message = f'Facture FNE {facture.reference} certifiée.'
        if facture.alerte_sticker:
            message += f' Stock de stickers bas (solde : {facture.solde_sticker}).'
    elif facture.statut == FactureFNE.STATUT_EN_COURS:
        message = 'Certification FNE en cours.'
    else:
        message = f'Facture FNE non certifiée : {facture.erreur}'
    return {
        'statut': facture.statut,
        'certifiee': facture.est_certifiee,
        'reference': facture.reference,
        'url_verification': facture.url_verification,
        'alerte_sticker': facture.alerte_sticker,
        'solde_sticker': facture.solde_sticker,
        'message': message,
    }
