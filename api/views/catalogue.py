"""Catalogue produits."""
from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ecom.models import FavoriPiece
from ecom.services import (
    enregistrer_recherche,
    enregistrer_vue_recente,
    enrichir_piece_stock,
    filtrer_pieces_boutique,
    get_local_from_code,
    lignes_catalogue_shop,
    quantite_disponible_piece,
    queryset_categories_catalogue,
    queryset_panier_online_actif,
    queryset_piece_fiche,
)
from stock.models import PanierItem
from stock.stock_local_service import get_prix_unitaire

from api.context import django_request, get_local_from_request
from api.serializers.piece import build_piece_card, row_to_piece_card


class CategoryListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        categories = queryset_categories_catalogue()
        return Response({
            'results': [c.as_dict() for c in categories],
        })


class ProductListView(APIView):
    permission_classes = [AllowAny]

    def _favori_ids(self, request):
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'client':
            return set(
                FavoriPiece.objects.filter(utilisateur=request.user).values_list('piece_id', flat=True)
            )
        return set()

    def _panier_qty(self, request, local):
        if not request.user.is_authenticated or not local:
            return {}
        panier = queryset_panier_online_actif(request.user, local).first()
        if not panier:
            return {}
        return dict(
            PanierItem.objects.filter(panier=panier).values_list('piece_id', 'quantite')
        )

    def get(self, request):
        drf_req = django_request(request)
        local = get_local_from_request(request)
        filter_local = local
        localite_param = request.query_params.get('localite', '').strip()
        if localite_param:
            from ecom.services import get_local_from_code
            filter_local = get_local_from_code(localite_param) or local

        q = request.query_params.get('q', '').strip()
        if q:
            enregistrer_recherche(drf_req, q)

        qs = filtrer_pieces_boutique(drf_req)
        sort = request.query_params.get('sort', 'designation')
        if sort == 'price_asc':
            qs = qs.order_by('prix_unitaire', 'designation')
        elif sort == 'price_desc':
            qs = qs.order_by('-prix_unitaire', 'designation')
        else:
            qs = qs.order_by('designation')

        page = max(int(request.query_params.get('page', 1) or 1), 1)
        page_size = min(max(int(request.query_params.get('page_size', 40) or 40), 1), 100)
        rows_all = lignes_catalogue_shop(list(qs), local, filter_local=filter_local)
        total = len(rows_all)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = rows_all[start:end]

        favori_ids = self._favori_ids(request)
        panier_qty = self._panier_qty(request, local)
        results = [
            row_to_piece_card(row, request, favori_ids=favori_ids, panier_qty_by_piece=panier_qty)
            for row in page_rows
        ]
        return Response({
            'count': total,
            'page': page,
            'page_size': page_size,
            'local_selected': {'code': str(local.code), 'nom': local.nom} if local else None,
            'results': results,
        })


class ProductDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, pk):
        piece = get_object_or_404(queryset_piece_fiche(), pk=pk)
        local = get_local_from_request(request)
        enrichir_piece_stock(piece, local)

        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'client':
            enregistrer_vue_recente(request.user, piece)

        prix = get_prix_unitaire(piece, local) if local else piece.prix_unitaire
        quantite = quantite_disponible_piece(piece, local) if local else None
        est_favori = False
        quantite_panier = 0
        if request.user.is_authenticated and getattr(request.user, 'role', None) == 'client':
            est_favori = FavoriPiece.objects.filter(
                utilisateur=request.user, piece=piece,
            ).exists()
            if local:
                panier = queryset_panier_online_actif(request.user, local).first()
                if panier:
                    item = PanierItem.objects.filter(panier=panier, piece=piece).first()
                    quantite_panier = item.quantite if item else 0

        data = build_piece_card(
            piece,
            request=request,
            prix_affiche=prix,
            quantite=quantite,
            localite_code=str(local.code) if local else '',
            localite_nom=local.nom if local else '',
            est_favori=est_favori,
            quantite_panier=quantite_panier,
        )

        stocks = []
        for sl in piece.stocks.filter(
            active_sortie=True, quantite_disponible__gt=0,
        ).select_related('local_entrepot'):
            stocks.append({
                'localite_code': str(sl.local_entrepot.code),
                'localite_nom': sl.local_entrepot.nom,
                'quantite': sl.quantite_disponible,
                'prix': get_prix_unitaire(piece, sl.local_entrepot),
            })
        data['stocks_par_localite'] = stocks
        data['prix_catalogue'] = piece.prix_unitaire
        data['emplacement'] = piece.emplacement or ''
        return Response(data)
