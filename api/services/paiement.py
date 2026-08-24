"""Paiement client mobile : Espèce + Paiement numérique (GeniusPay)."""
from __future__ import annotations

from django.conf import settings
from django.urls import reverse

from ecom.services import get_moyen_espece, get_moyen_geniuspay, moyen_depuis_code
from stock.models import GeniusPayPaiement, MoyenPaiement


def moyens_paiement_client():
    """Uniquement Espèce et Paiement numérique, numérique par défaut."""
    espece = get_moyen_espece()
    if not espece.actif:
        espece.actif = True
        espece.save(update_fields=['actif'])
    gp = get_moyen_geniuspay()
    fields = []
    if gp.nom != 'Paiement numérique':
        gp.nom = 'Paiement numérique'
        fields.append('nom')
    if not gp.actif:
        gp.actif = True
        fields.append('actif')
    if fields:
        gp.save(update_fields=fields)
    return [
        {
            'id': gp.pk,
            'nom': 'Paiement numérique',
            'code': 'geniuspay',
            'default': True,
            'description': 'Paiement sécurisé en ligne — Wave, Orange Money, MTN, carte',
        },
        {
            'id': espece.pk,
            'nom': 'Espèce',
            'code': 'espece',
            'default': False,
            'description': 'Règlement à la livraison ou au retrait',
        },
    ]


def resolve_moyen_paiement(raw) -> MoyenPaiement:
    value = str(raw or 'geniuspay').strip()
    if value.isdigit():
        mp = MoyenPaiement.objects.filter(pk=int(value)).first()
        if mp and (mp.code or '').lower() in ('espece', 'geniuspay'):
            return mp
        return get_moyen_geniuspay()
    code = value.lower()
    if code not in ('espece', 'geniuspay'):
        code = 'geniuspay'
    return moyen_depuis_code(code)


def _gp_ouvert(commande) -> GeniusPayPaiement | None:
    return (
        GeniusPayPaiement.objects.filter(commande=commande)
        .order_by('-date_creation')
        .first()
    )


def paiement_payload(request, commande, gp: GeniusPayPaiement | None = None) -> dict:
    gp = gp or _gp_ouvert(commande)
    code = (getattr(commande.moyen_paiement, 'code', '') or '').lower()
    pending = bool(
        not commande.paye
        and code == 'geniuspay'
        and gp
        and gp.checkout_url
        and gp.statut in ('pending', 'processing')
    )
    status_path = reverse('v1_order_payment', kwargs={'commande_id': commande.pk})
    pay_path = reverse('v1_order_pay', kwargs={'commande_id': commande.pk})
    return {
        'paye': bool(commande.paye),
        'pending': pending,
        'moyen_code': code or '',
        'libelle': commande.libelle_paiement,
        'payment_method': (gp.payment_method if gp else '') or '',
        'checkout_url': (gp.checkout_url if pending else '') or '',
        'reference': (gp.reference if gp else '') or '',
        'status_url': request.build_absolute_uri(status_path),
        'pay_url': request.build_absolute_uri(pay_path),
        'failed': bool(
            gp
            and not commande.paye
            and gp.statut in ('failed', 'cancelled', 'expired')
        ),
    }


def initier_paiement_ecom_api(request, commande) -> dict:
    from stock.geniuspay import GeniusPayError, montant_xof
    from stock.paiement_service import initier_paiement_commande

    min_amount = int(getattr(settings, 'GENIUSPAY_MIN_AMOUNT', 200) or 200)
    if montant_xof(commande.total) < min_amount:
        espece = get_moyen_espece()
        commande.moyen_paiement = espece
        commande.save(update_fields=['moyen_paiement'])
        payload = paiement_payload(request, commande)
        payload.update({
            'pending': False,
            'fallback_espece': True,
            'warning': (
                f'Paiement numérique disponible à partir de {min_amount} FCFA. '
                'Le règlement se fera en espèces à la livraison ou au retrait.'
            ),
        })
        return payload

    try:
        gp = initier_paiement_commande(commande, source='ecom', request=request)
    except GeniusPayError as exc:
        payload = paiement_payload(request, commande)
        payload.update({
            'pending': False,
            'error': str(exc),
            'checkout_url': '',
        })
        return payload

    if not gp.checkout_url:
        payload = paiement_payload(request, commande, gp)
        payload.update({
            'pending': False,
            'error': 'URL de paiement GeniusPay manquante.',
        })
        return payload

    payload = paiement_payload(request, commande, gp)
    payload['pending'] = True
    return payload
