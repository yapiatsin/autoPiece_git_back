"""Favoris et vues récentes."""
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ecom.models import FavoriPiece
from ecom.services import lignes_favoris, lignes_vues_recentes, MAX_VUES_RECENTES_PREVIEW
from stock.models import Piece

from api.context import get_local_from_request
from api.permissions import IsClient
from api.serializers.piece import row_to_piece_card


class FavoriteListView(APIView):
    permission_classes = [IsClient]

    def get(self, request):
        local = get_local_from_request(request)
        rows = lignes_favoris(request.user, local)
        results = [row_to_piece_card(row, request, favori_ids={row['piece'].pk}) for row in rows]
        return Response({'count': len(results), 'results': results})


class FavoriteAddView(APIView):
    permission_classes = [IsClient]

    def post(self, request, piece_id):
        piece = get_object_or_404(Piece, pk=piece_id)
        _, created = FavoriPiece.objects.get_or_create(utilisateur=request.user, piece=piece)
        return Response({
            'success': True,
            'created': created,
            'favoris_count': FavoriPiece.objects.filter(utilisateur=request.user).count(),
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class FavoriteRemoveView(APIView):
    permission_classes = [IsClient]

    def delete(self, request, piece_id):
        deleted, _ = FavoriPiece.objects.filter(
            utilisateur=request.user, piece_id=piece_id,
        ).delete()
        return Response({
            'success': True,
            'deleted': deleted > 0,
            'favoris_count': FavoriPiece.objects.filter(utilisateur=request.user).count(),
        })


class FavoriteToggleView(APIView):
    permission_classes = [IsClient]

    def post(self, request, piece_id):
        piece = get_object_or_404(Piece, pk=piece_id)
        fav = FavoriPiece.objects.filter(utilisateur=request.user, piece=piece).first()
        if fav:
            fav.delete()
            est_favori = False
        else:
            FavoriPiece.objects.create(utilisateur=request.user, piece=piece)
            est_favori = True
        return Response({
            'success': True,
            'est_favori': est_favori,
            'favoris_count': FavoriPiece.objects.filter(utilisateur=request.user).count(),
        })


class RecentlyViewedView(APIView):
    permission_classes = [IsClient]

    def get(self, request):
        local = get_local_from_request(request)
        limit = min(int(request.query_params.get('limit', MAX_VUES_RECENTES_PREVIEW) or MAX_VUES_RECENTES_PREVIEW), 50)
        rows = lignes_vues_recentes(request.user, local, limit=limit)
        favori_ids = set(
            FavoriPiece.objects.filter(utilisateur=request.user).values_list('piece_id', flat=True)
        )
        results = [row_to_piece_card(row, request, favori_ids=favori_ids) for row in rows]
        return Response({'count': len(results), 'results': results})
