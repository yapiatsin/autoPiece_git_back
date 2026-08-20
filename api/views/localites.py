"""Localités e-commerce."""
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from Userauths.models import LocalEntrepot

from api.context import get_local_from_request, local_payload
from api.permissions import IsClient
from api.serializers.piece import LocaliteSerializer
from ecom.services import filtrer_localites_catalogue, get_local_from_code


class LocaliteListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        qs = filtrer_localites_catalogue(request._request)
        results = [
            {
                'code': loc.code,
                'nom': loc.nom,
                'nb_pieces': getattr(loc, 'nb_pieces', 0),
            }
            for loc in qs
        ]
        serializer = LocaliteSerializer(results, many=True)
        return Response({
            'local_selected': local_payload(get_local_from_request(request)),
            'results': serializer.data,
        })


class LocaliteSelectView(APIView):
    permission_classes = [IsClient]

    def post(self, request):
        code = (request.data.get('code') or request.data.get('local_id') or '').strip()
        if not code:
            return Response({'detail': 'Code localité requis.'}, status=status.HTTP_400_BAD_REQUEST)
        local = get_local_from_code(code)
        if not local:
            return Response({'detail': 'Localité introuvable.'}, status=status.HTTP_404_NOT_FOUND)
        request.user.local_entrepot = local
        request.user.save(update_fields=['local_entrepot'])
        return Response({'success': True, 'local_selected': local_payload(local)})
