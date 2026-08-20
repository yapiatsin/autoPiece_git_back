"""Compte client."""
from calendar import month_name
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from Userauths.models import ProfilUser
from ecom.models import FavoriPiece, VueRecentePiece
from stock.models import Commande

from api.permissions import IsClient
from api.serializers.account import AccountAddressSerializer, AccountProfileSerializer
from api.serializers.auth import ProfilClientSerializer, ProfilClientWriteSerializer

_MOIS_LABELS = {
    1: 'Janvier',
    2: 'Février',
    3: 'Mars',
    4: 'Avril',
    5: 'Mai',
    6: 'Juin',
    7: 'Juillet',
    8: 'Août',
    9: 'Septembre',
    10: 'Octobre',
    11: 'Novembre',
    12: 'Décembre',
}


def _parse_period(request):
    today = date.today()
    try:
        annee = int(request.query_params.get('annee') or today.year)
    except (TypeError, ValueError):
        annee = today.year
    try:
        mois = int(request.query_params.get('mois') or today.month)
    except (TypeError, ValueError):
        mois = today.month
    if mois < 1 or mois > 12:
        mois = today.month
    annees_disponibles = [today.year - i for i in range(10)]
    if annee not in annees_disponibles:
        annee = today.year
    return mois, annee, annees_disponibles


def _build_account_stats(user, request):
    mois, annee, annees_disponibles = _parse_period(request)

    commandes_qs = Commande.objects.filter(
        commande_en_ligne=True,
        panier__utilisateur=user,
    )
    commandes_periode = commandes_qs.filter(date__year=annee, date__month=mois)
    commandes_payees_periode = commandes_periode.filter(paye=True)
    total_achats = (
        commandes_payees_periode.aggregate(s=Sum('total'))['s'] or Decimal('0')
    )

    return {
        # Compteurs filtrés par la période sélectionnée
        'commandes': commandes_periode.count(),
        'favoris': FavoriPiece.objects.filter(
            utilisateur=user,
            date_ajout__year=annee,
            date_ajout__month=mois,
        ).count(),
        'vues_recentes': VueRecentePiece.objects.filter(
            utilisateur=user,
            date_vue__year=annee,
            date_vue__month=mois,
        ).count(),
        'total_achats_periode': total_achats,
        'nb_commandes_periode': commandes_payees_periode.count(),
        'mois': mois,
        'mois_label': _MOIS_LABELS.get(mois, month_name[mois] if 1 <= mois <= 12 else ''),
        'annee': annee,
        'annees_disponibles': annees_disponibles,
    }


class AccountView(APIView):
    permission_classes = [IsClient]

    def get(self, request):
        profil, _ = ProfilUser.objects.get_or_create(user=request.user)
        return Response({
            'profile': AccountProfileSerializer(profil).data,
            'profil': ProfilClientSerializer(profil, context={'request': request}).data,
            'stats': _build_account_stats(request.user, request),
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
            'stats': _build_account_stats(request.user, request),
        })


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
