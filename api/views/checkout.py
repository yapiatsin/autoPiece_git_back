"""Checkout livraison / retrait."""
from decimal import Decimal

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ecom.models import CommuneLivraison, PaysLivraison, VilleLivraison
from ecom.services import (
    FREE_SHIPPING_THRESHOLD,
    enrichir_piece_stock,
    frais_livraison_payload,
    get_frais_livraison,
    liste_communes_actives,
    liste_pays_actifs,
    liste_villes_actives,
    quantite_disponible_piece,
    queryset_panier_online_actif,
    valider_commande_online,
)
from stock.models import Commande, PanierItem
from stock.stock_local_service import total_panier_items

from api.context import get_local_from_request, local_payload
from api.permissions import IsClient
from api.serializers.cart import CartItemSerializer
from api.serializers.checkout import CheckoutConfirmSerializer
from api.services.paiement import (
    initier_paiement_ecom_api,
    moyens_paiement_client,
    resolve_moyen_paiement,
)


def _local_required(request):
    local = get_local_from_request(request)
    if not local:
        return None, Response(
            {'detail': 'Sélectionnez une localité.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return local, None


class CheckoutPreviewView(APIView):
    permission_classes = [IsClient]

    def get(self, request):
        local, err = _local_required(request)
        if err:
            return err
        panier = queryset_panier_online_actif(request.user, local).first()
        items = list(
            PanierItem.objects.filter(panier=panier).select_related('piece', 'piece__categorie', 'piece__sous_categorie')
        ) if panier else []
        if not items:
            return Response({'detail': 'Votre panier est vide.'}, status=status.HTTP_400_BAD_REQUEST)

        for item in items:
            item.stock_disponible = quantite_disponible_piece(item.piece, local)
            enrichir_piece_stock(item.piece, local)

        sous_total = total_panier_items(items, local, panier=panier)
        pays_list = list(liste_pays_actifs())
        pays_defaut = next((p for p in pays_list if p.code == 'CI'), pays_list[0] if pays_list else None)
        villes_list = list(liste_villes_actives(pays_defaut.pk if pays_defaut else None))
        ville_defaut = next(
            (v for v in villes_list if v.nom.lower() == 'abidjan'),
            villes_list[0] if villes_list else None,
        )
        communes_list = list(liste_communes_actives(ville_defaut.pk if ville_defaut else None))
        frais = get_frais_livraison(ville_defaut, sous_total, 'livraison') if ville_defaut else Decimal('0')

        profil = getattr(request.user, 'profil', None)
        return Response({
            'local_selected': local_payload(local),
            'items': CartItemSerializer(items, many=True, context={'request': request}).data,
            'sous_total': sous_total,
            'frais_livraison': frais,
            'total': sous_total + frais,
            'free_shipping_threshold': FREE_SHIPPING_THRESHOLD,
            'mode_reception_choices': [
                {'value': 'livraison', 'label': 'Livraison'},
                {'value': 'retrait', 'label': 'Retrait en magasin'},
            ],
            'pays_list': [{'id': p.pk, 'nom': p.nom, 'code': p.code} for p in pays_list],
            'pays_defaut_id': pays_defaut.pk if pays_defaut else None,
            'villes_list': [
                {'id': v.pk, 'nom': v.nom, 'frais': float(v.frais_livraison or 0)}
                for v in villes_list
            ],
            'ville_defaut_id': ville_defaut.pk if ville_defaut else None,
            'communes_list': [{'id': c.pk, 'nom': c.nom} for c in communes_list],
            'defaults': {
                'telephone': request.user.contact or '',
                'adresse': getattr(profil, 'adresse', '') or '',
                'email': request.user.email,
                'nom': request.user.get_full_name() or request.user.username,
            },
            'moyens_paiement': moyens_paiement_client(),
            'moyen_defaut_code': 'geniuspay',
            'geniuspay_min_amount': int(getattr(settings, 'GENIUSPAY_MIN_AMOUNT', 200) or 200),
        })


class CheckoutVillesView(APIView):
    permission_classes = [IsClient]

    def get(self, request):
        pays_id = request.query_params.get('pays_id')
        villes = liste_villes_actives(pays_id)
        return Response({
            'results': [
                {'id': v.pk, 'nom': v.nom, 'frais': float(v.frais_livraison or 0)}
                for v in villes
            ],
        })


class CheckoutCommunesView(APIView):
    permission_classes = [IsClient]

    def get(self, request):
        ville_id = request.query_params.get('ville_id')
        communes = liste_communes_actives(ville_id)
        return Response({'results': [{'id': c.pk, 'nom': c.nom} for c in communes]})


class CheckoutFraisView(APIView):
    permission_classes = [IsClient]

    def get(self, request):
        ville_id = request.query_params.get('ville_id')
        sous_total = Decimal(request.query_params.get('sous_total') or '0')
        mode = request.query_params.get('mode_reception') or 'livraison'
        ville = VilleLivraison.objects.filter(pk=ville_id, actif=True).select_related('pays').first()
        return Response(frais_livraison_payload(ville, sous_total, mode))


class CheckoutConfirmView(APIView):
    permission_classes = [IsClient]

    def post(self, request):
        local, err = _local_required(request)
        if err:
            return err
        inp = CheckoutConfirmSerializer(data=request.data)
        inp.is_valid(raise_exception=True)
        data = inp.validated_data
        mode = data['mode_reception']
        pays = ville = commune = None
        if mode == 'livraison':
            pays = PaysLivraison.objects.filter(pk=data['pays_id'], actif=True).first()
            ville = VilleLivraison.objects.filter(pk=data['ville_id'], actif=True).select_related('pays').first()
            commune = CommuneLivraison.objects.filter(pk=data['commune_id'], actif=True).select_related('ville').first()
            if not pays or not ville or not commune:
                return Response({'detail': 'Zone de livraison invalide.'}, status=status.HTTP_400_BAD_REQUEST)
            if not (data.get('telephone_livraison') or '').strip() and not (request.user.contact or '').strip():
                return Response(
                    {'telephone_livraison': ['Téléphone requis.']},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        moyen = resolve_moyen_paiement(data.get('moyen_paiement'))
        try:
            commande, ticket = valider_commande_online(
                request.user,
                local,
                mode_reception=mode,
                pays=pays,
                ville=ville,
                commune=commune,
                adresse_domicile=data.get('adresse_domicile', ''),
                telephone_livraison=data.get('telephone_livraison', ''),
                instruction_livraison=data.get('instruction_livraison', ''),
                moyen_paiement=moyen,
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        from api.views.orders import build_order_detail

        paiement = None
        if (moyen.code or '').lower() == 'geniuspay':
            paiement = initier_paiement_ecom_api(request, commande)
            commande = Commande.objects.select_related('moyen_paiement').prefetch_related(
                'paiements_geniuspay'
            ).get(pk=commande.pk)

        return Response({
            'success': True,
            'commande': build_order_detail(request, commande),
            'ticket_numero': ticket.numero,
            'paiement': paiement,
        }, status=status.HTTP_201_CREATED)
