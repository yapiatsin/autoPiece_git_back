"""Panier client en ligne."""
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ecom.services import (
    FREE_SHIPPING_THRESHOLD,
    ajouter_au_panier_online,
    definir_quantite_panier_piece,
    enrichir_piece_stock,
    mettre_a_jour_quantite_panier,
    quantite_disponible_piece,
    queryset_panier_online_actif,
    retirer_du_panier,
)
from stock.models import Panier, PanierItem, Piece
from stock.stock_local_service import total_panier_items

from api.context import get_local_from_request, local_payload
from api.permissions import IsClient
from api.serializers.cart import (
    CartAddItemSerializer,
    CartItemSerializer,
    CartSetPieceQtySerializer,
    CartUpdateItemSerializer,
)


def _local_required(request):
    local = get_local_from_request(request)
    if not local:
        return None, Response(
            {'detail': 'Sélectionnez une localité (header X-Ecom-Local ou POST /localites/select/).'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return local, None


def _build_cart_response(request, panier, local):
    if not panier:
        return {
            'panier': None,
            'sous_total': 0,
            'total_quantite': 0,
            'free_shipping_threshold': str(FREE_SHIPPING_THRESHOLD),
            'local_selected': local_payload(local),
        }
    items = list(
        PanierItem.objects.filter(panier=panier).select_related('piece', 'piece__categorie')
    )
    for item in items:
        item.stock_disponible = quantite_disponible_piece(item.piece, local)
        enrichir_piece_stock(item.piece, local)
    sous_total = total_panier_items(items, local, panier=panier)
    total_qty = sum(i.quantite for i in items)
    return {
        'panier': {
            'id': panier.id,
            'localite': local_payload(local),
            'items': CartItemSerializer(items, many=True, context={'request': request}).data,
            'sous_total': sous_total,
            'total_quantite': total_qty,
            'free_shipping_threshold': FREE_SHIPPING_THRESHOLD,
        },
        'sous_total': sous_total,
        'total_quantite': total_qty,
        'free_shipping_threshold': str(FREE_SHIPPING_THRESHOLD),
        'local_selected': local_payload(local),
    }


class CartView(APIView):
    permission_classes = [IsClient]

    def get(self, request):
        local, err = _local_required(request)
        if err:
            return err
        panier = queryset_panier_online_actif(request.user, local).first()
        return Response(_build_cart_response(request, panier, local))

    def delete(self, request):
        local, err = _local_required(request)
        if err:
            return err
        panier = queryset_panier_online_actif(request.user, local).first()
        if panier:
            PanierItem.objects.filter(panier=panier).delete()
            panier.delete()
        return Response(_build_cart_response(request, None, local))


class CartAddItemView(APIView):
    permission_classes = [IsClient]

    def post(self, request):
        local, err = _local_required(request)
        if err:
            return err
        inp = CartAddItemSerializer(data=request.data)
        inp.is_valid(raise_exception=True)
        piece = get_object_or_404(Piece, pk=inp.validated_data['piece_id'])
        quantite = inp.validated_data.get('quantite', 1)
        try:
            ajouter_au_panier_online(request.user, local, piece, quantite)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        panier = queryset_panier_online_actif(request.user, local).first()
        return Response(_build_cart_response(request, panier, local), status=status.HTTP_201_CREATED)


class CartUpdateItemView(APIView):
    permission_classes = [IsClient]

    def patch(self, request, item_id):
        local, err = _local_required(request)
        if err:
            return err
        inp = CartUpdateItemSerializer(data=request.data)
        inp.is_valid(raise_exception=True)
        quantite = inp.validated_data['quantite']
        try:
            if quantite == 0:
                retirer_du_panier(request.user, local, item_id)
            else:
                mettre_a_jour_quantite_panier(request.user, local, item_id, quantite)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        panier = queryset_panier_online_actif(request.user, local).first()
        return Response(_build_cart_response(request, panier, local))


class CartSetPieceQuantityView(APIView):
    permission_classes = [IsClient]

    def put(self, request, piece_id):
        local, err = _local_required(request)
        if err:
            return err
        inp = CartSetPieceQtySerializer(data=request.data)
        inp.is_valid(raise_exception=True)
        piece = get_object_or_404(Piece, pk=piece_id)
        try:
            definir_quantite_panier_piece(
                request.user, local, piece, inp.validated_data['quantite'],
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        panier = queryset_panier_online_actif(request.user, local).first()
        return Response(_build_cart_response(request, panier, local))
