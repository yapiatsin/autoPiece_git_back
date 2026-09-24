"""Vues FNE de la caisse : relance de certification, reçu FNE (ESC/POS et PDF)."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from stock.fne_service import (
    certifier_commande,
    commande_eligible,
    fne_active,
    resume_fne,
)
from stock.models import FactureFNE, PanierItem, Ticket


def _commande_caisse(request, ticket_numero):
    """Commande payée du ticket, dans la localité de l'utilisateur. (commande, erreur JSON)"""
    from stock.views import get_user_localite

    ticket = get_object_or_404(Ticket, numero=ticket_numero)
    commande = ticket.commande
    if not commande.paye:
        return None, JsonResponse(
            {'success': False, 'error': "Cette commande n'est pas encore payée."},
            status=400,
        )
    localite = get_user_localite(request.user)
    if localite and commande.panier.local_entrepot_id != localite.pk:
        return None, JsonResponse(
            {'success': False, 'error': 'Accès refusé à cette localité.'},
            status=403,
        )
    return commande, None


def _facture_certifiee(request, ticket_numero):
    commande, erreur = _commande_caisse(request, ticket_numero)
    if erreur:
        return None, erreur
    facture = (
        FactureFNE.objects.select_related('commande', 'commande__utilisateur', 'commande__ticket')
        .filter(commande=commande, statut=FactureFNE.STATUT_CERTIFIEE)
        .first()
    )
    if facture is None:
        return None, JsonResponse(
            {'success': False, 'error': "Aucune facture FNE certifiée pour ce ticket."},
            status=404,
        )
    return facture, None


@login_required(login_url='connexion')
@require_POST
def caisse_fne_certifier(request, ticket_numero):
    """POST → (re)lance la certification FNE d'une vente déjà encaissée."""
    commande, erreur = _commande_caisse(request, ticket_numero)
    if erreur:
        return erreur
    if not fne_active():
        return JsonResponse(
            {'success': False, 'error': "La FNE n'est pas activée (FNE_ENABLED / FNE_API_KEY)."},
            status=400,
        )
    if not commande_eligible(commande):
        return JsonResponse(
            {'success': False, 'error': "Seules les ventes caisse payées en espèces sont certifiées."},
            status=400,
        )
    items = list(PanierItem.objects.filter(panier=commande.panier).select_related('piece'))
    # Relance manuelle : forcer=True ignore un éventuel statut « en cours » coincé
    # (processus tué, délai dépassé) pour pouvoir recommencer depuis le bouton FNE.
    facture = certifier_commande(
        commande, panier_items=items, caissier=request.user, forcer=True,
    )
    fne = resume_fne(facture)
    if fne is None:
        return JsonResponse(
            {'success': False, 'fne': None, 'error': 'Certification FNE impossible pour cette vente.'},
            status=400,
        )
    ok = fne['certifiee']
    return JsonResponse(
        {'success': ok, 'fne': fne, 'error': '' if ok else fne['message']},
        status=200 if ok else 502,
    )


@login_required(login_url='connexion')
@require_GET
def printer_escpos_fne_view(request, ticket_numero):
    """GET → reçu FNE au format ESC/POS brut, a envoyer via WebUSB."""
    from stock import printer_service

    facture, erreur = _facture_certifiee(request, ticket_numero)
    if erreur:
        return erreur
    payload = printer_service.build_fne_receipt_bytes(facture)
    response = HttpResponse(payload, content_type='application/octet-stream')
    response['Content-Disposition'] = f'attachment; filename="fne-{ticket_numero}.escpos"'
    response['Cache-Control'] = 'no-store'
    return response


@login_required(login_url='connexion')
@require_GET
def caisse_fne_pdf(request, ticket_numero):
    """GET → reçu FNE en PDF, imprimé depuis le navigateur quand WebUSB manque."""
    from stock.fne_receipt import render_fne_receipt_pdf

    facture, erreur = _facture_certifiee(request, ticket_numero)
    if erreur:
        return erreur
    response = HttpResponse(render_fne_receipt_pdf(facture), content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="fne-{facture.reference}.pdf"'
    return response
