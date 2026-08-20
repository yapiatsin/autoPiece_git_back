"""
API legacy — dépréciée.

Utilisez /api/v1/ pour l'application mobile client.
"""
from django.urls import path
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class DeprecatedAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                'detail': 'Cette API est dépréciée. Utilisez /api/v1/.',
                'migration': '/api/v1/',
            },
            status=410,
        )


urlpatterns = [
    path('', DeprecatedAPIView.as_view(), name='api_deprecated'),
]
