"""Compte client."""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from Userauths.models import ProfilUser

from api.permissions import IsClient
from api.serializers.account import AccountAddressSerializer, AccountProfileSerializer
from api.serializers.auth import ProfilClientSerializer, ProfilClientWriteSerializer
from ecom.dashboard import build_client_dashboard, parse_dashboard_period


class AccountView(APIView):
    permission_classes = [IsClient]

    def get(self, request):
        profil, _ = ProfilUser.objects.get_or_create(user=request.user)
        return Response({
            'profile': AccountProfileSerializer(profil).data,
            'profil': ProfilClientSerializer(profil, context={'request': request}).data,
        })

    def patch(self, request):
        profil, _ = ProfilUser.objects.get_or_create(user=request.user)
        serializer = ProfilClientWriteSerializer(profil, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        profil = serializer.save()
        request.user.refresh_from_db()
        return Response({
            'profile': AccountProfileSerializer(profil).data,
            'profil': ProfilClientSerializer(profil, context={'request': request}).data,
        })


class DashboardView(APIView):
    permission_classes = [IsClient]

    def get(self, request):
        mois, annee, _ = parse_dashboard_period(
            request.query_params.get('mois'),
            request.query_params.get('annee'),
        )
        data = build_client_dashboard(request.user, mois, annee)
        for key in [k for k in data if k.startswith('commandes_obj')]:
            data.pop(key, None)
        return Response(data)


class AccountAddressView(APIView):
    permission_classes = [IsClient]

    def patch(self, request):
        profil, _ = ProfilUser.objects.get_or_create(user=request.user)
        serializer = AccountAddressSerializer(profil, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        profil = serializer.save()
        return Response(AccountAddressSerializer(profil).data)


class AccountPhotoView(APIView):
    permission_classes = [IsClient]

    def post(self, request):
        profil, _ = ProfilUser.objects.get_or_create(user=request.user)
        photo = request.FILES.get('photo')
        if not photo:
            return Response({'detail': 'Fichier photo requis.'}, status=status.HTTP_400_BAD_REQUEST)
        profil.photo = photo
        profil.save(update_fields=['photo', 'date_modification'])
        return Response(ProfilClientSerializer(profil, context={'request': request}).data)
