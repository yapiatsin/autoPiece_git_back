"""Vues API v1 — auth client JWT."""
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from Userauths.models import CustomUser, ProfilUser

from api.context import get_cart_count, get_local_from_request, local_payload
from api.permissions import IsClient
from api.serializers.auth import (
    ClientRegisterSerializer,
    ClientUserSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    ProfilClientSerializer,
    RegisterOtpResendSerializer,
    RegisterOtpVerifySerializer,
)
from api.services.otp import OTP_EXPIRY_SECONDS, activation_otp_status


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {'refresh': str(refresh), 'access': str(refresh.access_token)}


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ClientRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        email_sent = getattr(user, '_otp_email_sent', True)
        expires_in = getattr(user, '_otp_expires_in', OTP_EXPIRY_SECONDS)
        detail = (
            f"Compte créé. Un code OTP a été envoyé à {user.email}."
            if email_sent
            else (
                f"Compte créé, mais l'email n'a pas pu être envoyé à {user.email}. "
                "Utilisez « Demander un nouveau code »."
            )
        )
        return Response({
            'detail': detail,
            'email': user.email,
            'otp_expires_in': expires_in,
            'email_sent': email_sent,
        }, status=status.HTTP_201_CREATED)


class RegisterOtpVerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterOtpVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response({
            'detail': 'Compte activé. Vous pouvez vous connecter.',
            'email': user.email,
        })


class RegisterOtpResendView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterOtpResendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        detail = (
            f"Un nouveau code OTP a été envoyé à {result['email']}."
            if result['email_sent']
            else "Le code a été généré mais l'email n'a pas pu être envoyé."
        )
        return Response({
            'detail': detail,
            'email': result['email'],
            'otp_expires_in': result['otp_expires_in'],
            'remaining_seconds': result['remaining_seconds'],
            'otp_expired': result['otp_expired'],
            'email_sent': result['email_sent'],
        })


class RegisterOtpStatusView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        email = (request.query_params.get('email') or '').strip().lower()
        if not email:
            return Response(
                {'email': ['Paramètre email requis.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = CustomUser.objects.filter(
            email__iexact=email, role='client', is_active=False,
        ).first()
        if not user:
            return Response({
                'remaining_seconds': 0,
                'otp_expired': True,
            })
        return Response(activation_otp_status(user))


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        tokens = get_tokens_for_user(user)
        return Response({
            'user': ClientUserSerializer(user).data,
            'access': tokens['access'],
            'refresh': tokens['refresh'],
        })


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except Exception:
                pass
        return Response({'detail': 'Déconnexion réussie.'})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        local = get_local_from_request(request)
        profil = ProfilUser.objects.filter(user=request.user).first()
        return Response({
            'user': ClientUserSerializer(request.user).data,
            'profil': ProfilClientSerializer(profil, context={'request': request}).data if profil else None,
            'local_selected': local_payload(local),
            'cart_count': get_cart_count(request.user, local),
        })


class PasswordChangeView(APIView):
    permission_classes = [IsClient]

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(serializer.validated_data['ancien_password']):
            return Response(
                {'ancien_password': ['Mot de passe actuel incorrect.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.set_password(serializer.validated_data['nouveau_password'])
        user.save(update_fields=['password'])
        return Response({'detail': 'Mot de passe modifié.'})
