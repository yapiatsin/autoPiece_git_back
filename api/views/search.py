"""Recherche (historique et popularité)."""
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.context import django_request
from api.permissions import IsClient
from ecom.services import (
    effacer_recherches_recentes,
    liste_recherches_populaires,
    liste_recherches_recentes,
)


class SearchRecentView(APIView):
    def get_permissions(self):
        if self.request.method == 'DELETE':
            return [IsClient()]
        return [AllowAny()]

    def get(self, request):
        terms = liste_recherches_recentes(django_request(request))
        return Response({'results': terms})

    def delete(self, request):
        count = effacer_recherches_recentes(django_request(request))
        return Response({'success': True, 'deleted': count})


class SearchPopularView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        terms = liste_recherches_populaires()
        return Response({'results': terms})
