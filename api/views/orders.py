"""Commandes client."""
from decimal import Decimal

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ecom.services import annuler_commande_client, confirmer_reception_client
from stock.models import Commande, PanierItem
from stock.stock_local_service import total_panier_items

from api.permissions import IsClient
from api.services.paiement import initier_paiement_ecom_api, paiement_payload


def _client_orders_qs(user):
    return Commande.objects.filter(
        commande_en_ligne=True,
        panier__utilisateur=user,
    ).select_related(
        'panier', 'panier__local_entrepot',
        'panier__livraison_pays', 'panier__livraison_ville', 'panier__livraison_commune',
        'moyen_paiement', 'livreur',
    ).prefetch_related('paiements_geniuspay').order_by('-date')


def build_order_detail(request, commande):
    panier = commande.panier
    items_qs = PanierItem.objects.filter(panier=panier).select_related('piece', 'piece__categorie', 'piece__sous_categorie')
    items = []
    for item in items_qs:
        pu = item.prix_unitaire_applique
        items.append({
            'piece_id': item.piece_id,
            'designation': item.piece.designation,
            'quantite': item.quantite,
            'prix_unitaire': pu,
            'prix_total': pu * item.quantite,
        })
    frais = getattr(panier, 'frais_livraison', None) or Decimal('0')
    sous_total = commande.total_sans_remise or total_panier_items(list(items_qs), panier.local_entrepot, panier=panier)
    adresse = None
    if panier.mode_reception == 'livraison':
        adresse = {
            'pays': panier.livraison_pays.nom if panier.livraison_pays_id else '',
            'ville': panier.livraison_ville.nom if panier.livraison_ville_id else '',
            'commune': panier.livraison_commune.nom if panier.livraison_commune_id else '',
            'adresse_domicile': panier.adresse_domicile or '',
            'telephone': panier.telephone_livraison or '',
            'instruction': panier.instruction_livraison or '',
        }
    statut_labels = dict(Commande._meta.get_field('statut_commande').choices)
    return {
        'id': commande.pk,
        'numero_commande': commande.numero_commande,
        'statut_commande': commande.statut_commande,
        'statut_label': statut_labels.get(commande.statut_commande, commande.statut_commande),
        'total': commande.total,
        'sous_total': sous_total,
        'frais_livraison': frais,
        'paye': commande.paye,
        'date': commande.date,
        'localite_nom': panier.local_entrepot.nom if panier.local_entrepot_id else '',
        'mode_reception': panier.mode_reception,
        'client_confirme_reception': commande.client_confirme_reception,
        'date_reception_client': commande.date_reception_client,
        'items': items,
        'adresse_livraison': adresse,
        'ticket_numero': panier.ticket,
        'invoice_url': request.build_absolute_uri(f'/api/v1/orders/{commande.pk}/invoice/'),
        'moyen_paiement': getattr(commande.moyen_paiement, 'nom', '') or '',
        'moyen_paiement_code': (getattr(commande.moyen_paiement, 'code', '') or ''),
        'libelle_paiement': commande.libelle_paiement,
        'panier_livre': bool(panier.panier_livre),
        'peut_confirmer_reception': (
            commande.statut_commande == 'livrer'
            and not commande.client_confirme_reception
        ),
        'paiement': paiement_payload(request, commande),
    }


class OrderListView(APIView):
    permission_classes = [IsClient]

    def get(self, request):
        qs = _client_orders_qs(request.user)
        statut = request.query_params.get('statut')
        if statut:
            qs = qs.filter(statut_commande=statut)
        results = []
        statut_labels = dict(Commande._meta.get_field('statut_commande').choices)
        for cmd in qs[:100]:
            results.append({
                'id': cmd.pk,
                'numero_commande': cmd.numero_commande,
                'statut_commande': cmd.statut_commande,
                'statut_label': statut_labels.get(cmd.statut_commande, cmd.statut_commande),
                'total': cmd.total,
                'paye': cmd.paye,
                'date': cmd.date,
                'localite_nom': cmd.panier.local_entrepot.nom if cmd.panier.local_entrepot_id else '',
                'mode_reception': cmd.panier.mode_reception,
                'client_confirme_reception': cmd.client_confirme_reception,
                'moyen_paiement_code': (getattr(cmd.moyen_paiement, 'code', '') or ''),
                'libelle_paiement': cmd.libelle_paiement,
                'panier_livre': bool(cmd.panier.panier_livre),
                'peut_confirmer_reception': (
                    cmd.statut_commande == 'livrer'
                    and not cmd.client_confirme_reception
                ),
            })
        return Response({'count': len(results), 'results': results})


class OrderDetailView(APIView):
    permission_classes = [IsClient]

    def get(self, request, commande_id):
        commande = get_object_or_404(_client_orders_qs(request.user), pk=commande_id)
        return Response(build_order_detail(request, commande))


class OrderCancelView(APIView):
    permission_classes = [IsClient]

    def post(self, request, commande_id):
        commande = get_object_or_404(_client_orders_qs(request.user), pk=commande_id)
        try:
            annuler_commande_client(commande, request.user)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        commande.refresh_from_db()
        return Response({'success': True, 'commande': build_order_detail(request, commande)})


class OrderConfirmReceiptView(APIView):
    permission_classes = [IsClient]

    def post(self, request, commande_id):
        commande = get_object_or_404(_client_orders_qs(request.user), pk=commande_id)
        try:
            confirmer_reception_client(commande, request.user)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        commande.refresh_from_db()
        return Response({'success': True, 'commande': build_order_detail(request, commande)})


class OrderInvoiceView(APIView):
    permission_classes = [IsClient]

    def get(self, request, commande_id):
        commande = get_object_or_404(
            _client_orders_qs(request.user),
            pk=commande_id,
        )
        items = list(
            PanierItem.objects.filter(panier=commande.panier).select_related('piece', 'piece__categorie', 'piece__sous_categorie')
        )
        panier = commande.panier
        frais = getattr(panier, 'frais_livraison', None) or Decimal('0')
        html = render_to_string('e_autopiece/invoice.html', {
            'commande': commande,
            'items': items,
            'frais_livraison': frais if frais > 0 else None,
            'auto_print': False,
        }, request=request._request)
        format_param = request.query_params.get('format', 'html')
        if format_param == 'html':
            return HttpResponse(html, content_type='text/html; charset=utf-8')
        return Response({
            'html': html,
            'numero_commande': commande.numero_commande,
            'web_url': request.build_absolute_uri(f'/facture/{commande.pk}/'),
        })


class OrderPayView(APIView):
    """Démarre ou relance un paiement numérique GeniusPay."""
    permission_classes = [IsClient]

    def post(self, request, commande_id):
        commande = get_object_or_404(_client_orders_qs(request.user), pk=commande_id)
        if commande.paye:
            return Response({
                'success': True,
                'commande': build_order_detail(request, commande),
                'paiement': paiement_payload(request, commande),
            })
        if commande.statut_commande == 'annuler':
            return Response(
                {'detail': 'Cette commande est annulée.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from ecom.services import get_moyen_geniuspay
        commande.moyen_paiement = get_moyen_geniuspay()
        commande.save(update_fields=['moyen_paiement'])
        paiement = initier_paiement_ecom_api(request, commande)
        commande.refresh_from_db()
        if paiement.get('error') and not paiement.get('checkout_url'):
            return Response(
                {
                    'success': False,
                    'detail': paiement['error'],
                    'commande': build_order_detail(request, commande),
                    'paiement': paiement,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({
            'success': True,
            'commande': build_order_detail(request, commande),
            'paiement': paiement,
        })


class OrderPaymentReturnView(APIView):
    """Page de retour GeniusPay (WebView mobile) — sans session web."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, commande_id):
        retour = (request.GET.get('retour') or '').strip().lower()
        ok = retour in ('ok', 'success')
        title = 'Paiement confirmé' if ok else 'Paiement'
        message = (
            'Retour vers l’application…'
            if ok
            else 'Le paiement a été annulé ou a échoué. Retour vers l’application…'
        )
        html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; min-height: 100vh;
           display: flex; align-items: center; justify-content: center;
           background: #fff8f0; color: #1a1a1d; }}
    .box {{ text-align: center; padding: 28px; }}
    h1 {{ font-size: 1.15rem; margin: 0 0 8px; }}
    p {{ color: #6b6b70; margin: 0; }}
  </style>
</head>
<body>
  <div class="box">
    <h1>{title}</h1>
    <p>{message}</p>
  </div>
</body>
</html>"""
        return HttpResponse(html, content_type='text/html; charset=utf-8')


class OrderPaymentStatusView(APIView):
    """Statut du paiement (polling mobile après page GeniusPay)."""
    permission_classes = [IsClient]

    def get(self, request, commande_id):
        from stock.geniuspay import GeniusPayError
        from stock.models import GeniusPayPaiement
        from stock.paiement_service import synchroniser_paiement

        commande = get_object_or_404(_client_orders_qs(request.user), pk=commande_id)
        gp = (
            GeniusPayPaiement.objects.filter(commande=commande)
            .order_by('-date_creation')
            .first()
        )
        if gp and not commande.paye:
            try:
                gp, _confirmed = synchroniser_paiement(gp, request=request)
                commande.refresh_from_db()
            except GeniusPayError as exc:
                return Response({
                    'success': False,
                    'pending': True,
                    'error': str(exc),
                    'paiement': paiement_payload(request, commande, gp),
                    'commande': build_order_detail(request, commande),
                }, status=status.HTTP_400_BAD_REQUEST)

        payload = paiement_payload(request, commande, gp)
        failed = bool(gp and gp.statut in ('failed', 'cancelled', 'expired'))
        return Response({
            'success': bool(commande.paye),
            'pending': payload.get('pending') and not commande.paye,
            'failed': failed and not commande.paye,
            'paiement': payload,
            'commande': build_order_detail(request, commande),
        })
