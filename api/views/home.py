"""Accueil agrégé (feed mobile)."""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from Userauths.models import LocalEntrepot
from ecom.services import (
    FREE_SHIPPING_THRESHOLD,
    lignes_pieces_plus_commandees,
    lignes_vues_recentes,
    MAX_VUES_RECENTES_INDEX,
    queryset_categories_catalogue,
)

from api.context import get_cart_count, get_local_from_request, local_payload
from api.serializers.piece import row_to_piece_card


class HomeView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        local = get_local_from_request(request)
        localites = LocalEntrepot.objects.all().order_by('nom')
        categories = queryset_categories_catalogue()
        top_rows = lignes_pieces_plus_commandees(local)[:12]
        top_products = [row_to_piece_card(row, request) for row in top_rows]

        recent_products = []
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'client':
            recent_rows = lignes_vues_recentes(
                request.user, local, limit=MAX_VUES_RECENTES_INDEX,
            )
            recent_products = [row_to_piece_card(row, request) for row in recent_rows]

        cart_count = 0
        if request.user.is_authenticated:
            cart_count = get_cart_count(request.user, local)

        return Response({
            'local_selected': local_payload(local),
            'localites': [
                {'code': str(loc.code), 'nom': loc.nom}
                for loc in localites
            ],
            'categories': [c.as_dict() for c in categories],
            'top_products': top_products,
            'recent_products': recent_products,
            'cart_count': cart_count,
            'free_shipping_threshold': str(FREE_SHIPPING_THRESHOLD),
        })
