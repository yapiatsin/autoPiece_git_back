import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import user_passes_test
from django.urls import reverse, reverse_lazy
from django.views import View
from .models import (
    Categorie, SousCategorie, EntrePiece, Piece, Fournisseur, Panier, PanierItem, Commande, Ticket,
    MoyenPaiement, Notification, StockLocal, TransfertStock,
    DemandeTransfert, LigneDemandeTransfert, BonCommandePaiement,
)
from .bon_commande_vente import (
    context_bon_commande_vente,
    creer_bon_commande_paiement,
    generate_bon_commande_vente_pdf,
    nom_fichier_bon_commande_vente,
    titre_bon_commande_vente,
)
from .stock_local_service import (
    annotate_pieces_for_localite,
    annotate_provenance_derniere_entree,
    filter_pieces_avec_stock,
    filter_pieces_sous_seuil,
    filter_piece_catalogue_actif,
    filter_pieces_archivees,
    annotate_archive_info,
    piece_visible_en_localite,
    decrementer_stock,
    incrementer_stock,
    get_quantite,
    get_or_create_stock,
    get_stock,
    get_prix_unitaire,
    total_panier_items,
)
from .panier_service import (
    get_user_localite_panier,
    get_panier_accueil_actif,
    get_or_create_panier_accueil,
    utilisateur_peut_modifier_panier_accueil,
)
from .stock_transfers import (
    creer_demande_transfert,
    annuler_demande_par_demandeur,
    annuler_demande_par_donneur,
    valider_demande_par_donneur,
    confirmer_reception_demande,
    utilisateur_peut_voir_demande,
    utilisateur_peut_gerer_livraison_donneur,
    utilisateur_est_chef_donneur,
    utilisateur_est_chef_demandeur,
    _parse_lignes_post,
)
from .demande_transfert_pdf import generate_demande_transfert_pdf, titre_bon_commande
from Userauths.models import LocalEntrepot
from .forms import (
    CategorieForm, SousCategorieForm, EntrePieceForm, PieceForm, DateForm,
    FournisseurForm, UpdatePieceForm, StockLocalPrixForm,
)
from django.contrib import messages 
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.db import transaction
from django.db.models import Sum, Count, F, DecimalField, ExpressionWrapper, Q, FloatField, Prefetch
from django.db.models.functions import Coalesce
from django.views.generic import ListView, DetailView, CreateView, DeleteView, UpdateView, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from Userauths.mixins import CustomPermissionRequiredMixin
from Userauths.permissions_utils import user_has_permission
from decimal import Decimal, InvalidOperation
import pandas as pd
import textwrap
import platform
import os
from pathlib import Path
try:
    import usb
    import usb.core
    import usb.util
    HAS_USB = True
except ImportError:
    usb = None
    HAS_USB = False
import time
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from django.conf import settings
from django.views.decorators.http import require_POST
from stock.mqtt_service import publish_panier_valide, publish_paiement_valide
from .period_filters import (
    get_periode_date_range,
    resolve_filter_localite,
    dashboard_can_choose_localite as pf_can_choose_localite,
    periode_filter_context,
    build_table_period_columns,
    chart_granularity,
    append_query_string,
    build_filtre_resume,
    MOIS_FR,
)
from .export_service import export_urls
from .mes_ventes_service import build_mes_ventes_data
from .checkout_service import compute_checkout_totals
from xhtml2pdf import pisa
from django.utils import timezone
from django.utils.timezone import now
from django.utils.dateparse import parse_date
from calendar import monthrange, SUNDAY


def get_user_localite(user):
    """
    Retourne la localité (LocalEntrepot) de l'utilisateur.
    Admin / superuser → None (voit tout le stock).
    Autres rôles (accueil, caissier, livreur, chefagence, gestionnaire, …)
    → leur LocalEntrepot affecté (ou None s'il n'en ont pas).
    """
    if not getattr(user, 'is_authenticated', False):
        return None
    if user.is_superuser or getattr(user, 'role', None) == 'admin':
        return None
    return getattr(user, 'local_entrepot', None)


def pieces_queryset_for_user(user, base=None):
    """Pièces du catalogue avec quantite_disponible annotée pour la localité de l'utilisateur."""
    localite = get_user_localite(user)
    qs = filter_piece_catalogue_actif(base if base is not None else Piece.objects.all())
    qs = qs.select_related('categorie', 'sous_categorie')
    if localite:
        qs = qs.filter(stocks__local_entrepot=localite, stocks__active_sortie=True).distinct()
    return annotate_pieces_for_localite(qs, localite)


def queryset_categories_avec_sous(actif_only=True):
    sous_qs = SousCategorie.objects.order_by('ordre', 'nom')
    if actif_only:
        sous_qs = sous_qs.filter(actif=True)
    return Categorie.objects.prefetch_related(
        Prefetch('sous_categories', queryset=sous_qs)
    ).order_by('categorie')


def utilisateur_peut_fixer_prix_local(user):
    """Chef d'agence (sa localité), gestionnaire ou admin."""
    if user.is_superuser or getattr(user, 'role', None) in ('admin', 'gestionnaire'):
        return True
    return getattr(user, 'role', None) == 'chefagence'


def _pu_item_panier(item, *, panier=None, commande=None):
    """Prix unitaire d'une ligne selon la localité du panier / commande."""
    loc = None
    if panier is not None:
        loc = panier.local_entrepot
    elif commande is not None and commande.panier_id:
        loc = commande.panier.local_entrepot
    elif getattr(item, 'panier', None) is not None:
        loc = item.panier.local_entrepot
    return get_prix_unitaire(item.piece, loc, item.new_price)

def user_is_chef_agence(user):
    return user.is_superuser or getattr(user, 'role', None) in ('chefagence', 'admin')

def parse_remise_montant(raw_value, total_brut):
    """
    Remise saisie comme montant fixe (même devise que le panier), plafonné au total brut.
    """
    if total_brut is None:
        total_brut = Decimal('0.0')
    if not isinstance(total_brut, Decimal):
        total_brut = Decimal(str(total_brut))
    try:
        s = str(raw_value or '0').strip().replace(',', '.')
        remise = Decimal(s)
    except (InvalidOperation, ValueError, TypeError):
        remise = Decimal('0.0')
    if remise < 0:
        remise = Decimal('0.0')
    if remise > total_brut:
        remise = total_brut
    return remise


def remise_pourcentage(total_brut, montant_remise):
    """Pourcentage de remise (0–100) à partir du montant saisi et du total brut."""
    total_brut = Decimal(str(total_brut or 0))
    montant_remise = Decimal(str(montant_remise or 0))
    if total_brut <= 0 or montant_remise <= 0:
        return Decimal('0')
    return (montant_remise / total_brut * Decimal('100')).quantize(Decimal('0.01'))


def format_remise_pourcent(total_brut, montant_remise):
    """Libellé affiché sur l'écran et les reçus (ex. « 12.50 % »)."""
    pct = remise_pourcentage(total_brut, montant_remise)
    if pct <= 0:
        return '0 %'
    return f'{pct:.2f} %'


def format_remise_pourcent_commande(commande):
    return format_remise_pourcent(commande.total_sans_remise, commande.remise)


# ============================================================================#
#          ARCHITECTURE DE GÉNÉRATION DE REÇUS - EPSON TM-T20III              #
# ============================================================================#
ROLES_DASHBOARD_LOCAL_ONLY = frozenset({'accueil', 'caissier', 'livreur'})
ROLES_DASHBOARD_GLOBAL = frozenset({'gestionnaire', 'admin'})


def dashboard_can_choose_localite(user):
    return user.is_superuser or getattr(user, 'role', None) in ROLES_DASHBOARD_GLOBAL


def utilisateur_peut_toggle_sortie_catalogue(user):
    """Archivage catalogue global (gestionnaire / admin)."""
    return dashboard_can_choose_localite(user)


def utilisateur_peut_toggle_sortie_local(user):
    """Activation vente par localité (chef d'agence uniquement)."""
    return getattr(user, 'role', None) == 'chefagence' and get_user_localite(user) is not None

class TableauBordsView(LoginRequiredMixin, CustomPermissionRequiredMixin, TemplateView):
    login_url = 'connexion'
    template_name = 'mag/dashboard.html'
    form_class = DateForm
    permission_url = 'tbord'
    permission_required_message = (
        "Vous n'avez pas la permission d'accéder au tableau de bord."
    )

    def dispatch(self, request, *args, **kwargs):
        if getattr(request.user, 'role', None) == 'client':
            messages.error(request, 'Accès réservé au personnel du magasin.')
            return redirect('ecom_index')
        return super().dispatch(request, *args, **kwargs)

    def get_date_range(self, request):
        """Période par défaut : mois en cours."""
        today = date.today()
        periode = request.GET.get('periode', 'mois')
        form = self.form_class(request.GET)

        if periode in ('aujourdhui', 'jour'):
            return today, today, 'aujourdhui'
        if periode == 'semaine':
            debut = today - timedelta(days=today.weekday())
            return debut, today, 'semaine'
        if periode == 'mois':
            debut = date(today.year, today.month, 1)
            fin = date(today.year, today.month, monthrange(today.year, today.month)[1])
            return debut, fin, 'mois'
        if periode == 'annee':
            return date(today.year, 1, 1), date(today.year, 12, 31), 'annee'
        if periode == 'personnalise' and form.is_valid():
            debut = form.cleaned_data.get('date_debut')
            fin = form.cleaned_data.get('date_fin')
            if debut and fin:
                if debut > fin:
                    debut, fin = fin, debut
                return debut, fin, 'personnalise'
        if form.is_valid():
            debut = form.cleaned_data.get('date_debut')
            fin = form.cleaned_data.get('date_fin')
            if debut and fin:
                if debut > fin:
                    debut, fin = fin, debut
                return debut, fin, 'personnalise'

        debut = date(today.year, today.month, 1)
        fin = date(today.year, today.month, monthrange(today.year, today.month)[1])
        return debut, fin, 'mois'

    @staticmethod
    def _days_in_range(date_debut, date_fin):
        return (date_fin - date_debut).days + 1

    @staticmethod
    def _chart_granularity(date_debut, date_fin):
        return 'monthly' if TableauBordsView._days_in_range(date_debut, date_fin) > 31 else 'daily'

    def _build_evolution_series(self, panier_items_qs, commande_qs, date_debut, date_fin):
        """Séries pour graphiques ligne : jour par jour ou mois par mois."""
        granularity = self._chart_granularity(date_debut, date_fin)
        if granularity == 'daily':
            labels, qty_data, val_data = [], [], []
            d = date_debut
            while d <= date_fin:
                labels.append(str(d.day))
                qty_data.append(
                    panier_items_qs.filter(date_creation=d).aggregate(t=Sum('quantite'))['t'] or 0
                )
                val_data.append(
                    float(commande_qs.filter(date_creation=d, paye=True).aggregate(t=Sum('total'))['t'] or 0)
                )
                d += timedelta(days=1)
            return labels, qty_data, val_data, 'daily'

        labels, qty_data, val_data = [], [], []
        month_cursor = date(date_debut.year, date_debut.month, 1)
        while month_cursor <= date_fin:
            m_start = month_cursor
            m_end = date(month_cursor.year, month_cursor.month, monthrange(month_cursor.year, month_cursor.month)[1])
            if m_end > date_fin:
                m_end = date_fin
            if m_start < date_debut:
                m_start = date_debut
            labels.append(calendar.month_name[month_cursor.month][:1])
            qty_data.append(
                panier_items_qs.filter(date_creation__range=[m_start, m_end]).aggregate(t=Sum('quantite'))['t'] or 0
            )
            val_data.append(
                float(commande_qs.filter(date_creation__range=[m_start, m_end], paye=True).aggregate(t=Sum('total'))['t'] or 0)
            )
            if month_cursor.month == 12:
                month_cursor = date(month_cursor.year + 1, 1, 1)
            else:
                month_cursor = date(month_cursor.year, month_cursor.month + 1, 1)
        return labels, qty_data, val_data, 'monthly'

    def _build_radar_datasets(self, panier_items_qs, categorie, date_debut, date_fin):
        """Radar : période filtre si ≤ 7 jours, sinon semaine en cours."""
        today = date.today()
        days = self._days_in_range(date_debut, date_fin)
        if days <= 7:
            radar_debut, radar_fin = date_debut, date_fin
            label_days = []
            d = radar_debut
            while d <= radar_fin:
                label_days.append(str(d.day))
                d += timedelta(days=1)
            n = len(label_days)
            ventes_template = [0] * n
        else:
            radar_debut = today - timedelta(days=today.weekday())
            radar_fin = radar_debut + timedelta(days=5)
            label_days = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]
            n = 6
            ventes_template = [0] * 6

        categories_to_show = [categorie] if categorie else Categorie.objects.all()
        datasets = []
        for cat in categories_to_show:
            ventes = list(ventes_template)
            if days <= 7:
                lignes = panier_items_qs.filter(
                    piece__categorie=cat,
                    date_creation__range=[radar_debut, radar_fin],
                ).values('date_creation').annotate(total=Sum('quantite'))
                day_index_map = {}
                d = radar_debut
                idx = 0
                while d <= radar_fin:
                    day_index_map[d] = idx
                    idx += 1
                    d += timedelta(days=1)
                for ligne in lignes:
                    i = day_index_map.get(ligne['date_creation'])
                    if i is not None:
                        ventes[i] = ligne['total']
            else:
                lignes = panier_items_qs.filter(
                    piece__categorie=cat,
                    date_creation__range=[radar_debut, radar_fin],
                ).values('date_creation').annotate(total=Sum('quantite'))
                for ligne in lignes:
                    day_index = ligne['date_creation'].weekday()
                    if day_index < 6:
                        ventes[day_index] = ligne['total']
            datasets.append({
                'label': cat.categorie.upper(),
                'data': ventes,
                'fill': True,
            })
        return label_days, datasets
    
    def get_base_queryset(self, date_debut, date_fin, categorie=None, caissier=None, moyen_paiement=None, user_role=None, localite=None, sous_categorie=None):
        """Get base queryset with all filters applied"""
        # Base queryset for PanierItem
        queryset = PanierItem.objects.filter(
            panier__valide=True,
            panier__panier_paye=True,
            date_creation__range=[date_debut, date_fin]
        )

        # Filter by category
        if categorie:
            queryset = queryset.filter(piece__categorie=categorie)
        if sous_categorie:
            queryset = queryset.filter(piece__sous_categorie=sous_categorie)

        # Filter by caissier (user who validated the payment)
        if caissier:
            queryset = queryset.filter(panier__commands__utilisateur=caissier)

        # Filter by payment method
        if moyen_paiement:
            queryset = queryset.filter(panier__commands__moyen_paiement=moyen_paiement)

        # Filter by user role
        if user_role == 'caissier':
            queryset = queryset.filter(panier__commands__utilisateur=self.request.user)
        elif user_role == 'accueil':
            # Accueil can see all data
            pass

        # Filter by localite (admin choisit, gestionnaire restreint à la sienne)
        if localite:
            queryset = queryset.filter(panier__local_entrepot=localite)
        return queryset
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = date.today()
        annee = today.year
        moisact = calendar.month_name[today.month]

        user_role = self.request.user.role if hasattr(self.request.user, 'role') else None
        can_choose_localite = dashboard_can_choose_localite(self.request.user)
        is_admin_like = can_choose_localite

        form = self.form_class(self.request.GET)
        date_debut, date_fin, periode_active = self.get_date_range(self.request)

        categorie = form.cleaned_data.get('categorie') if form.is_valid() else None
        sous_categorie = form.cleaned_data.get('sous_categorie') if form.is_valid() else None
        caissier = form.cleaned_data.get('caissier') if form.is_valid() else None
        moyen_paiement = form.cleaned_data.get('moyen_paiement') if form.is_valid() else None

        if can_choose_localite:
            localite = form.cleaned_data.get('localite') if form.is_valid() else None
        else:
            localite = getattr(self.request.user, 'local_entrepot', None)

        # Get base queryset with filters
        panier_items_queryset = self.get_base_queryset(
            date_debut, date_fin, categorie, caissier, moyen_paiement, user_role, localite,
            sous_categorie=sous_categorie,
        )

        # Base queryset for Commande
        commande_queryset = Commande.objects.filter(
            panier__valide=True,
            date_creation__range=[date_debut, date_fin]
        )
        if caissier:
            commande_queryset = commande_queryset.filter(utilisateur=caissier)
        if moyen_paiement:
            commande_queryset = commande_queryset.filter(moyen_paiement=moyen_paiement)
        if user_role == 'caissier':
            commande_queryset = commande_queryset.filter(utilisateur=self.request.user)
        if localite:
            commande_queryset = commande_queryset.filter(panier__local_entrepot=localite)

        count_catego = Categorie.objects.all().count()

        entre_queryset = EntrePiece.objects.filter(date_creation__range=[date_debut, date_fin])
        if localite:
            entre_queryset = entre_queryset.filter(local_entrepot=localite)
        piece_queryset = Piece.objects.all()  # Pour le stock total, on prend toutes les pièces
        if localite:
            piece_queryset = piece_queryset.filter(stocks__local_entrepot=localite).distinct()
        if categorie:
            piece_queryset = piece_queryset.filter(categorie=categorie)
        if sous_categorie:
            piece_queryset = piece_queryset.filter(sous_categorie=sous_categorie)
        
        piece_queryset = annotate_pieces_for_localite(piece_queryset, localite)
        count_piece = sum(getattr(p, 'quantite_disponible', 0) for p in piece_queryset)
        stock_val_qs = StockLocal.objects.all()
        if localite:
            stock_val_qs = stock_val_qs.filter(local_entrepot=localite)
        valeur_piece = stock_val_qs.aggregate(
            total=Sum(
                F('quantite_disponible') * Coalesce(
                    F('prix_unitaire_local'), F('piece__prix_unitaire')
                ),
                output_field=FloatField(),
            )
        )['total'] or 0
        
        total_entre_piece = entre_queryset.aggregate(
            total=Sum(F('quantitajout')))['total'] or 0
        
        valeur_entre_piece = entre_queryset.aggregate(
            total=Sum(F('quantitajout') * F('prix_achat'), output_field=FloatField())
        )['total'] or 0

        # État des commandes — le filtre dashboard (période / localité / caissier / paiement) s’applique
        # via commande_queryset + dates d’événement (paiement / livraison), pas seulement date_creation.
        cmd_etat_base = Commande.objects.filter(panier__valide=True)
        if caissier:
            cmd_etat_base = cmd_etat_base.filter(utilisateur=caissier)
        if moyen_paiement:
            cmd_etat_base = cmd_etat_base.filter(moyen_paiement=moyen_paiement)
        if user_role == 'caissier':
            cmd_etat_base = cmd_etat_base.filter(utilisateur=self.request.user)
        if localite:
            cmd_etat_base = cmd_etat_base.filter(panier__local_entrepot=localite)

        # Payée / À livrer : période = date de paiement (sinon date_creation)
        payees_periode = cmd_etat_base.filter(paye=True).filter(
            Q(panier__date_paie_panier__range=[date_debut, date_fin])
            | Q(panier__date_paie_panier__isnull=True, date_creation__range=[date_debut, date_fin])
        )

        # En attente : créées sur la période, non payées, non livrées
        cmd_attente = cmd_etat_base.filter(
            paye=False,
            panier__panier_livre=False,
            date_creation__range=[date_debut, date_fin],
        ).exclude(statut_commande='livrer').count()
        val_cmd_attente = cmd_etat_base.filter(
            paye=False,
            panier__panier_livre=False,
            date_creation__range=[date_debut, date_fin],
        ).exclude(statut_commande='livrer').aggregate(total=Sum('total'))['total'] or 0

        cmd_payee = payees_periode.count()
        val_cmd_payee = payees_periode.aggregate(total=Sum('total'))['total'] or 0

        # Livrée : période = date de livraison
        livrees_periode = cmd_etat_base.filter(paye=True).filter(
            Q(panier__panier_livre=True) | Q(statut_commande='livrer'),
        ).filter(
            Q(panier__date_livr_panier__range=[date_debut, date_fin])
            | Q(
                panier__date_livr_panier__isnull=True,
                date_creation__range=[date_debut, date_fin],
            )
        )
        cmd_livrer = livrees_periode.count()
        val_cmd_livrer = livrees_periode.aggregate(total=Sum('total'))['total'] or 0

        # À livrer : payées sur la période, pas encore livrées
        a_livrer_qs = payees_periode.filter(panier__panier_livre=False).exclude(
            statut_commande='livrer',
        )
        cmd_a_livrer = a_livrer_qs.count()
        val_cmd_a_livrer = a_livrer_qs.aggregate(total=Sum('total'))['total'] or 0
        
        ######--------------Total des pieces vendues--------------#######
        nb_piece_vendu = panier_items_queryset.aggregate(total=Sum('quantite'))['total'] or 0
        val_piece_vendu = panier_items_queryset.aggregate(
            total=Sum(F('quantite') * F('piece__prix_unitaire'), output_field=FloatField())
        )['total'] or 0
        
        cout_total = panier_items_queryset.aggregate(
            total_cout=Sum(F('quantite') * F('piece__prix_achat'), output_field=FloatField())
        )['total_cout'] or 0

        # Bénéfice = Revenu - Coût
        benefice_mensuel = val_piece_vendu - cout_total
        
        # Nombre de pièces par catégorie pour le graphique circulaire
        if categorie:
            # If filtering by category, show only that category
            piece_data = [{'categorie__categorie': categorie.categorie, 'total_quantite': count_piece}]
        else:
            # Get all categories with their quantities
            piece_data = panier_items_queryset.values('piece__categorie__categorie').annotate(
                total_quantite=Sum('quantite')
            )
        
        labels = [entry['piece__categorie__categorie'].upper() if 'piece__categorie__categorie' in entry else entry['categorie__categorie'].upper() for entry in piece_data]
        data = [entry['total_quantite'] for entry in piece_data]
        
        # Calculate percentages for legend
        total_data = sum(data) if data else 1
        pie_data_with_percent = [
            {
                'label': labels[i],
                'value': data[i],
                'percent': round((data[i] / total_data) * 100, 2) if total_data > 0 else 0
            }
            for i in range(len(labels))
        ]

        vente_month = commande_queryset.filter(paye=True).aggregate(total=Sum('total'))['total'] or 0
        vente_year = commande_queryset.filter(paye=True).aggregate(total=Sum('total'))['total'] or 0

        piece_alerte_queryset = filter_pieces_sous_seuil(Piece.objects.all(), localite)
        if categorie:
            piece_alerte_queryset = piece_alerte_queryset.filter(categorie=categorie)
        if sous_categorie:
            piece_alerte_queryset = piece_alerte_queryset.filter(sous_categorie=sous_categorie)
        piece_alerte = piece_alerte_queryset.count()
        liste_piece_alerte = list(piece_alerte_queryset[:8])

        chart_labels, nb_piece_data, valeur_mensuelle_data, chart_mode = self._build_evolution_series(
            panier_items_queryset, commande_queryset, date_debut, date_fin
        )
        jours_semaine, datasets = self._build_radar_datasets(
            panier_items_queryset, categorie, date_debut, date_fin
        )

        top_vent_piece = (
            panier_items_queryset
            .values('piece__designation', 'piece__categorie__categorie')
            .annotate(
                quantite_vendue=Sum('quantite'),
                cout_total=Sum(ExpressionWrapper(F('piece__prix_unitaire') * F('quantite'), output_field=DecimalField()))
            )
            .order_by('-quantite_vendue')[:5]
        )
        
        tickets_queryset = Ticket.objects.filter(utilise=True, date_creation__range=[date_debut, date_fin])
        if localite:
            tickets_queryset = tickets_queryset.filter(commande__panier__local_entrepot=localite)
        total_tickets_used = tickets_queryset.count()

        proforma_queryset = Commande.objects.filter(profoma=1, paye=False, date_creation__range=[date_debut, date_fin])
        if caissier:
            proforma_queryset = proforma_queryset.filter(utilisateur=caissier)
        if localite:
            proforma_queryset = proforma_queryset.filter(panier__local_entrepot=localite)
        proforma_genere = proforma_queryset.count()

        proforma_valide_queryset = Commande.objects.filter(profoma=1, paye=True, date_creation__range=[date_debut, date_fin])
        if caissier:
            proforma_valide_queryset = proforma_valide_queryset.filter(utilisateur=caissier)
        if localite:
            proforma_valide_queryset = proforma_valide_queryset.filter(panier__local_entrepot=localite)
        proforma_valide = proforma_valide_queryset.count()
        
        # Vente par catégorie (pour graphique)
        vente_par_categorie = panier_items_queryset.values('piece__categorie__categorie').annotate(
            total_vente=Sum(F('quantite') * F('piece__prix_unitaire'), output_field=FloatField())
        ).order_by('-total_vente')
        
        stock_cat_qs = StockLocal.objects.all()
        if localite:
            stock_cat_qs = stock_cat_qs.filter(local_entrepot=localite)
        if categorie:
            stock_cat_qs = stock_cat_qs.filter(piece__categorie=categorie)
        qte_piece_par_cat_stock = list(
            stock_cat_qs.values('piece__categorie__categorie').annotate(
                total_qte=Sum('quantite_disponible')
            ).order_by('-total_qte')
        )
        vente_par_categorie_list = list(vente_par_categorie)
        filtre_resume = build_filtre_resume(date_debut, date_fin, periode_active, localite)
        context = {
            'proforma_genere': proforma_genere,
            'proforma_valide': proforma_valide,

            'total_entre_piece': total_entre_piece,
            'valeur_entre_piece': valeur_entre_piece,
            'moisact':moisact,
            'annee':annee,

            'cmd_attente': cmd_attente,
            'cmd_payee': cmd_payee,
            'cmd_a_livrer': cmd_a_livrer,
            'cmd_livrer': cmd_livrer,

            'val_cmd_attente': val_cmd_attente,
            'val_cmd_payee': val_cmd_payee,
            'val_cmd_livrer': val_cmd_livrer,
            'val_cmd_a_livrer': val_cmd_a_livrer,

            'count_catego': count_catego,
            'count_piece': count_piece,
            'valeur_piece': valeur_piece,

            'labels': labels,
            'data': data,
            'pie_data_with_percent': json.dumps(pie_data_with_percent),
            'chart_labels': json.dumps(chart_labels),
            'chart_mode': chart_mode,

            'nb_piece_vendu': nb_piece_vendu,
            'val_piece_vendu': val_piece_vendu,

            'jours_semaine': json.dumps(jours_semaine),
            'datasets_json': json.dumps(datasets),

            'piece_alerte': piece_alerte,
            'liste_piece_alerte': liste_piece_alerte,

            'top_vent_piece': top_vent_piece,
            'valeur_mensuelle_data': json.dumps(valeur_mensuelle_data),
            'cmde_paye_day': cmd_payee,

            'benefice_mensuel': benefice_mensuel,
            'nb_piece_data': json.dumps(nb_piece_data),
            'total_tickets_used': total_tickets_used,

            'vente_month': vente_month,
            'vente_year': vente_year,
            'form': form,

            'vente_par_categorie': vente_par_categorie_list,
            'vente_par_categorie_json': json.dumps([
                {
                    'label': (v.get('piece__categorie__categorie') or 'N/A'),
                    'value': float(v.get('total_vente') or 0),
                }
                for v in vente_par_categorie_list
            ]),
            'qte_piece_par_cat_stock': qte_piece_par_cat_stock,
            'qte_stock_cat_json': json.dumps([
                {
                    'label': (q.get('piece__categorie__categorie') or 'N/A'),
                    'value': int(q.get('total_qte') or 0),
                }
                for q in qte_piece_par_cat_stock
            ]),

            'is_admin_like': is_admin_like,
            'can_choose_localite': can_choose_localite,
            'localite_active': localite,
            'localites': LocalEntrepot.objects.all() if can_choose_localite else None,
            'periode_active': periode_active,
            'date_debut': date_debut,
            'date_fin': date_fin,
            'filtre_resume': filtre_resume,
            'filter_modal_id': 'dashboardFilterModal',
            'filter_reset_url': reverse('tbord'),
        }
        return context


def details_commande(request, commande_id):
    commande = get_object_or_404(Commande, id=commande_id)
    return render(request, 'details_commande.html', {'commande': commande})

class AddCategorieView(LoginRequiredMixin, CustomPermissionRequiredMixin, CreateView):
    login_url = 'connexion'
    model = Categorie
    form_class = CategorieForm
    template_name = 'mag/categorie.html'
    success_message = 'Categorie enregistrée avec succès✓✓'
    error_message = "Erreur de saisie ✘✘"
    def form_valid(self, form):
        reponse = super().form_valid(form)
        messages.success(self.request, self.success_message)
        return reponse
    def form_invalid(self, form):
        categorie_nom = form.cleaned_data.get('categorie')
        if Categorie.objects.filter(categorie=categorie_nom).exists():
            messages.error(self.request, "Cette catégorie existe déjà ❌.")
        else:
            messages.error(self.request, self.error_message)
        return super().form_invalid(form)
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = self.get_form()
        # Annoter chaque catégorie avec le nombre de pièces et la somme des quantités disponibles
        categories = Categorie.objects.annotate(
            nb_pieces=Count('piece', distinct=True),
            total_quantite=Sum('piece__stocks__quantite_disponible')
        ).prefetch_related(
            Prefetch(
                'sous_categories',
                queryset=SousCategorie.objects.order_by('ordre', 'nom'),
            )
        ).all()
        # Créer un formulaire vide pour l'édition (sera rempli par le partial)
        edit_form = CategorieForm()
        count_medoc = Piece.objects.count()
        context.update({
            'categories': categories,
            'form': form,
            'edit_form': edit_form,
            'sous_form': SousCategorieForm(),
            'count_medoc': count_medoc,
        })
        return context
    def get_success_url(self):
        return reverse_lazy('add_categorie')
    
class UpdateCategorieView(LoginRequiredMixin, UpdateView):
    login_url = 'connexion'
    model = Categorie
    form_class = CategorieForm
    template_name = 'mag/categorie.html'
    success_message = 'Catégorie modifiée avec succès✓✓'
    error_message = "Erreur de saisie ✘✘"
    def form_valid(self, form):
        reponse = super().form_valid(form)
        messages.success(self.request, self.success_message)
        return reponse
    def form_invalid(self, form):
        # Afficher les erreurs de validation dans les messages
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(self.request, f"{field}: {error}")
        messages.error(self.request, self.error_message)
        # Rediriger vers add_categorie même en cas d'erreur
        return redirect('add_categorie')
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Annoter chaque catégorie avec le nombre de pièces et la somme des quantités disponibles
        categories = Categorie.objects.annotate(
            nb_pieces=Count('piece', distinct=True),
            total_quantite=Sum('piece__stocks__quantite_disponible')
        ).prefetch_related(
            Prefetch(
                'sous_categories',
                queryset=SousCategorie.objects.order_by('ordre', 'nom'),
            )
        ).all()
        edit_form = CategorieForm(instance=self.get_object())
        count_medoc = Piece.objects.count()
        context.update({
            'categories': categories,
            'form': CategorieForm(),
            'edit_form': edit_form,
            'sous_form': SousCategorieForm(),
            'count_medoc': count_medoc,
        })
        return context
    def get_success_url(self):
        return reverse('add_categorie')

def delete_categorie(request, pk):
    try:
        catego = get_object_or_404(Categorie, id=pk)
        catego.delete()
        messages.success(request, f"la categorie {catego.categorie} a été supprimés avec succès.")
    except Exception as e:
        messages.error(request, f"Erreur lors de la suppression : {str(e)}")
    return redirect('add_categorie')


@login_required(login_url='connexion')
def add_sous_categorie(request):
    if request.method != 'POST':
        return redirect('add_categorie')
    form = SousCategorieForm(request.POST, request.FILES)
    if form.is_valid():
        form.save()
        messages.success(request, 'Sous-catégorie enregistrée avec succès✓✓')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{field}: {error}")
        messages.error(request, "Erreur de saisie ✘✘")
    return redirect('add_categorie')


class UpdateSousCategorieView(LoginRequiredMixin, UpdateView):
    login_url = 'connexion'
    model = SousCategorie
    form_class = SousCategorieForm
    success_message = 'Sous-catégorie modifiée avec succès✓✓'

    def get(self, request, *args, **kwargs):
        return redirect('add_categorie')

    def form_valid(self, form):
        form.save()
        messages.success(self.request, self.success_message)
        return redirect('add_categorie')

    def form_invalid(self, form):
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(self.request, f"{field}: {error}")
        messages.error(self.request, "Erreur de saisie ✘✘")
        return redirect('add_categorie')


@login_required(login_url='connexion')
def delete_sous_categorie(request, pk):
    try:
        sous = get_object_or_404(SousCategorie, pk=pk)
        nom = str(sous)
        sous.delete()
        messages.success(request, f'La sous-catégorie {nom} a été supprimée.')
    except Exception as e:
        messages.error(request, f"Erreur lors de la suppression : {str(e)}")
    return redirect('add_categorie')


def _excel_cell_str(value):
    if value is None:
        return ''
    text = str(value).strip()
    if not text or text.lower() in ('nan', 'none', 'nat'):
        return ''
    return ' '.join(text.split())


def _excel_cell_bool(value, default=True):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ('', 'nan', 'none'):
        return default
    if text in ('1', 'true', 'vrai', 'oui', 'yes', 'o', 'x'):
        return True
    if text in ('0', 'false', 'faux', 'non', 'no', 'n'):
        return False
    return default


def _trouver_categorie_insensible_casse(nom):
    """Accepte « DZIRE » et « dzire » si la catégorie existe déjà."""
    nom = _excel_cell_str(nom)
    if not nom:
        return None
    exacte = Categorie.objects.filter(categorie=nom).first()
    if exacte:
        return exacte
    return Categorie.objects.filter(categorie__iexact=nom).first()


SOUS_CATEGORIE_IMPORT_COLONNES = ('categorie', 'nom')
SOUS_CATEGORIE_EXEMPLES_NOMS = (
    'Moteur',
    'Freinage',
    'Suspension & Direction',
    'Transmission',
    'Électricité & Électronique',
    'Éclairage',
    'Carrosserie',
    'Climatisation & Chauffage',
    'Échappement',
    'Pneus & Jantes',
    'Refroidissement',
    'Accessoires & Intérieur',
)


@login_required(login_url='connexion')
def download_modele_sous_categories_excel(request):
    premiere = Categorie.objects.order_by('categorie').first()
    exemple_cat = premiere.categorie if premiere else 'Dzire'
    lignes = [
        {
            'categorie': exemple_cat,
            'nom': nom,
            'description': '',
            'ordre': index,
            'actif': True,
        }
        for index, nom in enumerate(SOUS_CATEGORIE_EXEMPLES_NOMS, start=1)
    ]
    exemple = pd.DataFrame(lignes)
    instructions = pd.DataFrame([
        {
            'Colonne': 'categorie',
            'Description': 'Obligatoire — nom de la catégorie parente. Majuscules/minuscules indifférentes (DZIRE = dzire). La catégorie doit déjà exister.',
        },
        {'Colonne': 'nom', 'Description': 'Obligatoire — nom de la sous-catégorie'},
        {'Colonne': 'description', 'Description': 'Optionnel'},
        {'Colonne': 'ordre', 'Description': 'Optionnel — entier (affichage). Défaut 0'},
        {'Colonne': 'actif', 'Description': 'Optionnel — oui/non, true/false, 1/0. Défaut oui'},
    ], columns=['Colonne', 'Description'])

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="modele_import_sous_categories.xlsx"'
    try:
        with pd.ExcelWriter(response, engine='openpyxl') as writer:
            exemple.to_excel(writer, sheet_name='SousCategories', index=False)
            instructions.to_excel(writer, sheet_name='Instructions', index=False)
            for sheet_name in ('SousCategories', 'Instructions'):
                ws = writer.sheets[sheet_name]
                for column in ws.columns:
                    max_len = max((len(str(cell.value or '')) for cell in column), default=8)
                    ws.column_dimensions[column[0].column_letter].width = min(max_len + 2, 70)
    except Exception as exc:
        return HttpResponse(f"Erreur lors de la génération du modèle Excel : {exc}", status=500)
    return response


@login_required(login_url='connexion')
def import_sous_categories_excel(request):
    if request.method != 'POST':
        return redirect('add_categorie')
    if not (
        request.user.is_superuser
        or user_has_permission(request.user, 'add_sous_categorie')
        or user_has_permission(request.user, 'add_categorie')
    ):
        messages.error(request, "Vous n'avez pas la permission d'importer des sous-catégories.")
        return redirect('add_categorie')

    excel_file = request.FILES.get('excel_file')
    if not excel_file:
        messages.error(request, "Aucun fichier Excel n'a été sélectionné.")
        return redirect('add_categorie')

    try:
        df = pd.read_excel(excel_file)
    except Exception as exc:
        messages.error(request, f"Impossible de lire le fichier Excel : {exc}")
        return redirect('add_categorie')

    df.columns = [_excel_cell_str(col).lower() for col in df.columns]
    alias = {
        'catégorie': 'categorie',
        'categorie parente': 'categorie',
        'catégorie parente': 'categorie',
        'sous_categorie': 'nom',
        'sous-categorie': 'nom',
        'sous categorie': 'nom',
        'sous-catégorie': 'nom',
    }
    df.rename(columns={k: v for k, v in alias.items() if k in df.columns}, inplace=True)

    manquantes = [col for col in SOUS_CATEGORIE_IMPORT_COLONNES if col not in df.columns]
    if manquantes:
        messages.error(request, f"Colonnes manquantes : {', '.join(manquantes)}")
        return redirect('add_categorie')

    created_count = 0
    updated_count = 0
    refused = []

    for index, row in df.iterrows():
        ligne = int(index) + 2
        categorie_nom = _excel_cell_str(row.get('categorie'))
        sous_nom = _excel_cell_str(row.get('nom'))
        if not categorie_nom and not sous_nom:
            continue
        if not categorie_nom:
            refused.append(f"Ligne {ligne} : catégorie parente vide — enregistrement refusé")
            continue
        if not sous_nom:
            refused.append(f"Ligne {ligne} : nom de sous-catégorie vide — enregistrement refusé")
            continue

        parent = _trouver_categorie_insensible_casse(categorie_nom)
        if parent is None:
            refused.append(
                f"Ligne {ligne} : catégorie « {categorie_nom} » introuvable — enregistrement refusé"
            )
            continue

        description = _excel_cell_str(row.get('description')) if 'description' in df.columns else ''
        ordre = 0
        if 'ordre' in df.columns:
            try:
                raw_ordre = row.get('ordre', 0)
                if raw_ordre is not None and not (isinstance(raw_ordre, float) and pd.isna(raw_ordre)):
                    ordre = max(0, int(float(raw_ordre)))
            except (TypeError, ValueError):
                ordre = 0
        actif = _excel_cell_bool(row.get('actif'), default=True) if 'actif' in df.columns else True

        existante = SousCategorie.objects.filter(
            categorie=parent, nom__iexact=sous_nom,
        ).first()
        if existante:
            existante.description = description or existante.description
            existante.ordre = ordre
            existante.actif = actif
            existante.save()
            updated_count += 1
        else:
            SousCategorie.objects.create(
                categorie=parent,
                nom=sous_nom,
                description=description or None,
                ordre=ordre,
                actif=actif,
            )
            created_count += 1

    if created_count or updated_count:
        messages.success(
            request,
            f"{created_count} sous-catégorie(s) créée(s), {updated_count} mise(s) à jour.",
        )
    if refused:
        apercu = ' | '.join(refused[:8])
        extra = f" (+{len(refused) - 8} autre(s))" if len(refused) > 8 else ''
        messages.error(request, f"{len(refused)} ligne(s) refusée(s). {apercu}{extra}")
    if not created_count and not updated_count and not refused:
        messages.warning(request, "Le fichier ne contient aucune ligne à importer.")
    return redirect('add_categorie')


@login_required(login_url='connexion')
def ajax_sous_categories(request):
    categorie_id = request.GET.get('categorie', '').strip()
    qs = SousCategorie.objects.filter(actif=True).order_by('ordre', 'nom')
    if categorie_id:
        qs = qs.filter(categorie_id=categorie_id)
    return JsonResponse({
        'results': [{'id': s.pk, 'nom': s.nom} for s in qs],
    })


PIECE_IMPORT_EXCEL_COLUMNS = [
    'numero_piece', 'designation', 'prix_achat', 'prix_unitaire', 'seuil', 'emplacement',
]
PIECE_IMPORT_EXCEL_OPTIONAL_COLUMNS = ['fournisseur', 'sous_categorie']


@login_required(login_url='connexion')
def download_modele_pieces_excel(request, pk):
    """Télécharge un fichier Excel modèle pour l'import de pièces dans une catégorie."""
    categorie = get_object_or_404(Categorie, pk=pk)
    exemple = pd.DataFrame([
        {
            'numero_piece': 'DZI-001',
            'designation': 'Courroie de distribution',
            'prix_achat': 15000,
            'prix_unitaire': 22000,
            'seuil': 5,
            'emplacement': 'Rayon A1',
            'sous_categorie': '',
            'fournisseur': '',
        },
        {
            'numero_piece': 'DZI-002',
            'designation': 'Filtre à huile',
            'prix_achat': 3500,
            'prix_unitaire': 6000,
            'seuil': 10,
            'emplacement': 'Rayon B2',
            'sous_categorie': '',
            'fournisseur': '',
        },
    ])
    instructions = pd.DataFrame([
        {'Colonne': 'numero_piece', 'Description': 'Obligatoire — référence unique de la pièce'},
        {'Colonne': 'designation', 'Description': 'Obligatoire — libellé de la pièce'},
        {'Colonne': 'prix_achat', 'Description': 'Obligatoire — prix d\'achat (nombre)'},
        {'Colonne': 'prix_unitaire', 'Description': 'Obligatoire — prix de vente (nombre)'},
        {'Colonne': 'seuil', 'Description': 'Obligatoire — seuil d\'alerte stock (entier)'},
        {'Colonne': 'emplacement', 'Description': 'Obligatoire — emplacement en magasin'},
        {'Colonne': 'sous_categorie', 'Description': 'Optionnel — nom d\'une sous-catégorie de cette catégorie'},
        {'Colonne': 'fournisseur', 'Description': 'Optionnel — nom du fournisseur (doit exister dans le système)'},
    ], columns=['Colonne', 'Description'])
    meta = pd.DataFrame([
        {'Information': 'Catégorie cible', 'Valeur': categorie.categorie},
        {'Information': 'Note', 'Valeur': 'Supprimez les lignes d\'exemple avant import. Le stock s\'ajoute via « Entrée en stock ».'},
    ])

    safe_cat = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in categorie.categorie)[:40]
    filename = f"modele_import_pieces_{safe_cat}.xlsx"
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    try:
        with pd.ExcelWriter(response, engine='openpyxl') as writer:
            exemple.to_excel(writer, sheet_name='Pieces', index=False)
            instructions.to_excel(writer, sheet_name='Instructions', index=False)
            meta.to_excel(writer, sheet_name='Infos', index=False)
            for sheet_name in ('Pieces', 'Instructions', 'Infos'):
                ws = writer.sheets[sheet_name]
                for column in ws.columns:
                    max_len = max((len(str(cell.value or '')) for cell in column), default=8)
                    ws.column_dimensions[column[0].column_letter].width = min(max_len + 2, 45)
    except Exception as exc:
        return HttpResponse(f"Erreur lors de la génération du modèle Excel : {exc}", status=500)
    return response


# @method_decorator(login_required, name='dispatch')
class AddPieceView(View):
    template_name = 'mag/add_piece.html'
    success_message = 'Pièce enregistrée avec succès✓✓'
    error_message = "Erreur de saisie✘✘"
    def get(self, request, pk=None):
        categories = Categorie.objects.annotate(nb_produits=Count('piece')).order_by('id')
        sous_categorie_id = request.GET.get('sous_categorie', '').strip()
        sous_categorie = None
        if pk:
            categorie = get_object_or_404(Categorie, pk=pk)
            pieces_qs = Piece.objects.filter(categorie=categorie).select_related(
                'categorie', 'sous_categorie', 'utilisateur'
            ).order_by('id')
            total_pieces_categorie = pieces_qs.count()
            if sous_categorie_id:
                sous_categorie = SousCategorie.objects.filter(
                    pk=sous_categorie_id, categorie=categorie,
                ).first()
                if sous_categorie:
                    pieces_qs = pieces_qs.filter(sous_categorie=sous_categorie)
            pieces = annotate_pieces_for_localite(
                pieces_qs,
                get_user_localite(request.user),
            )
            form = PieceForm(
                categorie=categorie,
                initial={'sous_categorie': sous_categorie.pk} if sous_categorie else None,
            )
        else:
            categorie = None
            pieces = Piece.objects.none()
            form = PieceForm()
            total_pieces_categorie = 0

        entre_stock_form = EntrePieceForm()
        edit_piece_form = UpdatePieceForm()
        fournisseurs = Fournisseur.objects.all()
        sous_categories = (
            SousCategorie.objects.filter(categorie=categorie, actif=True)
            .annotate(nb_pieces=Count('pieces'))
            .order_by('ordre', 'nom')
            if categorie else SousCategorie.objects.none()
        )

        return render(request, self.template_name, {
            'form': form,
            'pieces': pieces,
            'categorie': categorie,
            'categories': categories,
            'sous_categories': sous_categories,
            'sous_categorie_active': sous_categorie,
            'total_pieces_categorie': total_pieces_categorie,
            'entre_stock_form': entre_stock_form,
            'edit_piece_form': edit_piece_form,
            'fournisseurs': fournisseurs,
            'peut_toggle_sortie_catalogue': utilisateur_peut_toggle_sortie_catalogue(request.user),
            'peut_toggle_sortie_local': utilisateur_peut_toggle_sortie_local(request.user),
            **(
                export_urls(
                    request, 'export_pieces_categorie_excel', 'export_pieces_categorie_pdf',
                    url_kwargs={'pk': pk},
                ) if pk else {}
            ),
        })

    def post(self, request, pk):
        categorie = get_object_or_404(Categorie, pk=pk)
        categories = Categorie.objects.all().order_by('-id')
        entre_stock_form = EntrePieceForm()
        edit_piece_form = UpdatePieceForm()
        fournisseurs = Fournisseur.objects.all()
        if request.FILES.get('excel_file'):
            excel_file = request.FILES['excel_file']
            try:
                df = pd.read_excel(excel_file)
                required_columns = list(PIECE_IMPORT_EXCEL_COLUMNS)
                missing_columns = [col for col in required_columns if col not in df.columns]
                if missing_columns:
                    messages.error(request, f"Colonnes manquantes : {', '.join(missing_columns)}")
                    return redirect('add_piece', pk=pk)

                created_count = 0
                updated_count = 0
                for _, row in df.iterrows():
                    numero_piece = str(row['numero_piece']).strip()
                    if not numero_piece:
                        continue  # ignorer lignes vides

                    piece_data = {
                        'designation': str(row.get('designation', '')).strip(),
                        'prix_achat': row.get('prix_achat', 0),
                        'prix_unitaire': row.get('prix_unitaire', 0),
                        # 'quantite_disponible': int(row.get('quantite_disponible', 0)),
                        'seuil': int(row.get('seuil', 0)),
                        'emplacement': str(row.get('emplacement', '')).strip(),
                        'categorie': categorie,
                        'utilisateur': request.user,
                    }
                    if 'sous_categorie' in df.columns:
                        sous_nom = str(row.get('sous_categorie', '')).strip()
                        if sous_nom and sous_nom.lower() != 'nan':
                            sous = SousCategorie.objects.filter(
                                categorie=categorie, nom__iexact=sous_nom,
                            ).first()
                            if sous:
                                piece_data['sous_categorie'] = sous
                    # Gestion fournisseur (optionnel, si colonne "fournisseur" existe)
                    if 'fournisseur' in df.columns:
                        fournisseur_nom = str(row['fournisseur']).strip()
                        if fournisseur_nom:
                            fournisseur = Fournisseur.objects.filter(nom__iexact=fournisseur_nom).first()
                            if fournisseur:
                                piece_data['fournisseur'] = fournisseur
                    piece, created = Piece.objects.update_or_create(
                        numero_piece=numero_piece,
                        defaults=piece_data
                    )
                    loc = get_user_localite(request.user)
                    if loc:
                        get_or_create_stock(piece, loc)
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
                messages.success(request, f"✅ {created_count} pièce(s) créée(s), {updated_count} mise(s) à jour.")
                return redirect('add_piece', pk=pk)

            except Exception as e:
                messages.error(request, f"Erreur d'importation : {str(e)}")
                return redirect('add_piece', pk=pk)

        # Traitement du formulaire manuel
        form = PieceForm(request.POST, request.FILES, categorie=categorie)
        if form.is_valid():
            piece = form.save(commit=False)
            piece.utilisateur = request.user
            piece.categorie = categorie
            piece.save()
            localite = get_user_localite(request.user)
            if localite:
                get_or_create_stock(piece, localite)
            messages.success(request, self.success_message)
            return redirect('add_piece', pk=pk)
        else:
            messages.error(request, self.error_message)
            pieces = annotate_pieces_for_localite(
                Piece.objects.filter(
                    categorie=categorie,
                ).select_related('categorie', 'sous_categorie', 'utilisateur').order_by('-id'),
                get_user_localite(request.user),
            )
            return render(request, self.template_name,{
                'form': form,
                'pieces': pieces,
                'categorie': categorie,
                'categories': categories,
                'sous_categories': SousCategorie.objects.filter(
                    categorie=categorie, actif=True,
                ).order_by('ordre', 'nom'),
                'entre_stock_form': entre_stock_form,
                'edit_piece_form': edit_piece_form,
                'fournisseurs': fournisseurs,
                'peut_toggle_sortie_catalogue': utilisateur_peut_toggle_sortie_catalogue(request.user),
                'peut_toggle_sortie_local': utilisateur_peut_toggle_sortie_local(request.user),
            })

class AddPanierView(LoginRequiredMixin, View):
    login_url = 'connexion'
    def get(self, request):
        localite = get_user_localite(request.user)
        localite_panier = get_user_localite_panier(request.user)
        panier = get_panier_accueil_actif(request.user)
        if panier and not utilisateur_peut_modifier_panier_accueil(request.user, panier):
            panier = None
        items = list(
            PanierItem.objects.filter(panier=panier).select_related('piece', 'panier')
        ) if panier else []
        loc_prix = panier.local_entrepot if panier else localite_panier
        total = total_panier_items(items, loc_prix, panier=panier)
        total_quantite = (
            PanierItem.objects.filter(panier=panier).aggregate(total=Sum('quantite'))['total'] or 0
            if panier else 0
        )
        # Catalogue filtré / annoté sur le LocalEntrepot du compte
        articles = filter_pieces_avec_stock(
            pieces_queryset_for_user(request.user),
            localite,
        ).order_by("date_creation")[:8]
        categories = queryset_categories_avec_sous()
        return render(request, 'mag/add_panier.html', {
            'panier': panier,
            'items': items,
            'articles': articles,
            'total': total,
            'total_apres_remise': total,
            'categories': categories,
            'total_quantite': total_quantite,
            'localite_panier': localite_panier,
        })
        
@login_required(login_url='connexion')
def ajax_panier_items(request):
    panier = get_panier_accueil_actif(request.user)
    items = list(PanierItem.objects.filter(panier=panier).select_related('piece', 'panier')) if panier else []
    loc = panier.local_entrepot if panier else get_user_localite_panier(request.user)
    total = total_panier_items(items, loc, panier=panier)
    total_quantite = sum(it.quantite for it in items)
    html = render_to_string('mag/partials/_panier_items.html', {'items': items, 'total': total, 'total_quantite': total_quantite})
    return JsonResponse({'html': html, 'total': float(total), 'total_quantite': total_quantite})

@login_required(login_url='connexion')
def ajax_panier_accueil_state(request):
    """Synchronise l'affichage du panier accueil (évite un panier obsolète d'une autre session)."""
    panier = get_panier_accueil_actif(request.user)
    if panier and not utilisateur_peut_modifier_panier_accueil(request.user, panier):
        panier = None
    items = list(
        PanierItem.objects.filter(panier=panier).select_related('piece', 'panier')
    ) if panier else []
    loc = panier.local_entrepot if panier else get_user_localite_panier(request.user)
    total = total_panier_items(items, loc, panier=panier)
    total_quantite = sum(it.quantite for it in items)
    panier_html = render_to_string(
        'mag/partials/_panier_items_full.html',
        {'items': items, 'total': total, 'total_quantite': total_quantite},
        request=request,
    )
    return JsonResponse({
        'success': True,
        'panier_html': panier_html,
        'total': float(total),
        'total_quantite': total_quantite,
        'panier_empty': panier is None,
        'localite': str(loc) if loc else None,
    })

_VALID_PANIER_ACTIONS = {'add', 'increment', 'decrement', 'delete'}
def _is_ajax_request(request):
    return request.headers.get('x-requested-with', '').lower() == 'xmlhttprequest' \
        or request.headers.get('accept', '').find('application/json') != -1

def _render_panier_response(request, *, success, message, panier, piece, item, action, http_status=200):
    """Construit la réponse unifiée (JSON en AJAX, redirect sinon)."""
    if panier is not None:
        items = list(panier.panier_items.select_related('piece', 'panier').all())
        total = total_panier_items(items, panier.local_entrepot, panier=panier)
        total_quantite = sum(it.quantite for it in items)
    else:
        items = []
        total = 0
        total_quantite = 0

    if not _is_ajax_request(request):
        # Fallback sans JS : on conserve l'ancien comportement de redirection.
        if message:
            if success:
                messages.success(request, message)
            else:
                messages.warning(request, message)
        return redirect('paniers')

    quantite = item.quantite if item else 0
    prix_total_piece = (
        float(_pu_item_panier(item, panier=panier) * item.quantite)
        if (piece and item) else 0.0
    )

    panier_html = render_to_string(
        'mag/partials/_panier_items_full.html',
        {'items': items, 'total': total, 'total_quantite': total_quantite},
        request=request,
    )

    return JsonResponse({
        'success': success,
        'message': message,
        'action': action,
        'piece_id': piece.pk if piece else None,
        'quantite': quantite,
        'prix_total_piece': prix_total_piece,
        'total': float(total),
        'total_quantite': total_quantite,
        'panier_empty': panier is None,
        'deleted': item is None and action in {'decrement', 'delete'},
        'panier_html': panier_html,
    }, status=http_status)

@login_required(login_url='connexion')
def panier_action(request, pk, action=None):
    """Vue unifiée pour ajouter / incrémenter / décrémenter / supprimer une pièce du panier.

    L'action peut venir :
      - de l'URL (kwarg `action` passé par urls.py)
      - du body POST (`action` dans request.POST)
    Valeurs valides : 'add', 'increment', 'decrement', 'delete'.
    ('add' et 'increment' sont équivalents : +1 sur la quantité.)

    Retourne du JSON si la requête est AJAX, sinon redirige vers la page panier
    (rétro-compatibilité avec l'ancienne vue `Ajouter_panier`).
    """
    action = (action or request.POST.get('action') or request.GET.get('action') or 'add').lower()
    if action not in _VALID_PANIER_ACTIONS:
        return _render_panier_response(
            request, success=False, message="Action invalide.",
            panier=None, piece=None, item=None, action=action, http_status=400,
        )

    # Verrou pessimiste sur la pièce pour éviter les courses concurrentes.
    with transaction.atomic():
        piece = Piece.objects.select_for_update().filter(pk=pk).first()
        if piece is None:
            return _render_panier_response(
                request, success=False, message="Pièce introuvable.",
                panier=None, piece=None, item=None, action=action, http_status=404,
            )
        localite_panier = get_user_localite_panier(request.user)
        if action in ('add', 'increment'):
            if localite_panier and not piece_visible_en_localite(piece, localite_panier):
                return _render_panier_response(
                    request,
                    success=False,
                    message=f"La pièce « {piece.designation} » n'est pas disponible à la vente dans votre localité.",
                    panier=None,
                    piece=piece,
                    item=None,
                    action=action,
                    http_status=400,
                )

        panier = get_panier_accueil_actif(request.user, for_update=True)
        if panier and not utilisateur_peut_modifier_panier_accueil(request.user, panier):
            panier = None

        message = None
        item = None

        if action in ('add', 'increment'):
            if panier is None:
                panier, _created = get_or_create_panier_accueil(request.user)
                if panier is None:
                    return _render_panier_response(
                        request,
                        success=False,
                        message="Impossible de créer le panier (localité manquante).",
                        panier=None,
                        piece=piece,
                        item=None,
                        action=action,
                        http_status=403,
                    )
            item, created = PanierItem.objects.select_for_update().get_or_create(
                panier=panier, piece=piece,
                defaults={'quantite': 0},
            )
            new_qty = item.quantite + 1
            loc_stock = panier.local_entrepot or localite_panier
            stock_dispo = get_quantite(piece, loc_stock) if loc_stock else piece.quantite_totale
            if loc_stock and new_qty > stock_dispo:
                # Stock insuffisant : on rollback l'éventuelle création d'item.
                if created:
                    item.delete()
                    item = None
                    if not panier.panier_items.exists():
                        panier.delete()
                        panier = None
                return _render_panier_response(
                    request, success=False,
                    message=f"Stock insuffisant pour {piece.designation}. Disponible : {stock_dispo}.",
                    panier=panier, piece=piece, item=item, action=action, http_status=400,
                )
            item.quantite = new_qty
            item.save(update_fields=['quantite'])
            message = f"{piece.designation} ajouté au panier."

        elif action == 'decrement':
            if panier is None:
                return _render_panier_response(
                    request, success=False, message="Aucun panier actif.",
                    panier=None, piece=piece, item=None, action=action, http_status=404,
                )
            item = PanierItem.objects.select_for_update().filter(panier=panier, piece=piece).first()
            if item is None:
                return _render_panier_response(
                    request, success=False, message="Article non trouvé dans le panier.",
                    panier=panier, piece=piece, item=None, action=action, http_status=404,
                )
            if item.quantite > 1:
                item.quantite -= 1
                item.save(update_fields=['quantite'])
            else:
                item.delete()
                item = None

        elif action == 'delete':
            if panier is None:
                return _render_panier_response(
                    request, success=False, message="Aucun panier actif.",
                    panier=None, piece=piece, item=None, action=action, http_status=404,
                )
            deleted, _ = PanierItem.objects.filter(panier=panier, piece=piece).delete()
            if not deleted:
                return _render_panier_response(
                    request, success=False, message="Article non trouvé dans le panier.",
                    panier=panier, piece=piece, item=None, action=action, http_status=404,
                )
            item = None
            message = "Article supprimé du panier."

        # Nettoyer le panier s'il est vide.
        if panier is not None and not panier.panier_items.exists():
            panier.delete()
            panier = None
            item = None

    return _render_panier_response(
        request, success=True, message=message,
        panier=panier, piece=piece, item=item, action=action,
    )


# Alias de compatibilité : les anciens noms pointent sur la vue unifiée.
# Les URLs dans stock/urls.py passent l'action via kwargs, donc ces alias
# sont conservés uniquement pour les imports externes éventuels.
Ajouter_panier = panier_action
ajouter_panier_ajax = panier_action
retirer_panier_ajax = panier_action
supprimer_panier_ajax = panier_action

def ajax_search_articles(request):
    query = request.GET.get('q', '')
    categorie_id = request.GET.get('categorie', '')
    sous_categorie_id = request.GET.get('sous_categorie', '')
    localite = get_user_localite(request.user)
    articles = filter_pieces_avec_stock(
        pieces_queryset_for_user(request.user), localite
    )
    if query:
        articles = articles.filter(
            Q(designation__icontains=query) |
            Q(numero_piece__icontains=query) |
            Q(categorie__categorie__icontains=query) |
            Q(sous_categorie__nom__icontains=query) |
            Q(prix_unitaire__icontains=query)
        )
    if categorie_id:
        articles = articles.filter(categorie__id=categorie_id)
    if sous_categorie_id:
        articles = articles.filter(sous_categorie__id=sous_categorie_id)

    articles = articles.order_by("-date_creation")[:12]
    html = render_to_string('mag/partials/_article_list.html', {'articles': articles})
    return JsonResponse({'html': html})

def ajax_search_articles_proforma(request):
    """Recherche d'articles pour la proforma"""
    query = request.GET.get('q', '')
    categorie_id = request.GET.get('categorie', '')
    sous_categorie_id = request.GET.get('sous_categorie', '')
    localite = get_user_localite(request.user)
    articles = filter_pieces_avec_stock(
        pieces_queryset_for_user(request.user), localite
    )
    if query:
        articles = articles.filter(
            Q(designation__icontains=query) |
            Q(numero_piece__icontains=query) |
            Q(categorie__categorie__icontains=query) |
            Q(sous_categorie__nom__icontains=query) |
            Q(prix_unitaire__icontains=query)
        )
    if categorie_id:
        articles = articles.filter(categorie__id=categorie_id)
    if sous_categorie_id:
        articles = articles.filter(sous_categorie__id=sous_categorie_id)

    articles = articles.order_by("-date_creation")[:12]
    html = render_to_string('mag/partials/_article_proforma_list.html', {'articles': articles})
    return JsonResponse({'html': html})

@login_required(login_url='connexion')
def valider_paniers(request):
    localite_panier = get_user_localite_panier(request.user)
    if not localite_panier:
        messages.error(request, "Aucune localité affectée : impossible de valider un panier.")
        return redirect('paniers')
    panier = get_panier_accueil_actif(request.user)
    if not panier or not utilisateur_peut_modifier_panier_accueil(request.user, panier):
        messages.warning(request, "Aucun panier actif à valider pour votre localité.")
        return redirect('paniers')
    panier = Panier.objects.select_related('local_entrepot').get(pk=panier.pk)
    # Calcul du total du panier
    panier_items = list(PanierItem.objects.filter(panier=panier).select_related('piece', 'panier'))
    total = total_panier_items(panier_items, panier.local_entrepot, panier=panier)
    montant_remise = parse_remise_montant(request.POST.get('remiser'), total)
    total_apres_remise = total - montant_remise
    commande = Commande.objects.create(
        panier=panier,
        numero_commande='N°' + str(panier.id) + '-' + str(Commande.objects.filter(panier=panier).count() + 1),
        total=total_apres_remise,
        remise=montant_remise,
        paye=False,
        total_sans_remise=total,
        utilisateur=request.user,
    )
    # Création du ticket
    ticket = Ticket.objects.create(
        numero='TKT' + str(commande.id),
        commande=commande,
        utilise=False,
        utilisateur=request.user
    )
    # Mise à jour du panier
    panier.valide = True
    numero=f"TKT{str(commande.id)}"
    numero=str(numero)
    panier.ticket = numero
    panier.save()
    _loc = getattr(panier, 'local_entrepot', None)
    publish_panier_valide(
        panier.id,
        total_apres_remise,
        local_entrepot_id=_loc.pk if _loc else None,
        local_entrepot_nom=str(_loc) if _loc else None,
    )
    messages.success(request, f"Le panier de Ticket N°{ticket.numero} a été validé ")

    # Impression automatique du bon de commande (à remettre au client pour la caisse)
    panier_items_list = list(panier_items)
    try:
        print_order_receipt_thermal(commande, panier_items_list)
        messages.success(request, "✅ Bon de commande imprimé sur l'imprimante Epson TM-T20III.")
    except Exception as e:
        messages.warning(
            request,
            f"⚠️ Impression du bon de commande impossible : {e}. "
            f"Vous pouvez le réimprimer depuis la page caisse."
        )

    # Sauvegarde PDF du bon de commande
    try:
        pdf_relative_path = generate_order_receipt_pdf_file(commande, panier_items_list)
        ticket.fichier_pdf = pdf_relative_path
        ticket.save()
    except Exception as e:
        print(f"⚠️ Erreur lors de la génération du PDF du bon de commande : {e}")

    return redirect('paniers')

# ============================================================================#
#                          VUES POUR LA PROFORMA                              #
# ============================================================================#
class AddProformaView(LoginRequiredMixin, View):
    login_url = 'connexion'
    def get(self, request):
        localite = get_user_localite(request.user)
        panier_qs = Panier.objects.filter(
            utilisateur=request.user,
            valide=False,
            proforma=True,
            ticket__isnull=True,
        )
        if localite:
            panier_qs = panier_qs.filter(local_entrepot=localite)
        panier = panier_qs.select_related('local_entrepot').first()
        items = list(
            PanierItem.objects.filter(panier=panier).select_related('piece', 'panier')
        ) if panier else []
        total = total_panier_items(items, localite, panier=panier) if panier else 0
        total_quantite = PanierItem.objects.filter(panier=panier).aggregate(total=Sum('quantite'))['total'] or 0 if panier else 0
        total_apres_remise = total  # Par défaut, pas de remise
        articles = filter_pieces_avec_stock(
            annotate_pieces_for_localite(
                Piece.objects.select_related('categorie', 'sous_categorie'), localite
            ),
            localite,
        ).order_by("date_creation")[:8]
        categories = queryset_categories_avec_sous()
        return render(request, 'mag/add_proforma.html', {
            'panier': panier,
            'items': items,
            'articles': articles,
            'total': total,
            'total_apres_remise': total_apres_remise,
            'categories': categories,
            'total_quantite': total_quantite,
        })

@login_required(login_url='connexion')
def panier_proforma_action(request, pk, action=None):
    """Vue unifiée pour ajouter / incrémenter / décrémenter / supprimer du panier proforma.

    Action (priorité : kwarg URL > POST body > GET param) :
      - 'add'       : ajouter depuis la liste articles (crée l'item si absent, sinon +1)
      - 'increment' : bouton + dans le panier (alias de add)
      - 'decrement' : bouton - dans le panier
      - 'delete'    : supprimer complètement l'item
    Retourne du JSON si AJAX (X-Requested-With: XMLHttpRequest),
    sinon redirige vers la page proforma (rétro-compatibilité).
    """
    action = (action or request.POST.get('action') or request.GET.get('action') or 'add').lower()
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    piece = get_object_or_404(Piece, id=pk)
    localite = get_user_localite(request.user)

    def _get_or_create_panier():
        qs = Panier.objects.filter(utilisateur=request.user, valide=False, proforma=True, ticket__isnull=True)
        if localite:
            qs = qs.filter(local_entrepot=localite)
        panier = qs.first()
        if not panier:
            panier = Panier.objects.create(utilisateur=request.user, valide=False, proforma=True, local_entrepot=localite)
        return panier

    def _get_panier():
        qs = Panier.objects.filter(utilisateur=request.user, valide=False, proforma=True, ticket__isnull=True)
        if localite:
            qs = qs.filter(local_entrepot=localite)
        return qs.first()

    def _totaux(panier):
        items = list(panier.panier_items.select_related('piece', 'panier').all())
        total = total_panier_items(items, panier.local_entrepot, panier=panier)
        total_quantite = sum(i.quantite for i in items)
        return float(total), total_quantite

    # ── ADD / INCREMENT ────────────────────────────────────────────────────────
    if action in ('add', 'increment'):
        loc_pf = localite
        if not piece_visible_en_localite(piece, loc_pf):
            msg = f"La pièce « {piece.designation} » n'est pas disponible à la vente dans votre localité."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.warning(request, msg)
            return redirect('add_proforma')
        panier = _get_or_create_panier()
        panier_item, created = PanierItem.objects.get_or_create(
            panier=panier, piece=piece, defaults={'quantite': 1}
        )
        if not created:
            loc_pf = panier.local_entrepot or localite
            stock_dispo = get_quantite(piece, loc_pf) if loc_pf else piece.quantite_totale
            if panier_item.quantite < stock_dispo:
                panier_item.quantite += 1
                panier_item.save()
            else:
                total, total_quantite = _totaux(panier)
                prix_total_piece = float(_pu_item_panier(panier_item, panier=panier) * panier_item.quantite)
                if is_ajax:
                    return JsonResponse({
                        'success': False,
                        'message': f"Stock insuffisant pour {piece.designation}. Disponible : {stock_dispo}.",
                        'quantite': panier_item.quantite,
                        'total': total,
                        'total_quantite': total_quantite,
                        'prix_total_piece': prix_total_piece,
                    })
                messages.warning(request, f"Stock insuffisant pour {piece.designation} ({stock_dispo} dispo).")
                return redirect('add_proforma')

        total, total_quantite = _totaux(panier)
        prix_total_piece = float(_pu_item_panier(panier_item, panier=panier) * panier_item.quantite)

        if is_ajax:
            card_html = ''
            if created:
                card_html = render_to_string(
                    'mag/partials/_panier_proforma_item.html',
                    {'item': panier_item},
                    request=request,
                )
            return JsonResponse({
                'success': True,
                'created': created,
                'piece_id': pk,
                'quantite': panier_item.quantite,
                'total': total,
                'total_quantite': total_quantite,
                'prix_total_piece': prix_total_piece,
                'card_html': card_html,
            })
        messages.success(request, f"{piece.designation} ajouté au panier proforma.")
        return redirect('add_proforma')

    # ── DECREMENT ──────────────────────────────────────────────────────────────
    elif action == 'decrement':
        panier = _get_panier()
        if not panier:
            if is_ajax:
                return JsonResponse({'success': False, 'message': 'Aucun panier proforma actif.'})
            return redirect('add_proforma')

        panier_item = PanierItem.objects.filter(panier=panier, piece=piece).first()
        if not panier_item:
            if is_ajax:
                return JsonResponse({'success': False, 'message': 'Article non trouvé dans le panier.'})
            return redirect('add_proforma')

        if panier_item.quantite > 1:
            panier_item.quantite -= 1
            panier_item.save()
            quantite = panier_item.quantite
            prix_total_piece = float(_pu_item_panier(panier_item, panier=panier) * panier_item.quantite)
        else:
            panier_item.delete()
            quantite = 0
            prix_total_piece = 0.0

        if not panier.panier_items.exists():
            panier.delete()
            panier_empty, total, total_quantite = True, 0.0, 0
        else:
            panier_empty = False
            total, total_quantite = _totaux(panier)

        if is_ajax:
            return JsonResponse({
                'success': True,
                'quantite': quantite,
                'total': total,
                'total_quantite': total_quantite,
                'panier_empty': panier_empty,
                'prix_total_piece': prix_total_piece,
            })
        return redirect('add_proforma')

    # ── DELETE ─────────────────────────────────────────────────────────────────
    elif action == 'delete':
        panier = _get_panier()
        if not panier:
            if is_ajax:
                return JsonResponse({'success': False, 'message': "Aucun panier proforma actif."})
            return redirect('add_proforma')

        panier_item = PanierItem.objects.filter(panier=panier, piece=piece).first()
        if not panier_item:
            if is_ajax:
                return JsonResponse({'success': False, 'message': "Article non trouvé dans le panier."})
            return redirect('add_proforma')

        panier_item.delete()
        if not panier.panier_items.exists():
            panier.delete()
            panier_vide, total, total_quantite = True, 0.0, 0
        else:
            panier_vide = False
            total, total_quantite = _totaux(panier)

        if is_ajax:
            return JsonResponse({
                'success': True,
                'deleted': True,
                'piece_id': pk,
                'total': total,
                'total_quantite': total_quantite,
                'panier_empty': panier_vide,
            })
        return redirect('add_proforma')

    # ── ACTION INCONNUE ────────────────────────────────────────────────────────
    if is_ajax:
        return JsonResponse({'success': False, 'message': 'Action invalide.'}, status=400)
    return redirect('add_proforma')

# Alias pour garder la rétro-compatibilité des anciens appels directs
Ajouter_panier_proforma        = lambda req, pk: panier_proforma_action(req, pk, action='add')
ajouter_panier_proforma_ajax   = lambda req, pk: panier_proforma_action(req, pk, action='increment')
retirer_panier_proforma_ajax   = lambda req, pk: panier_proforma_action(req, pk, action='decrement')
supprimer_panier_proforma_ajax = lambda req, pk: panier_proforma_action(req, pk, action='delete')

@login_required(login_url='connexion')
def valider_proforma(request, ticket_id=None):
    """Valider une proforma avec valide=False, proforma=True et nom_client"""
    localite = get_user_localite(request.user)
    if ticket_id:
        filtre = {'ticket': ticket_id, 'proforma': True}
        if localite:
            filtre['local_entrepot'] = localite
        panier = get_object_or_404(Panier, **filtre)
    else:
        # Récupérer uniquement les paniers non validés (sans ticket)
        filtre = {'utilisateur': request.user, 'valide': False, 'proforma': True, 'ticket__isnull': True}
        if localite:
            filtre['local_entrepot'] = localite
        panier = get_object_or_404(Panier, **filtre)
    
    # Calcul du total du panier
    panier_items = list(PanierItem.objects.filter(panier=panier).select_related('piece', 'panier'))
    if not panier_items:
        messages.error(request, "Le panier proforma est vide.")
        return redirect('add_proforma')
    
    total = total_panier_items(panier_items, panier.local_entrepot, panier=panier)
    nom_client = request.POST.get('nom_client', '').strip()
    
    if not nom_client:
        messages.error(request, "Le nom du client est obligatoire pour valider la proforma.")
        return redirect('add_proforma')
    
    montant_remise = parse_remise_montant(request.POST.get('remiser'), total)
    total_apres_remise = total - montant_remise
    
    # Création de la commande avec profoma=1
    commande = Commande.objects.create(
        panier=panier,
        numero_commande='PROF-' + str(panier.id) + '-' + str(Commande.objects.filter(panier=panier).count() + 1),
        total=total_apres_remise,
        remise=montant_remise,
        paye=False,
        total_sans_remise=total,
        utilisateur=request.user,
        profoma=1  # Marquer comme proforma
    )
    
    # Création du ticket
    ticket = Ticket.objects.create(
        numero='PROF-' + str(commande.id),
        commande=commande,
        utilise=False,
        utilisateur=request.user,
        client_name=nom_client
    )
    
    # Mise à jour du panier : valide=False, proforma=True, nom_client
    panier.valide = False  # Important : reste False pour proforma
    panier.proforma = True
    panier.nom_client = nom_client
    numero = f"PROF-{str(commande.id)}"
    panier.ticket = numero
    panier.save()
    
    messages.success(request, f"La proforma N°{ticket.numero} pour {nom_client} a été validée avec succès.")
    return redirect('add_proforma')

class ProformaAttenteView(LoginRequiredMixin, TemplateView):
    """Vue pour afficher les proformas en attente (proforma=True, valide=False)"""
    login_url = 'connexion'
    template_name = 'mag/proforma_attente.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        localite = get_user_localite(self.request.user)
        # Récupérer les proformas en attente (proforma=True, valide=False, avec ticket)
        paniers_proforma = Panier.objects.filter(
            proforma=True,
            valide=False,
            ticket__isnull=False
        ).select_related('local_entrepot').order_by('-date_creation')
        if localite:
            paniers_proforma = paniers_proforma.filter(local_entrepot=localite)

        context['paniers_proforma'] = paniers_proforma
        return context

@login_required(login_url='connexion')
def ajax_search_proformas(request):
    """Recherche AJAX des proformas par numéro ou nom client"""
    query = request.GET.get('q', '').strip()
    localite = get_user_localite(request.user)

    # Récupérer les proformas en attente
    paniers_proforma = Panier.objects.filter(
        proforma=True,
        valide=False,
        ticket__isnull=False
    ).select_related('local_entrepot')
    if localite:
        paniers_proforma = paniers_proforma.filter(local_entrepot=localite)

    # Filtrer par numéro de proforma (ticket) ou nom du client
    if query:
        paniers_proforma = paniers_proforma.filter(
            Q(ticket__icontains=query) |
            Q(nom_client__icontains=query)
        )

    paniers_proforma = paniers_proforma.order_by('-date_creation')

    html = render_to_string('mag/partials/_proforma_attente.html', {'paniers_proforma': paniers_proforma})
    return JsonResponse({
        'html': html,
        'count': paniers_proforma.count()
    })

def _context_proforma_document(panier, panier_items, commande=None):
    """Contexte commun modal / impression proforma (mise en page type bon de commande)."""
    lignes = []
    total_quantite = 0
    total_valeur = Decimal('0')
    for item in panier_items:
        pu = get_prix_unitaire(item.piece, panier.local_entrepot, item.new_price)
        item.prix_unitaire_affiche = pu
        item.total_ligne = pu * item.quantite
        lignes.append(item)
        total_quantite += item.quantite
        total_valeur += item.total_ligne

    montant_remise = commande.remise if commande else Decimal('0.0')
    if montant_remise > total_valeur:
        montant_remise = total_valeur
    total_apres_remise = total_valeur - montant_remise
    min_rows = 8
    empty_rows = range(max(0, min_rows - len(lignes)))

    ticket_safe = (panier.ticket or 'proforma').replace('/', '-').replace('\\', '-')
    return {
        'panier': panier,
        'panier_items': panier_items,
        'commande': commande,
        'lignes': lignes,
        'total_quantite': total_quantite,
        'total_valeur': total_valeur,
        'total': total_valeur,
        'montant_remise': montant_remise,
        'remise': montant_remise,
        'remise_pourcent': format_remise_pourcent(total_valeur, montant_remise),
        'total_apres_remise': total_apres_remise,
        'empty_rows': empty_rows,
        'localite': panier.local_entrepot,
        'print_title': f"Proforma {panier.ticket}",
        'pdf_filename': f"Proforma_{ticket_safe}.pdf",
        'auto_print': False,
        'pdf_export': False,
    }


@login_required(login_url='connexion')
def ajax_detail_proforma(request, ticket_id):
    """Récupérer les détails d'une proforma pour affichage dans le modal"""
    panier = get_object_or_404(
        Panier.objects.select_related('utilisateur', 'local_entrepot'),
        ticket=ticket_id,
        proforma=True,
        valide=False,
    )
    panier_items = PanierItem.objects.filter(panier=panier).select_related('piece')
    commande = Commande.objects.filter(panier=panier, profoma=1).first()
    context = _context_proforma_document(panier, panier_items, commande)
    html = render_to_string('mag/partials/_modal_proforma_detail.html', context, request=request)
    return JsonResponse({'html': html})

@require_POST
@login_required(login_url='connexion')
def valider_panier_proforma(request, ticket_id):
    """Valider le panier d'une proforma (valide=1)"""
    panier = get_object_or_404(Panier, ticket=ticket_id, proforma=True, valide=False)
    commande = Commande.objects.filter(panier=panier, profoma=1).first()
    
    if not commande:
        return JsonResponse({'success': False, 'message': 'Commande non trouvée pour cette proforma.'})
    
    # Calculer le total
    panier_items = list(PanierItem.objects.filter(panier=panier).select_related('piece', 'panier'))
    total = total_panier_items(panier_items, panier.local_entrepot, panier=panier)
    montant_remise = commande.remise if commande else Decimal('0.0')
    if montant_remise > total:
        montant_remise = total
    total_apres_remise = total - montant_remise
    
    # Mettre à jour le panier : valide=True
    panier.valide = True
    panier.save()
    
    # Publier via MQTT pour affichage en temps réel sur caisse.html
    _loc = getattr(panier, 'local_entrepot', None)
    publish_panier_valide(
        panier.id,
        total_apres_remise,
        local_entrepot_id=_loc.pk if _loc else None,
        local_entrepot_nom=str(_loc) if _loc else None,
    )
    
    return JsonResponse({
        'success': True,
        'message': f'La proforma N°{panier.ticket} a été validée avec succès.'
    })

@login_required(login_url='connexion')
def imprimer_proforma_pdf(request, ticket_id):
    """Proforma imprimable (HTML) ou PDF (?format=pdf), même mise en page que le bon de transfert."""
    panier = get_object_or_404(
        Panier.objects.select_related('utilisateur', 'local_entrepot'),
        ticket=ticket_id,
        proforma=True,
    )
    panier_items = PanierItem.objects.filter(panier=panier).select_related('piece')
    commande = Commande.objects.filter(panier=panier, profoma=1).first()
    context = _context_proforma_document(panier, panier_items, commande)
    context['auto_print'] = request.GET.get('print') == '1'

    if request.GET.get('format') == 'pdf':
        context['pdf_export'] = True
        html_content = render_to_string('mag/imprimer_proforma.html', context, request=request)
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = (
            f'inline; filename="{context["pdf_filename"]}"'
        )
        pisa_status = pisa.CreatePDF(html_content, dest=response)
        if pisa_status.err:
            return HttpResponse('Erreur lors de la génération du PDF', status=500)
        return response

    html_content = render_to_string('mag/imprimer_proforma.html', context, request=request)
    return HttpResponse(html_content)


@login_required(login_url='connexion')
def imprimer_recu_commande(request, ticket_id):
    """
    Réimprime le BON DE COMMANDE (avant paiement) pour un panier validé non encore payé.
    Permet de récupérer un bon perdu ou de relancer une impression échouée.
    """
    localite = get_user_localite(request.user)
    filtre = {'ticket': ticket_id, 'valide': True, 'panier_paye': False}
    if localite:
        filtre['local_entrepot'] = localite
    panier = get_object_or_404(Panier, **filtre)
    commande = Commande.objects.filter(panier=panier).order_by('-date_creation').first()
    if not commande:
        messages.error(request, f"Aucune commande trouvée pour le ticket {ticket_id}.")
        return redirect('caissiere')
    panier_items = list(PanierItem.objects.filter(panier=panier))

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    try:
        print_order_receipt_thermal(commande, panier_items)
        if is_ajax:
            return JsonResponse({'success': True, 'message': f"Bon de commande {ticket_id} réimprimé."})
        messages.success(request, f"✅ Bon de commande {ticket_id} réimprimé.")
    except Exception as e:
        if is_ajax:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
        messages.error(request, f"❌ Erreur impression : {e}")

    return redirect('caissiere')

# ============================================================================#
#         MODULE DE CONNEXION D'IMPRIMANTE USB GÉNÉRIQUE                      #
# ============================================================================#

@login_required(login_url='connexion')
def printer_scan_view(request):
    """
    GET → JSON. Scanne le bus USB et retourne la liste des imprimantes
    détectées (classe USB Printer).
    """
    from stock import printer_service
    try:
        printers = printer_service.scan_usb_printers()
    except RuntimeError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f"Erreur scan USB : {e}"}, status=500)

    saved = printer_service.get_session_printer(request)
    return JsonResponse({
        'success': True,
        'count': len(printers),
        'printers': printers,
        'saved_printer': saved,
        'backend': printer_service.backend_status(),
    })

@login_required(login_url='connexion')
@require_POST
def printer_connect_view(request):
    """Mémorise VID/PID de l'imprimante choisie (session) pour les impressions auto."""
    from stock import printer_service

    def _parse_int(value):
        if value is None:
            return None
        s = str(value).strip()
        try:
            return int(s, 16) if s.lower().startswith('0x') else int(s)
        except (ValueError, TypeError):
            return None

    vid = _parse_int(request.POST.get('vid'))
    pid = _parse_int(request.POST.get('pid'))
    if vid is None or pid is None:
        return JsonResponse({'success': False, 'error': "VID/PID invalides."}, status=400)

    info = printer_service.get_printer_info(vid, pid) or {}
    printer_service.set_session_printer(request, vid, pid, info)
    return JsonResponse({
        'success': True,
        'message': "Imprimante enregistrée pour les impressions automatiques.",
        'printer': printer_service.get_session_printer(request),
    })

@login_required(login_url='connexion')
@require_POST
def printer_test_view(request):
    """
    POST {vid, pid} → envoie une page de test ESC/POS sur l'imprimante.
    VID/PID acceptés en décimal ou en hex (préfixe 0x).
    """
    from stock import printer_service

    def _parse_int(value):
        if value is None:
            return None
        s = str(value).strip()
        try:
            return int(s, 16) if s.lower().startswith('0x') else int(s)
        except (ValueError, TypeError):
            return None

    vid = _parse_int(request.POST.get('vid'))
    pid = _parse_int(request.POST.get('pid'))
    if vid is None or pid is None:
        return JsonResponse({'success': False, 'error': "VID/PID invalides ou manquants."}, status=400)

    try:
        printer_service.print_test_page(vid, pid)
    except RuntimeError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f"Erreur impression : {e}"}, status=500)

    return JsonResponse({'success': True, 'message': "Page de test envoyée à l'imprimante."})


def _moyens_paiement_caisse():
    """Caisse : uniquement Espèce et Paiement numérique (GeniusPay)."""
    from ecom.services import get_moyen_espece, get_moyen_geniuspay

    espece = get_moyen_espece()
    if not espece.actif:
        espece.actif = True
        espece.save(update_fields=['actif'])
    gp = get_moyen_geniuspay()
    gp_fields = []
    if gp.nom != 'Paiement numérique':
        gp.nom = 'Paiement numérique'
        gp_fields.append('nom')
    if not gp.actif:
        gp.actif = True
        gp_fields.append('actif')
    if gp_fields:
        gp.save(update_fields=gp_fields)
    MoyenPaiement.objects.exclude(code__in=['espece', 'geniuspay']).update(actif=False)
    return [gp, espece]


def _paniers_caisse_en_attente(localite=None, q=None):
    """Paniers validés en attente d'encaissement, avec lignes et pièces préchargées.

    Les paniers e-commerce (commande_en_ligne=True) sont exclus : paiement chez
    le livreur via livraison_cmd_online, pas en caisse.
    """
    paniers = (
        Panier.objects.filter(
            valide=True,
            panier_paye=False,
            panier_livre=False,
            commande_en_ligne=False,
        )
        .filter(Q(proforma=0) | Q(proforma=True))
        .select_related('utilisateur')
        .prefetch_related(
            Prefetch(
                'panier_items',
                queryset=PanierItem.objects.select_related(
                'piece', 'piece__categorie', 'piece__sous_categorie'
            ).order_by('pk'),
            )
        )
        .order_by('-date_save')
    )
    if localite:
        paniers = paniers.filter(local_entrepot=localite)
    if q:
        paniers = paniers.filter(ticket__icontains=q)
    return paniers


def ajax_reload_paniers(request):
    """
    Vue AJAX pour recharger la liste des paniers non payés,
    avec possibilité de filtrer par ticket via le paramètre GET 'q'.
    Inclut les paniers normaux et les proformas validées.
    """
    q = request.GET.get('q', '').strip()
    localite = get_user_localite(request.user)
    paniers_non_valides = _paniers_caisse_en_attente(localite=localite, q=q or None)

    html = render_to_string(
        'mag/partials/_panier_no_valid.html',
        {'paniers_non_valides': paniers_non_valides}
    )
    return HttpResponse(html)

@login_required(login_url='connexion')
def ajax_reload_livraisons(request):
    """Vue AJAX pour recharger la liste des livraisons après un paiement validé"""
    from datetime import date
    localite = get_user_localite(request.user)

    # Récupérer les paniers payés et non livrés (hors commandes e-commerce)
    liste_panier = Panier.objects.filter(
        date_creation__month=date.today().month,
        valide=True,
        panier_paye=True,
        panier_livre=False,
        commande_en_ligne=False,
    ).order_by('panier_livre', '-date_creation')
    if localite:
        liste_panier = liste_panier.filter(local_entrepot=localite)

    # Calculer les statistiques
    base_day = Panier.objects.filter(
        date_creation=date.today(),
        valide=True,
        panier_paye=True,
        commande_en_ligne=False,
    )
    base_month = Panier.objects.filter(
        date_creation__month=date.today().month,
        valide=True,
        panier_paye=True,
        commande_en_ligne=False,
    )
    if localite:
        base_day = base_day.filter(local_entrepot=localite)
        base_month = base_month.filter(local_entrepot=localite)

    tot_panier_day = base_day.count()
    tot_panier = base_month.count()
    tot_en_at = base_day.filter(panier_livre=False).count()
    tot_livre = Panier.objects.filter(
        date_livr_panier=date.today(),
        valide=True,
        panier_paye=True,
        panier_livre=True,
        commande_en_ligne=False,
    )
    if localite:
        tot_livre = tot_livre.filter(local_entrepot=localite)
    tot_livre = tot_livre.count()
    
    html = render_to_string('mag/partials/_liste_livraisons.html', {'liste_panier': liste_panier})
    return JsonResponse({
        'html': html,
        'tot_panier_day': tot_panier_day,
        'tot_panier': tot_panier,
        'tot_en_at': tot_en_at,
        'tot_livre': tot_livre
    })

@login_required(login_url='connexion')
def Caisse(request):
    dates = date.today()
    localite = get_user_localite(request.user)
    paniers_non_valides = _paniers_caisse_en_attente(localite=localite)
    cmdes = (
        Commande.objects.filter(date_creation=dates, commande_en_ligne=False)
        .select_related('utilisateur', 'panier', 'ticket', 'bon_paiement', 'moyen_paiement')
        .prefetch_related('paiements_geniuspay')
        .order_by('-date_creation')
    )
    if localite:
        cmdes = cmdes.filter(panier__local_entrepot=localite)
    try:
        bon_commande_print_url_tpl = reverse(
            'imprimer_bon_commande_vente',
            kwargs={'ticket_numero': '__TICKET__'},
        )
    except Exception:
        bon_commande_print_url_tpl = '/stocks/caisse/bon-commande/__TICKET__/imprimer/'
    from .tva_service import get_taux_tva, tva_est_active
    context = {
        'paniers_non_valides': paniers_non_valides,
        'cmdes': cmdes,
        'moyens_paiement': _moyens_paiement_caisse(),
        'bon_commande_print_url_tpl': bon_commande_print_url_tpl,
        'tva_active': tva_est_active(),
        'taux_tva': get_taux_tva(),
    }
    context.update(export_urls(request, 'export_caisse_ventes_excel', 'export_caisse_ventes_pdf'))
    return render(request, 'mag/caisse.html', context)


@login_required(login_url='connexion')
def ajax_caisse_detail(request, ticket_id):
    """Retourne le formulaire de caisse (_caisse_form.html) pour un ticket donné, via AJAX."""
    localite = get_user_localite(request.user)
    filtre_panier = {
        'ticket': ticket_id,
        'valide': True,
        'panier_paye': False,
        'commande_en_ligne': False,
    }
    if localite:
        filtre_panier['local_entrepot'] = localite
    panier = get_object_or_404(Panier, **filtre_panier)
    panier_items = PanierItem.objects.filter(panier=panier)
    ticket = get_object_or_404(Ticket, numero=ticket_id, utilise=False)
    commande = ticket.commande
    if commande.commande_en_ligne:
        return JsonResponse(
            {'error': 'Commande en ligne : paiement via le livreur, pas en caisse.'},
            status=400,
        )
    from .tva_service import get_taux_tva, tva_est_active
    context = {
        'moyens_paiement': _moyens_paiement_caisse(),
        'panier_items': panier_items,
        'commande': commande,
        'ticket': ticket,
        'tva_active': tva_est_active(),
        'taux_tva': get_taux_tva(),
        }
    html = render_to_string('mag/partials/_caisse_form.html', context, request=request)
    return JsonResponse({'html': html})

BASE_DIR = Path(__file__).resolve().parent.parent
# Identifiants VID et PID de l'imprimante
VID = 0x04B8  # VID pour Epson
PID = 0x0E28  # PID pour TM-T20III

def get_usb_backend():
    """Délègue au service imprimante (DLL embarquée + libusb-package)."""
    from stock import printer_service
    return printer_service._get_backend()

def print_image(dev, image_path):
    img = Image.open(image_path)
    img = img.convert('L')
    width = 200
    w_percent = width / float(img.size[0])
    h_size = int((float(img.size[1]) * float(w_percent)))
    # Si la largeur ou la hauteur dépasse 255, ajuster les dimensions
    if width // 8 > 255:
        width = 255 * 8 
    if h_size > 255:
        h_size = 255  
    img = img.resize((width, h_size), Image.LANCZOS)
    img = img.convert('1')  # Convertir l'image en noir et blanc
    pixels = img.tobytes()
    # Assurez-vous que la taille du tableau de pixels ne dépasse pas 255
    dev.write(0x01, b'\x1d\x76\x30\x00' + bytes([width // 8, 0, h_size, 0]) + pixels)

def generate_receipt_pdf(request, commande, panier_items):
    """
    Imprime automatiquement le reçu sur l'imprimante USB (session ou auto-détection).
    """
    from stock import printer_service
    if not printer_service.HAS_USB:
        raise RuntimeError(
            "Support imprimante USB non disponible. pip install pyusb libusb-package"
        )
    printer_service.print_receipt_for_request(request, commande, panier_items)

def generate_receipt_pdf_file(commande, panier_items):
    """
    Génère un fichier PDF du reçu (format ticket 80 mm, identique au thermique)
    et le sauvegarde dans media/tickets/. Retourne le chemin relatif.
    """
    from stock.receipt_ticket_pdf import save_receipt_pdf_file

    return save_receipt_pdf_file(commande, panier_items)

def print_order_receipt_thermal(commande, panier_items):
    """
    Imprime un BON DE COMMANDE (avant paiement) sur l'imprimante Epson TM-T20III.
    À remettre au client pour qu'il aille payer en caisse avec le numéro de ticket.
    Pas de champs paiement / rendu — la remise est affichée si présente.
    """
    if not HAS_USB:
        raise Exception("Support imprimante USB non disponible. Installez pyusb: pip install pyusb")
    backend = get_usb_backend()
    dev = None
    kernel_driver_detached = False
    try:
        if backend:
            dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
        else:
            dev = usb.core.find(idVendor=VID, idProduct=PID)
        if dev is None:
            raise Exception("Imprimante Epson TM-T20III non trouvée. Vérifiez la connexion USB.")
        try:
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
                kernel_driver_detached = True
        except (usb.core.USBError, NotImplementedError, AttributeError):
            pass
        try:
            dev.set_configuration()
        except usb.core.USBError as e:
            if e.errno == 13:
                raise Exception("Erreur de permissions USB (Access denied). Débranchez/rebranchez l'imprimante ou redémarrez l'ordinateur.")
            raise Exception(f"Erreur de configuration de l'imprimante : {e}")
    except Exception as e:
        error_msg = str(e)
        if "No backend available" in error_msg or "backend" in error_msg.lower():
            raise Exception("Backend USB non disponible. Installez libusb-package : pip install libusb-package.")
        raise Exception(f"Erreur lors de la connexion à l'imprimante : {e}")

    try:
        MARGIN = 6
        LINE_WIDTH = 50
        INNER_WIDTH = LINE_WIDTH - MARGIN * 2

        def write(text, align='left', bold=False, double_height=False):
            alignments = {'left': b'\x1b\x61\x00', 'center': b'\x1b\x61\x01', 'right': b'\x1b\x61\x02'}
            if align in alignments:
                dev.write(0x01, alignments[align])
            dev.write(0x01, b'\x1b\x45' + (b'\x01' if bold else b'\x00'))
            dev.write(0x01, b'\x1d\x21' + (b'\x11' if double_height else b'\x00'))
            padded_text = f"{' ' * MARGIN}{text}{' ' * MARGIN}"
            dev.write(0x01, f"{padded_text[:LINE_WIDTH]}\n".encode('cp850'))
            dev.write(0x01, b'\x1b\x21\x00')

        dev.write(0x01, b'\x1b\x40')  # Init
        # En-tête
        write("P&B Auto-Pieces", align='center', bold=True, double_height=True)
        write("*" * INNER_WIDTH, align='center')
        write("BON DE COMMANDE", align='center', bold=True)
        write("(A presenter en caisse)", align='center')
        write("*" * INNER_WIDTH, align='center')

        # Infos commande
        ticket_num = getattr(commande.panier, 'ticket', '') or f"TKT{commande.id}"
        write(f"Ticket : {ticket_num}", align='left', bold=True)
        commande_label = f"{commande.numero_commande}"
        if commande.date:
            date_label = commande.date.strftime('%d/%m/%Y %H:%M')
        else:
            date_label = commande.date_creation.strftime('%d/%m/%Y')
        space = max(1, INNER_WIDTH - len(commande_label) - len(date_label))
        write(f"{commande_label}{' ' * space}{date_label}", align='left')
        if commande.utilisateur:
            write(f"Hote : {commande.utilisateur.username}", align='left')
        local = getattr(commande.panier, 'local_entrepot', None)
        if local:
            write(f"Localite : {str(local)[:INNER_WIDTH - 12]}", align='left')
        write("-" * INNER_WIDTH, align='center')

        # En-tête articles
        header_line = f"{'Désignation':<20}{'Qte':>4}{'PU':>7}{'Tot':>7}"
        write(header_line, align='left', bold=True)

        # Articles
        for item in panier_items:
            designation = item.piece.designation
            quantite = item.quantite
            prix = _pu_item_panier(item, commande=commande)
            total_ligne = prix * quantite
            lines = textwrap.wrap(designation, width=20) or [designation[:20]]
            item_line = f"{lines[0]:<20}{quantite:>4}{int(prix):>7}{int(total_ligne):>7}"
            write(item_line, align='left')
            for extra in lines[1:]:
                write(f"{extra}", align='left')

        write("-" * INNER_WIDTH, align='center')
        dev.write(0x01, b'\x1b\x33\x14')  # interligne réduit

        total_brut_label = "Total Brut"
        total_brut_value = str(int(commande.total_sans_remise))
        space_brut = max(1, INNER_WIDTH - len(total_brut_label) - len(total_brut_value))
        write(f"{total_brut_label}{' ' * space_brut}{total_brut_value}", align='left')

        if commande.remise and commande.remise > 0:
            remise_label = "Remise"
            remise_value = f"-{format_remise_pourcent_commande(commande)}"
            space_remise = max(1, INNER_WIDTH - len(remise_label) - len(remise_value))
            write(f"{remise_label}{' ' * space_remise}{remise_value}", align='left')

        a_payer_label = "A PAYER"
        a_payer_value = f"{int(commande.total)} Fcfa"
        space_pay = max(1, INNER_WIDTH - len(a_payer_label) - len(a_payer_value))
        write(f"{a_payer_label}{' ' * space_pay}{a_payer_value}", align='left', bold=True)

        dev.write(0x01, b'\x1b\x33\x1e')  # interligne par défaut
        write("-" * INNER_WIDTH, align='center')

        dev.write(0x01, "\nVeuillez vous presenter a la caisse\n".encode('cp850'))
        dev.write(0x01, "pour effectuer le paiement.\n".encode('cp850'))
        dev.write(0x01, "Ce bon n'est pas un recu de paiement.\n".encode('cp850'))
        dev.write(0x01, "*** P&B Auto-Pieces ***\n".encode('cp850'))

        for _ in range(8):
            dev.write(0x01, b'\x0a')
        dev.write(0x01, b'\x1d\x56\x00')  # découpe
        time.sleep(0.5)
    except Exception as e:
        raise Exception(f"Erreur lors de l'impression du bon de commande : {e}")
    finally:
        if dev is not None:
            try:
                try:
                    usb.util.release_interface(dev, 0)
                except (usb.core.USBError, AttributeError):
                    pass
                if kernel_driver_detached:
                    try:
                        dev.attach_kernel_driver(0)
                    except (usb.core.USBError, NotImplementedError, AttributeError):
                        pass
                try:
                    dev.reset()
                except (usb.core.USBError, AttributeError):
                    pass
                time.sleep(0.2)
            except Exception:
                pass


def generate_order_receipt_pdf_file(commande, panier_items):
    """
    Génère un PDF A4 du BON DE COMMANDE et le sauvegarde dans media/tickets/.
    Retourne le chemin relatif (ou None en cas d'échec).
    """
    output_dir = os.path.join(settings.MEDIA_ROOT, 'tickets')
    os.makedirs(output_dir, exist_ok=True)

    filename = f"bon_commande_{commande.numero_commande.replace('/', '_').replace(' ', '_')}.pdf"
    output_path = os.path.join(output_dir, filename)

    page_width, page_height = A4
    margin = 15 * mm
    y = page_height - margin

    c = canvas.Canvas(output_path, pagesize=A4)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(page_width / 2, y, "P&B Auto-Pieces")
    y -= 14
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(page_width / 2, y, "BON DE COMMANDE")
    y -= 10
    c.setFont("Helvetica-Oblique", 8)
    c.drawCentredString(page_width / 2, y, "(À présenter à la caisse)")
    y -= 8
    c.line(margin, y, page_width - margin, y)
    y -= 12

    ticket_num = getattr(commande.panier, 'ticket', '') or f"TKT{commande.id}"
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, f"Ticket : {ticket_num}")
    y -= 12
    c.setFont("Helvetica", 9)
    c.drawString(margin, y, f"Commande : {commande.numero_commande}")
    y -= 12
    date_str = commande.date.strftime('%d/%m/%Y %H:%M') if commande.date else commande.date_creation.strftime('%d/%m/%Y')
    c.drawString(margin, y, f"Date : {date_str}")
    y -= 12
    if commande.utilisateur:
        c.drawString(margin, y, f"Hôte : {commande.utilisateur.username}")
        y -= 12
    local = getattr(commande.panier, 'local_entrepot', None)
    if local:
        c.drawString(margin, y, f"Localité : {local}")
        y -= 12
    y -= 4
    c.line(margin, y, page_width - margin, y)
    y -= 12

    c.setFont("Helvetica-Bold", 9)
    c.drawString(margin, y, "Désignation")
    c.drawRightString(page_width - margin - 90, y, "Qté")
    c.drawRightString(page_width - margin - 60, y, "PU")
    c.drawRightString(page_width - margin, y, "Total")
    y -= 8
    c.line(margin, y, page_width - margin, y)
    y -= 10

    c.setFont("Helvetica", 8)
    for item in panier_items:
        designation = item.piece.designation
        quantite = item.quantite
        prix = _pu_item_panier(item, commande=commande)
        total_ligne = prix * quantite
        c.drawString(margin, y, designation[:40])
        c.drawRightString(page_width - margin - 90, y, str(quantite))
        c.drawRightString(page_width - margin - 60, y, str(int(prix)))
        c.drawRightString(page_width - margin, y, str(int(total_ligne)))
        y -= 11

    c.line(margin, y, page_width - margin, y)
    y -= 14

    c.setFont("Helvetica", 9)
    c.drawString(margin, y, "Total Brut :")
    c.drawRightString(page_width - margin, y, f"{int(commande.total_sans_remise)} Fcfa")
    y -= 12
    if commande.remise and commande.remise > 0:
        c.drawString(margin, y, f"Remise : -{format_remise_pourcent_commande(commande)}")
        y -= 12
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, y, "À PAYER :")
    c.drawRightString(page_width - margin, y, f"{int(commande.total)} Fcfa")
    y -= 18

    c.setFont("Helvetica-Oblique", 8)
    c.drawCentredString(page_width / 2, y, "Veuillez vous présenter à la caisse pour effectuer le paiement.")
    y -= 10
    c.drawCentredString(page_width / 2, y, "Ce bon n'est pas un reçu de paiement.")

    c.save()
    return f"tickets/{filename}"

@login_required(login_url='connexion')
def valider_panier_paiement(request, ticket_id):
    # Accepter les paniers normaux (proforma=0) ET les proformas validées (proforma=True)
    # Exclure les commandes e-commerce (paiement livreur).
    localite = get_user_localite(request.user)
    filtre_panier = {
        'ticket': ticket_id,
        'valide': True,
        'panier_paye': False,
        'commande_en_ligne': False,
    }
    if localite:
        filtre_panier['local_entrepot'] = localite
    panier = get_object_or_404(Panier, **filtre_panier)
    panier_items = PanierItem.objects.filter(panier=panier)
    ticket = get_object_or_404(Ticket, numero=ticket_id, utilise=False)
    commande = ticket.commande
    if commande.commande_en_ligne:
        messages.error(
            request,
            "Cette commande en ligne se paie chez le livreur, pas en caisse.",
        )
        return redirect('caissiere')

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == 'POST':
        montant_paye = request.POST.get('montant', '0')
        moyen_paiement_id = request.POST.get('moyen_paiement')
        moyen_paiement = MoyenPaiement.objects.get(id=moyen_paiement_id)
        try:
            montant_paye = Decimal(montant_paye)
        except (InvalidOperation, ValueError):
            montant_paye = Decimal('0.0')
        appliquer_tva = request.POST.get('appliquer_tva') in ('on', '1', 'true', 'True')
        totals = compute_checkout_totals(
            total=commande.total,
            moyen_paiement=moyen_paiement,
            appliquer_tva=appliquer_tva,
        )
        montant_tva = totals['tva']
        montant_timbre = totals['timbre']
        bareme = totals['bareme']
        total_a_payer = totals['total_a_payer']

        if (moyen_paiement.code or '').lower() == 'geniuspay':
            from django.conf import settings as dj_settings
            from stock.geniuspay import GeniusPayError, montant_xof
            from stock.paiement_service import initier_paiement_commande

            min_amount = int(getattr(dj_settings, 'GENIUSPAY_MIN_AMOUNT', 200) or 200)
            if montant_xof(total_a_payer) < min_amount:
                msg = f'Paiement numérique : montant minimum {min_amount} FCFA.'
                if is_ajax:
                    return JsonResponse({'success': False, 'error': msg}, status=400)
                messages.error(request, msg)
                return redirect('caissiere')
            try:
                gp = initier_paiement_commande(
                    commande,
                    source='caisse',
                    request=request,
                    appliquer_tva=appliquer_tva,
                    caissier=request.user,
                    amount=total_a_payer,
                )
            except GeniusPayError as exc:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': str(exc)}, status=400)
                messages.error(request, str(exc))
                return redirect('caissiere')
            if not gp.checkout_url:
                msg = 'URL de paiement GeniusPay manquante.'
                if is_ajax:
                    return JsonResponse({'success': False, 'error': msg}, status=400)
                messages.error(request, msg)
                return redirect('caissiere')
            status_url = reverse('caisse_geniuspay_statut', kwargs={'ticket_id': ticket.numero})
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'pending': True,
                    'checkout_url': gp.checkout_url,
                    'reference': gp.reference,
                    'status_url': status_url,
                })
            return redirect(gp.checkout_url)

        if montant_paye < total_a_payer:
            details = []
            if montant_tva > 0:
                details.append(f"TVA {montant_tva:,.0f} Fcfa")
            if montant_timbre > 0:
                details.append(f"timbre fiscal {montant_timbre:,.0f} Fcfa")
            if details:
                msg = (
                    f"Montant insuffisant. À payer : {total_a_payer:,.0f} Fcfa "
                    f"(dont {' et '.join(details)})."
                )
            else:
                msg = "Le montant payé est insuffisant"
            if is_ajax:
                return JsonResponse({'success': False, 'error': msg}, status=400)
            messages.error(request, msg)
            return redirect('caissiere')

        if montant_paye >= total_a_payer:
            # Vérifier que l'utilisateur est authentifié
            if not request.user.is_authenticated:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': "Vous devez être connecté."}, status=403)
                messages.error(request, "Vous devez être connecté pour valider un paiement.")
                return redirect('connexion')

            from stock.paiement_service import (
                finaliser_encaissement_caisse,
                payload_succes_caisse,
            )
            try:
                result = finaliser_encaissement_caisse(
                    request=request,
                    commande=commande,
                    panier=panier,
                    ticket=ticket,
                    moyen_paiement=moyen_paiement,
                    appliquer_tva=appliquer_tva,
                    montant_paye=montant_paye,
                    panier_items=list(panier_items),
                    caissier=request.user,
                )
            except ValueError as exc:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': str(exc)}, status=400)
                messages.error(request, str(exc))
                return redirect('caissiere')

            bon_paiement = result['bon_paiement']
            if is_ajax:
                payload = payload_succes_caisse(
                    request,
                    result['commande'],
                    result['panier'],
                    result['panier_items'],
                    result['ticket'],
                    bon_paiement,
                )
                if not bon_paiement:
                    payload['warning'] = payload.get('warning') or (
                        "Paiement OK, bon de commande non généré."
                    )
                return JsonResponse(payload)
            if not bon_paiement:
                messages.warning(
                    request,
                    "Paiement enregistré, bon de commande non généré.",
                )
                return redirect(f"{reverse('caissiere')}?paiement=success")
            return redirect(f"{reverse('caissiere')}?paiement=success&bon_ticket={ticket.numero}")
    context = {
        'moyens_paiement': _moyens_paiement_caisse(),
        'paniers_non_valides': Panier.objects.filter(
            valide=True,
            panier_paye=False,
            panier_livre=False,
            commande_en_ligne=False,
        ).filter(
            Q(proforma=0) | Q(proforma=True)
        ),
        'panier_items': panier_items,
        'commande': commande,
        'ticket': ticket,
    }
    return render(request, 'mag/caisse.html', context)


@login_required(login_url='connexion')
def ajax_calcul_timbre(request):
    """Prévisualisation timbre + TVA selon moyen de paiement et case TVA (caisse)."""
    from .timbre_service import moyen_paiement_est_espece
    from .tva_service import get_taux_tva, tva_est_active
    try:
        total = Decimal(request.GET.get('total', '0') or '0')
    except (InvalidOperation, ValueError):
        total = Decimal('0')
    mp_id = request.GET.get('moyen_paiement')
    moyen = MoyenPaiement.objects.filter(pk=mp_id).first() if mp_id else None
    appliquer_tva = request.GET.get('appliquer_tva') in ('1', 'true', 'on')
    totals = compute_checkout_totals(
        total=total,
        moyen_paiement=moyen,
        appliquer_tva=appliquer_tva,
    )
    return JsonResponse({
        'timbre': float(totals['timbre']),
        'tva': float(totals['tva']),
        'tva_active': tva_est_active(),
        'taux_tva': float(get_taux_tva()),
        'total': float(total),
        'total_a_payer': float(totals['total_a_payer']),
        'espece': moyen_paiement_est_espece(moyen),
        'bareme_label': str(totals['bareme']) if totals['bareme'] else None,
    })

@login_required(login_url='connexion')
@require_POST
def reimprimer_recu_paiement(request, ticket_numero):
    """Réimprime le reçu thermique de paiement pour une commande déjà payée."""
    localite = get_user_localite(request.user)
    ticket = get_object_or_404(Ticket, numero=ticket_numero)
    commande = ticket.commande
    if not commande.paye:
        return JsonResponse(
            {'success': False, 'error': 'Cette commande n\'est pas encore payée.'},
            status=400,
        )
    panier = commande.panier
    if localite and panier.local_entrepot_id != localite.id:
        return JsonResponse({'success': False, 'error': 'Accès refusé à cette localité.'}, status=403)
    panier_items = list(
        PanierItem.objects.filter(panier=panier).select_related('piece')
    )
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    try:
        generate_receipt_pdf(request, commande, panier_items)
        msg = f"Reçu de paiement {ticket_numero} réimprimé."
        if is_ajax:
            return JsonResponse({'success': True, 'message': msg})
        messages.success(request, msg)
    except Exception as e:
        if is_ajax:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
        messages.error(request, f"Erreur impression : {e}")
    return redirect('caissiere')

@login_required(login_url='connexion')
def imprimer_bon_commande_vente(request, ticket_numero):
    """Bon de commande caisse (HTML / PDF) après paiement."""
    ticket = get_object_or_404(Ticket, numero=ticket_numero)
    commande = ticket.commande
    panier = commande.panier
    try:
        bon = commande.bon_paiement
    except BonCommandePaiement.DoesNotExist:
        messages.error(request, "Aucun bon de commande pour ce ticket.")
        return redirect('caissiere')
    panier_items = PanierItem.objects.filter(panier=panier).select_related('piece')
    ctx = context_bon_commande_vente(bon, commande, panier, panier_items)
    if request.GET.get('format') == 'pdf':
        try:
            pdf_bytes = generate_bon_commande_vente_pdf(
                bon, commande, panier, list(panier_items)
            )
        except Exception as exc:
            return HttpResponse(f'Erreur PDF : {exc}', status=500)
        nom_ascii, nom_utf8_enc = nom_fichier_bon_commande_vente(bon)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'inline; filename="{nom_ascii}"; filename*=UTF-8\'\'{nom_utf8_enc}'
        )
        return response
    if request.GET.get('fragment') == '1':
        html = (
            render_to_string('mag/partials/_bon_commande_vente_styles.html', request=request)
            + render_to_string('mag/partials/_bon_commande_vente_body.html', ctx, request=request)
        )
        return HttpResponse(html)
    ctx['auto_print'] = request.GET.get('print') == '1'
    ctx['print_title'] = titre_bon_commande_vente(bon)
    ctx['pdf_filename'] = nom_fichier_bon_commande_vente(bon)[0]
    html_content = render_to_string('mag/imprimer_bon_commande_vente.html', ctx, request=request)
    return HttpResponse(html_content)


@login_required
def imprimer_ticket_pdf(request, ticket_id):
    ticket = get_object_or_404(Ticket, pk=ticket_id)
    commande = ticket.commande
    panier_items = PanierItem.objects.filter(panier=commande.panier)
    if not HAS_USB:
        messages.error(request, "Support imprimante USB non disponible. Installez pyusb: pip install pyusb")
        return redirect('liste_tickets')
    # Connexion à l’imprimante
    dev = usb.core.find(idVendor=0x04B8, idProduct=0x0E28)
    if dev is None:
        messages.error(request, "Imprimante Epson non trouvée. Vérifiez la connexion USB.")
        return redirect('liste_tickets')
    try:
        dev.set_configuration()
    except usb.core.USBError as e:
        messages.error(request, f"Erreur configuration imprimante : {e}")
        return redirect('liste_tickets')
    # Paramètres
    MARGIN = 6
    LINE_WIDTH = 40
    INNER_WIDTH = LINE_WIDTH - MARGIN * 2

    def write(text, align='left', bold=False, double_height=False):
        alignments = {'left': b'\x1b\x61\x00', 'center': b'\x1b\x61\x01', 'right': b'\x1b\x61\x02'}
        if align in alignments:
            dev.write(0x01, alignments[align])
        dev.write(0x01, b'\x1b\x45' + (b'\x01' if bold else b'\x00'))
        dev.write(0x01, b'\x1d\x21' + (b'\x11' if double_height else b'\x00'))
        padded = f"{' ' * MARGIN}{text}{' ' * MARGIN}"
        dev.write(0x01, f"{padded[:LINE_WIDTH]}\n".encode('cp850'))
        dev.write(0x01, b'\x1b\x21\x00')
    dev.write(0x01, b'\x1b\x40')  # Init imprimante
    # En-tête
    write("Auto-Pièce", align='center', bold=True, double_height=True)
    write("*" * INNER_WIDTH, align='center')
    write("TICKET DE CAISSE", align='center', bold=True)
    write("*" * INNER_WIDTH, align='center')
    # Commande et date sur une ligne
    commande_label = f"Cmd: {commande.numero_commande}"
    date_label = commande.date_creation.strftime('%d/%m/%Y')
    space = INNER_WIDTH - len(commande_label) - len(date_label)
    write(f"{commande_label}{' ' * space}{date_label}", align='left')
    write(f"Caissier : {commande.utilisateur.username}", align='left')
    write("-" * INNER_WIDTH, align='center')
    # En-tête articles
    write(f"{'Désignation':<16}{'Q':>3}{'PU':>6}{'T':>7}", align='left', bold=True)
    # Articles
    for item in panier_items:
        designation = item.piece.designation
        quantite = item.quantite
        prix = _pu_item_panier(item, commande=commande)
        total = quantite * prix
        lines = textwrap.wrap(designation, width=16)
        write(f"{lines[0]:<16}{quantite:>3}{int(prix):>6}{int(total):>7}", align='left')
        for extra in lines[1:]:
            write(extra, align='left')
    write("-" * INNER_WIDTH, align='center')
    # Totaux
    write(f"{'Total Brut':<22}{int(commande.total_sans_remise):>10}", align='left')
    if commande.remise > 0:
        remise_pct = format_remise_pourcent_commande(commande)
        write(f"{'Remise':<22}-{remise_pct:>10}", align='left')
    write(f"{'Total Net':<22}{int(commande.total):>10}", align='left')
    write(f"{'Payé':<22}{int(commande.montant_paye):>10}", align='left')
    write(f"{'Rendu':<22}{int(commande.montant_reste):>10}", align='left')
    moyen_nom = commande.libelle_paiement or "—"
    label_mp = "Payer par"
    space_mp = INNER_WIDTH - len(label_mp) - len(moyen_nom)
    write(f"{label_mp}{' ' * max(1, space_mp)}{moyen_nom}", align='left')
    # Footer
    write("-" * INNER_WIDTH, align='center')
    dev.write(0x01, "\nMerci pour votre achat !\n".encode('cp850'))
    dev.write(0x01, "Auto-Pièce la Qualité assurée\n".encode('cp850'))
    dev.write(0x01, "Contactez-nous au 0787532210\n".encode('cp850'))
    dev.write(0x01, "Retrouvez-nous sur \n".encode('cp850'))
    dev.write(0x01, "*** AutoPiece.@facebook.com ***\n".encode('cp850'))
    for _ in range(8):
        dev.write(0x01, b'\x0a')
    dev.write(0x01, b'\x1d\x56\x00')
    usb.util.release_interface(dev, 0)
    messages.success(request, f"Ticket {ticket.numero} envoyé à l'imprimante.")
    return redirect('liste_tickets')

class Liste_ticketsView(LoginRequiredMixin, TemplateView):
    # permission_url = 'dash'
    login_url = 'connexion'
    template_name = 'mag/list_ticket.html'
    def get(self, request, *args, **kwargs):
        request.session['last_activity'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return super().get(request, *args, **kwargs)
    def post(self, request, *args, **kwargs):
        request.session['last_activity'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return super().post(request, *args, **kwargs)
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dates = date.today()
        annee = date.today().year
        mois = date.today().month
        moisact = calendar.month_name[mois]
        label = [calendar.month_name[month][:1] for month in range(1, 13)]

        user = self.request.user
        filt = periode_filter_context(self.request, user, reset_url_name='stock')
        localite = filt['localite_active']
        tickets = (
            Ticket.objects.filter(
                date_save__date__range=[filt['date_debut'], filt['date_fin']]
            )
            .select_related('utilisateur', 'commande', 'commande__bon_paiement')
            .order_by('-date_save')
        )
        if localite:
            tickets = tickets.filter(commande__panier__local_entrepot=localite)
        context = {
            'labels': label,
            'annee': annee,
            'dates': dates,
            'tickets': tickets,
            'filter_modal_id': 'ticketsFilterModal',
        }
        context.update(filt)
        return context

def _cmdes_liste_queryset(request):
    """Queryset partagé Liste commandes + rechargement AJAX (filtres période / localité)."""
    filt = periode_filter_context(request, request.user, reset_url_name='liste_commandes')
    localite = filt['localite_active']
    cmdes = (
        Commande.objects.filter(
            date_creation__range=[filt['date_debut'], filt['date_fin']]
        )
        .select_related('utilisateur', 'ticket', 'bon_paiement', 'panier')
        .order_by('-date_creation')
    )
    if localite:
        cmdes = cmdes.filter(panier__local_entrepot=localite)
    return cmdes, filt


@login_required(login_url='connexion')
def ajax_reload_liste_commandes(request):
    """Recharge le tableau Liste commandes sans recharger la page (MQTT / polling)."""
    cmdes, _filt = _cmdes_liste_queryset(request)
    html = render_to_string(
        'mag/partials/_liste_commandes_table.html',
        {'cmdes': cmdes},
        request=request,
    )
    return HttpResponse(html)


class Liste_CmdeView(LoginRequiredMixin, TemplateView):
    # permission_url = 'dash'
    login_url = 'connexion'
    template_name = 'mag/list_cmd.html'
    def get(self, request, *args, **kwargs):
        request.session['last_activity'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return super().get(request, *args, **kwargs)
    def post(self, request, *args, **kwargs):
        request.session['last_activity'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return super().post(request, *args, **kwargs)
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dates = date.today()
        annee = date.today().year
        mois = date.today().month
        moisact = calendar.month_name[mois]
        label = [calendar.month_name[month][:1] for month in range(1, 13)]

        cmdes, filt = _cmdes_liste_queryset(self.request)
        context = {
            'labels': label,
            'annee': annee,
            'dates': dates,
            'cmdes': cmdes,
            'filter_modal_id': 'cmdesFilterModal',
        }
        context.update(filt)
        context.update(export_urls(
            self.request, 'export_liste_commandes_excel', 'export_liste_commandes_pdf',
        ))
        return context


class ListeVentesView(LoginRequiredMixin, TemplateView):
    """Liste des ventes payées — période par défaut : journée en cours."""
    login_url = 'connexion'
    template_name = 'mag/liste_ventes.html'

    def get(self, request, *args, **kwargs):
        request.session['last_activity'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        request.session['last_activity'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return super().post(request, *args, **kwargs)

    @staticmethod
    def _base_ventes_qs(localite=None):
        qs = Commande.objects.filter(paye=True, panier__valide=True)
        if localite:
            qs = qs.filter(panier__local_entrepot=localite)
        return qs

    @staticmethod
    def _agg_ventes(qs):
        return {
            'nombre': qs.count(),
            'montant': qs.aggregate(t=Sum('total'))['t'] or 0,
            'verse': qs.aggregate(t=Sum('montant_paye'))['t'] or 0,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = date.today()
        annee = today.year
        mois = today.month

        user = self.request.user
        filt = periode_filter_context(
            self.request, user, reset_url_name='liste_ventes', default='aujourdhui'
        )
        localite = filt['localite_active']

        base = self._base_ventes_qs(localite)
        cmdes = (
            base.filter(date_creation__range=[filt['date_debut'], filt['date_fin']])
            .select_related('utilisateur', 'ticket', 'bon_paiement', 'moyen_paiement')
            .prefetch_related('paiements_geniuspay')
            .order_by('-date_creation', '-date')
        )

        debut_mois = date(annee, mois, 1)
        fin_mois = date(annee, mois, calendar.monthrange(annee, mois)[1])
        debut_annee = date(annee, 1, 1)
        fin_annee = date(annee, 12, 31)

        stats_jour = self._agg_ventes(base.filter(date_creation=today))
        stats_mois = self._agg_ventes(base.filter(date_creation__range=[debut_mois, fin_mois]))
        stats_annee = self._agg_ventes(base.filter(date_creation__range=[debut_annee, fin_annee]))

        context.update(filt)
        context.update({
            'dates': today,
            'annee': annee,
            'moisact': MOIS_FR[mois],
            'cmdes': cmdes,
            'filter_modal_id': 'ventesFilterModal',
            'stats_jour': stats_jour,
            'stats_mois': stats_mois,
            'stats_annee': stats_annee,
        })
        context.update(export_urls(
            self.request, 'export_liste_ventes_excel', 'export_liste_ventes_pdf',
        ))
        return context


class Liste_StockView(LoginRequiredMixin, TemplateView):
    # permission_url = 'dash'
    login_url = 'connexion'
    template_name = 'list_art.html'
    def get(self, request, *args, **kwargs):
        request.session['last_activity'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return super().get(request, *args, **kwargs)
    def post(self, request, *args, **kwargs):
        request.session['last_activity'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return super().post(request, *args, **kwargs)
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dates = date.today()
        annee = date.today().year
        mois = date.today().month
        moisact = calendar.month_name[mois]
        label = [calendar.month_name[month][:1] for month in range(1, 13)]

        user = self.request.user
        filt = periode_filter_context(self.request, user, reset_url_name='stock')
        localite = filt['localite_active']
        pieces = Piece.objects.filter(
            date_creation__range=[filt['date_debut'], filt['date_fin']]
        ).order_by('-date_creation')
        if localite:
            pieces = pieces.filter(stocks__local_entrepot=localite).distinct()
        context = {
            'labels': label,
            'annee': annee,
            'dates': dates,
            'pieces': pieces,
            'filter_modal_id': 'piecesFilterModal',
        }
        context.update(filt)
        return context

def piece_create(request):
    localite = get_user_localite(request.user)
    piece_qs = Piece.objects.all()
    if localite:
        piece_qs = piece_qs.filter(stocks__local_entrepot=localite).distinct()
    listpiece = piece_qs
    nbpiece = piece_qs.count()
    nbtypealto = piece_qs.filter(categorie__categorie='ALTO',).count()
    nbtypedzir = piece_qs.filter(categorie__categorie='DZIRE',).count()
    nbtypespre = piece_qs.filter(categorie__categorie='SWIFT',).count()

    inventaire = piece_qs.aggregate(total_value=Sum(F('prix_unitaire') * F('quantite')))['total_value'] or 0
    qtalto = piece_qs.filter(categorie__categorie='ALTO',).aggregate(total_value=Sum(F('quantite')))['total_value'] or 0
    qtdzir = piece_qs.filter(categorie__categorie='DZIRE',).aggregate(total_value=Sum(F('quantite')))['total_value'] or 0
    qtspre = piece_qs.filter(categorie__categorie='SWIFT',).aggregate(total_value=Sum(F('quantite')))['total_value'] or 0
    qtepiece = piece_qs.aggregate(total_value=Sum(F('quantite')))['total_value'] or 0
    print('')
    top_pieces_qs = PanierItem.objects.filter(panier__valide=True, panier__panier_paye=True,)
    if localite:
        top_pieces_qs = top_pieces_qs.filter(panier__local_entrepot=localite)
    top_pieces = (top_pieces_qs.values('piece__designation', 'piece__categorie__categorie').annotate(total_commandes=Count('id'), total_somme=Sum(ExpressionWrapper(F('piece__prix_unitaire') * F('quantite'), output_field=DecimalField()))).order_by('-total_commandes')[:5])
    # print(top_pieces,'**********',qtepiece,'**********', inventaire)
    print('')
    if request.method == 'POST':
        form = PieceForm(request.POST)
        if form.is_valid():
            numero_piece = form.cleaned_data['numero_piece']
            categorie = form.cleaned_data['categorie']
            quantite = form.cleaned_data['quantite']
            try:
                piece = Piece.objects.get(numero_piece=numero_piece,categorie=categorie)
                piece.quantite_disponible += quantite
                piece.save()
                messages.success(request, f"La quantité de la pièce {numero_piece} a été mise à jour.")
            except Piece.DoesNotExist:
                piece = form.save(commit=False)
                piece.utilisateur = request.user
                piece.save()
                messages.success(request, f"La pièce {numero_piece} a été ajoutée.")
            return redirect('nouvelle_piece')
    else:
        form = PieceForm()

    context = {
        "form": form,
        "listpiece": listpiece,
        "qtalto": qtalto,
        "qtdzir": qtdzir,
        "qtspre": qtspre,
        "qtepiece": qtepiece,
        "nbtypealto":nbtypealto,
        "nbtypedzir":nbtypedzir,
        "nbtypespre":nbtypespre,
        "top_pieces":top_pieces,
        "nbpiece": nbpiece,
        "inventaire": inventaire,
    }
    return render(request, 'perfect/add_piece.html', context)

class EntreSockPieceView(LoginRequiredMixin, CreateView):
    login_url = 'connexion'
    model = Piece
    form_class = EntrePieceForm
    template_name = 'mag/stock.html'
    success_message = 'Pièce mis à jour avec succès✓✓'
    error_message = "Erreur de saisie ✘✘"
    
    def form_valid(self, form):
        form.instance.piece = get_object_or_404(Piece, pk=self.kwargs['pk'])
        form.instance.utilisateur = self.request.user
        loc = get_user_localite(self.request.user)
        if not loc:
            messages.error(self.request, "Localité requise pour enregistrer une entrée en stock.")
            return redirect(self.request.META.get('HTTP_REFERER', 'stock'))
        form.instance.local_entrepot = loc
        reponse = super().form_valid(form)
        messages.success(self.request, self.success_message)
        return reponse
    
    def form_invalid(self, form):
        # Afficher les erreurs de validation dans les messages
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(self.request, f"{field}: {error}")
        messages.error(self.request, self.error_message)
        # Rediriger vers la page précédente (HTTP_REFERER) ou stock par défaut
        referer = self.request.META.get('HTTP_REFERER')
        if referer:
            return redirect(referer)
        return redirect('stock')
    
    def get_success_url(self):
        referer = self.request.META.get('HTTP_REFERER')
        if referer:
            return referer
        return append_query_string(reverse('stock'), self.request)
    
def deletentrestock(request, pk):
    try:
        entrepiece = get_object_or_404(EntrePiece, id=pk)
        entrepiece.delete()
        messages.success(request, f"L'entrée en stock de {entrepiece} faite le {entrepiece.date} a été supprimés avec succès.")
    except Exception as e:
        messages.error(request, f"Erreur lors de la suppression : {str(e)}")
    return redirect('stock')

class UpdatepieceView(LoginRequiredMixin, UpdateView):
    login_url = 'connexion'
    model = Piece
    form_class = UpdatePieceForm
    template_name = 'mag/stock.html'
    success_message = 'La pièce a été mise à jour.👍✓✓'
    error_message = "Erreur de saisie verifié les informations ✘✘"
    def form_valid(self, form):
        form.save()
        messages.success(self.request, self.success_message)
        # Rediriger vers la page d'origine (HTTP_REFERER) ou vers stock par défaut
        return redirect(self.request.META.get('HTTP_REFERER', 'stock'))
    
    def form_invalid(self, form):
        # Afficher les erreurs de validation dans les messages
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(self.request, f"{field}: {error}")
        messages.error(self.request, self.error_message)
        # Rediriger vers la page d'origine (HTTP_REFERER) ou vers stock par défaut
        return redirect(self.request.META.get('HTTP_REFERER', 'stock'))
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        piecs = self.get_object()
        localite = get_user_localite(self.request.user)
        pieces = Piece.objects.all()
        if localite:
            pieces = pieces.filter(stocks__local_entrepot=localite).distinct()
        labels = [calendar.month_name[month][:2] for month in range(1, 13)]
        mois_en_cours=date.today().month
        libelle_mois_en_cours = calendar.month_name[mois_en_cours]
        # form = self.form_class(self.request.GET)
        form = self.get_form()
        def _pi_base(**extra):
            qs = PanierItem.objects.filter(
                panier__valide=True,
                piece=piecs,
                panier__panier_paye=True,
                **extra,
            )
            if localite:
                qs = qs.filter(panier__local_entrepot=localite)
            return qs
        nb_vente_mens = _pi_base(
                                            date_creation__year=date.today().year,
                                            date_creation__month=date.today().month
                                            ).aggregate(total=Sum('quantite'))['total'] or 0
        vente_mens = _pi_base(
                                            date_creation__year=date.today().year,
                                            date_creation__month=date.today().month
                                            ).aggregate(total=Sum(F('quantite') * F('piece__prix_unitaire')))['total'] or 0
        nb_vente_day = _pi_base(
                                            date_creation=date.today()
                                            ).aggregate(total=Sum('quantite'))['total'] or 0
        vente_day = _pi_base(
                date_creation=date.today()
            ).aggregate(total=Sum(F('quantite') * F('piece__prix_unitaire')))['total']
        #--------------------------------------Graphs--------------------------------#
        nb_piec = _pi_base(
                                            date_creation__year=datetime.now().year
                                            )
        revenue_mens_swi = {month: 0 for month in range(1, 13)}
        for commande in nb_piec:
            revenue_mens_swi[commande.date_creation.month] += commande.quantite
        nb_piec_data = [revenue_mens_swi[month] for month in range(1, 13)]
        #--------------------------------------Graphs2222222--------------------------------#
        # val_ventes_alto_mensu = Commande.objects.filter(paye=True, date_creation__year=date.today().year).aggregate(total=Sum('total'))['total'] or 0
        vent_piec = _pi_base(
                                                        date_creation__year=datetime.now().year
                                                        )
        revenue_mens_alto = {month: 0 for month in range(1, 13)}
        for commande in vent_piec:
            revenue_mens_alto[commande.date_creation.month] += commande.quantite * commande.piece.prix_unitaire
        vent_piec_data = [float(revenue_mens_alto[month]) for month in range(1, 13)]
        context.update({
            'pieces':pieces,
            'nb_piec_data':nb_piec_data,
            'vent_piec_data':vent_piec_data,
            'vente_day':vente_day,
            'nb_vente_day':nb_vente_day,
            'libelle_mois_en_cours':libelle_mois_en_cours,
            'nb_vente_mens':nb_vente_mens,
            'vente_mens':vente_mens,
            'labels':labels,
            'form':form,
            'piecs':piecs,
        })
        return context

class DetailpieceView(DetailView):
    model = Piece
    form_class = DateForm
    login_url = 'connexion'
    template_name = 'perfect/piece_detail.html'
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        localite = get_user_localite(self.request.user)
        pieces = Piece.objects.all()
        if localite:
            pieces = pieces.filter(stocks__local_entrepot=localite).distinct()
        piecs = self.get_object()
        labels = [calendar.month_name[month][:2] for month in range(1, 13)]
        mois_en_cours=date.today().month
        libelle_mois_en_cours = calendar.month_name[mois_en_cours]
        form = self.form_class(self.request.GET)
        def _pi_base(**extra):
            qs = PanierItem.objects.filter(
                panier__valide=True,
                piece=piecs,
                panier__panier_paye=True,
                **extra,
            )
            if localite:
                qs = qs.filter(panier__local_entrepot=localite)
            return qs
        if form.is_valid():
            date_debut = form.cleaned_data['date_debut']
            date_fin = form.cleaned_data['date_fin']
            nb_vente_mens = _pi_base(
                date_creation__range=[date_debut, date_fin],
                ).aggregate(total=Sum('quantite'))['total'] or 0
            vente_mens = _pi_base(
                date_creation__range=[date_debut, date_fin],
                ).aggregate(total=Sum(F('quantite') * F('piece__prix_unitaire')))['total'] or 0
            nb_vente_day = _pi_base(
                date_creation=date.today()
                ).aggregate(total=Sum('quantite'))['total'] or 0
            vente_day = _pi_base(
                    date_creation=date.today()
                ).aggregate(total=Sum(F('quantite') * F('piece__prix_unitaire')))['total']
            #--------------------------------------Graphs--------------------------------#
            nb_piec = _pi_base(
                date_creation__range=[date_debut, date_fin],
                )
            revenue_mens_swi = {month: 0 for month in range(1, 13)}
            for commande in nb_piec:
                revenue_mens_swi[commande.date_creation.month] += commande.quantite
            nb_piec_data = [revenue_mens_swi[month] for month in range(1, 13)]

            #--------------------------------------Graphs2222222--------------------------------#
            # val_ventes_alto_mensu = Commande.objects.filter(paye=True, date_creation__year=date.today().year).aggregate(total=Sum('total'))['total'] or 0
            vent_piec = _pi_base(
                                                            date_creation__range=[date_debut, date_fin],
                                                            )
            revenue_mens_alto = {month: 0 for month in range(1, 13)}
            for commande in vent_piec:
                revenue_mens_alto[commande.date_creation.month] += commande.quantite * commande.piece.prix_unitaire
            vent_piec_data = [float(revenue_mens_alto[month]) for month in range(1, 13)]
        else:
            nb_vente_mens = _pi_base(
                date_creation__year=date.today().year,
                date_creation__month=date.today().month
                ).aggregate(total=Sum('quantite'))['total'] or 0

            vente_mens = _pi_base(
                date_creation__year=date.today().year,
                date_creation__month=date.today().month
                ).aggregate(total=Sum(F('quantite') * F('piece__prix_unitaire')))['total'] or 0

            nb_vente_day = _pi_base(
                date_creation=date.today()
                ).aggregate(total=Sum('quantite'))['total'] or 0

            vente_day = _pi_base(
                    date_creation=date.today()
                ).aggregate(total=Sum(F('quantite') * F('piece__prix_unitaire')))['total']
            #--------------------------------------Graphs--------------------------------#
            nb_piec = _pi_base(
                                                date_creation__year=datetime.now().year
                                                )
            revenue_mens_swi = {month: 0 for month in range(1, 13)}
            for commande in nb_piec:
                revenue_mens_swi[commande.date_creation.month] += commande.quantite
            nb_piec_data = [revenue_mens_swi[month] for month in range(1, 13)]

            #--------------------------------------Graphs2222222--------------------------------#
            vent_piec = _pi_base(
                date_creation__year=datetime.now().year
                )
            revenue_mens_alto = {month: 0 for month in range(1, 13)}
            for commande in vent_piec:
                revenue_mens_alto[commande.date_creation.month] += commande.quantite * commande.piece.prix_unitaire
            vent_piec_data = [float(revenue_mens_alto[month]) for month in range(1, 13)]
        context.update({
            'pieces':pieces,
            'nb_piec_data':nb_piec_data,
            'vent_piec_data':vent_piec_data,
            'vente_day':vente_day,
            'nb_vente_day':nb_vente_day,
            'libelle_mois_en_cours':libelle_mois_en_cours,
            'nb_vente_mens':nb_vente_mens,
            'vente_mens':vente_mens,
            'labels':labels,
            'form':form,
        })
        return context

def piece_delete(request, pk):
    try:
        piece = get_object_or_404(Piece, id=pk)
        piece.delete()
        messages.success(request, f"La pièce {piece.numero_piece} a été supprimée.")
    except Exception as e:
        messages.error(request, f"Erreur lors de la suppression : {str(e)}")
    return redirect(request.META.get('HTTP_REFERER', 'nouvelle_piece'))

class ListPiec_moisView(ListView):
    login_url = 'connexion'
    model = Piece
    template_name = 'perfect/liste_visites.html'
    timeout_minutes = 500
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dates =date.today()
        annee =date.today().year
        mois =date.today().month
        
        libelle_mois= calendar.month_name[mois]
        forms = DateForm(self.request.GET)
        if forms.is_valid():
            date_debut = forms.cleaned_data['date_debut'] 
            date_fin = forms.cleaned_data['date_fin']
            print("Date")
        else:
            print("Date")
        context={
            'dates':dates,
            'libelles_mois':libelle_mois,
            'annees':annee,
            'form':forms,
            }
        return context


class VenteView(TemplateView):
    login_url = 'connexion'
    template_name = "mag/table_vente.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        data = build_mes_ventes_data(self.request)
        filt = data['filt']
        context.update(filt)
        export_qs = self.request.GET.urlencode()
        export_url = reverse('export_ventes_excel')
        if export_qs:
            export_url = f'{export_url}?{export_qs}'
        context.update({
            'filter_modal_id': 'venteFilterModal',
            'page_export_url': export_url,
            'page_export_title': 'Exporter les ventes en Excel',
            'vente_details': data['vente_details'],
            'current_date': data['today'],
            'period_columns': data['period_columns'],
            'period_table_mode': data['period_table_mode'],
            'days_in_month': [c['label'] for c in data['period_columns']],
            'days_in_month_count': data['n_cols'],
            'month_name': filt['filtre_resume'],
            'year': data['year_ref'],
            'total_cols': data['total_cols'],
            'sum_vent_jour': data['sum_vent_jour'],
            'sum_cout_jour': data['sum_cout_jour'],
            'sum_vent_mois': data['sum_vent_mois'],
            'sum_cout_mois': data['sum_cout_mois'],
            'sum_vent_an': data['sum_vent_an'],
            'sum_cout_an': data['sum_cout_an'],
            'daily_totals': data['daily_totals'],
            'daily_costs': data['daily_costs'],
        })
        return context


@login_required(login_url='connexion')
def export_ventes_excel(request):
    """Exporte MES VENTES selon le filtre de période actif (défaut = mois en cours)."""
    data = build_mes_ventes_data(request)
    filt = data['filt']
    period_columns = data['period_columns']
    vente_details = data['vente_details']

    headers = ['N°#', 'Pièce', 'N° Pièce', 'Catégorie']
    for col in period_columns:
        headers.append(str(col['label']))
    headers.extend([
        'Qté Jour', 'Coût Jour',
        'Qté Période', 'Coût Période',
        'Qté Année', 'Coût Année',
    ])

    data_rows = []
    for idx, vente in enumerate(vente_details, start=1):
        row = [
            idx,
            vente['designation'],
            vente['numero_piece'],
            vente['categorie'],
        ]
        row.extend(vente['daily_actions'])
        row.extend([
            vente['vent_jour'],
            float(vente['cout_jour']),
            vente['vent_mois'],
            float(vente['cout_mois']),
            vente['vent_an'],
            float(vente['cout_an']),
        ])
        data_rows.append(row)

    total_row = ['TOTAL', '', '', '']
    total_row.extend(data['daily_totals'])
    total_row.extend([
        data['sum_vent_jour'],
        float(data['sum_cout_jour']),
        data['sum_vent_mois'],
        float(data['sum_cout_mois']),
        data['sum_vent_an'],
        float(data['sum_cout_an']),
    ])
    data_rows.append(total_row)

    df = pd.DataFrame(data_rows, columns=headers)

    resume = (filt.get('filtre_resume') or 'periode').replace(' ', '_')
    date_debut = data['date_debut']
    date_fin = data['date_fin']
    filename = f"ventes_{resume}_{date_debut}_{date_fin}.xlsx"
    sheet_title = f"{filt.get('filtre_resume', 'Ventes')} {date_debut.year}"[:31]

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    try:
        with pd.ExcelWriter(response, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name=sheet_title, index=False)
            worksheet = writer.sheets[sheet_title]
            try:
                from openpyxl.styles import Font, PatternFill, Alignment

                header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
                header_font = Font(bold=True, color="FFFFFF", size=11)

                for cell in worksheet[1]:
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = Alignment(horizontal="center", vertical="center")

                if data_rows:
                    total_row_num = len(data_rows)
                    total_fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")
                    total_font = Font(bold=True)
                    for cell in worksheet[total_row_num + 1]:
                        cell.fill = total_fill
                        cell.font = total_font
                        cell.alignment = Alignment(horizontal="center", vertical="center")

                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except Exception:
                            pass
                    worksheet.column_dimensions[column_letter].width = min(max_length + 2, 50)
            except ImportError:
                pass
    except Exception as e:
        return HttpResponse(f"Erreur lors de l'export Excel: {str(e)}", status=500)

    return response


class ListPiec_jourView(ListView):
    login_url = 'connexion'
    model = Piece
    template_name = 'perfect/liste_visites.html'
    timeout_minutes = 500
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dates =date.today()
        annee =date.today().year
        mois =date.today().month
        
        libelle_mois= calendar.month_name[mois]
        forms = DateForm(self.request.GET)
        if forms.is_valid():
            date_debut = forms.cleaned_data['date_debut'] 
            date_fin = forms.cleaned_data['date_fin']
            print (date_debut, date_fin)
        else:
            print('')
        context={
            'dates':dates,
            'libelles_mois':libelle_mois,
            'annees':annee,
            'form':forms,
            }
        return context

class List_best_venteView(ListView):
    login_url = 'connexion'
    model = Piece
    template_name = 'perfect/liste_visites.html'
    timeout_minutes = 500

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filt = periode_filter_context(self.request, self.request.user, reset_url_name='topventes')
        context.update(filt)
        context.update({
            'filter_modal_id': 'topVenteFilterModal',
            'dates': date.today(),
            'libelles_mois': filt['filtre_resume'],
            'annees': filt['date_fin'].year,
        })
        return context

def base(request):
    return render(request,'magasin/base.html',)

login_required(login_url='login')
class topBestPiecView(TemplateView):
    login_url = 'connexion'
    template_name = 'mag/best_vente.html'
    form_class = DateForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        filt = periode_filter_context(self.request, user, reset_url_name='topventes')
        date_debut = filt['date_debut']
        date_fin = filt['date_fin']
        localite = filt['localite_active']
        day = date.today()
        annee = date_fin.year
        moislib = calendar.month_name[date_debut.month]

        def vente_qs():
            qs = PanierItem.objects.filter(panier__valide=True, panier__panier_paye=True)
            if localite:
                qs = qs.filter(panier__local_entrepot=localite)
            return qs

        top_vente_day = vente_qs().filter(date_creation=day).values(
            'piece__designation', 'piece__categorie__categorie'
        ).annotate(
            quantite_vendue=Sum('quantite'),
            cout_total=Sum(ExpressionWrapper(
                F('piece__prix_unitaire') * F('quantite'), output_field=DecimalField()))
        ).order_by('-quantite_vendue')[:10]

        top_vente_mens = vente_qs().filter(
            date_creation__range=[date_debut, date_fin]
        ).values('piece__designation', 'piece__categorie__categorie').annotate(
            quantite_vendue=Sum('quantite'),
            cout_total=Sum(ExpressionWrapper(
                F('piece__prix_unitaire') * F('quantite'), output_field=DecimalField()))
        ).order_by('-quantite_vendue')[:10]

        nb_vente_tot = vente_qs().filter(
            date_creation__range=[date_debut, date_fin]
        ).aggregate(total=Sum('quantite'))['total'] or 0
        nb_piece_vendu_day = vente_qs().filter(date_creation=day).aggregate(
            total=Sum('quantite'))['total'] or 0
        vente_day = vente_qs().filter(date_creation=day).aggregate(
            total=Sum(F('quantite') * F('piece__prix_unitaire'), output_field=FloatField()))['total'] or 0
        nb_piece_vendu = nb_vente_tot
        vente_mens = vente_qs().filter(date_creation__range=[date_debut, date_fin]).aggregate(
            total=Sum(F('quantite') * F('piece__prix_unitaire'), output_field=FloatField()))['total'] or 0
        vente_year = vente_qs().filter(date_creation__year=annee).aggregate(
            total=Sum(F('quantite') * F('piece__prix_unitaire'), output_field=FloatField()))['total'] or 0
        nb_piece_vendu_year = vente_qs().filter(date_creation__year=annee).aggregate(
            total=Sum('quantite'))['total'] or 0
        cout_total = vente_qs().filter(date_creation__range=[date_debut, date_fin]).aggregate(
            total_cout=Sum(F('quantite') * F('piece__prix_achat'), output_field=FloatField())
        )['total_cout'] or 0
        benefice_mensuel = vente_mens - cout_total

        context.update(filt)
        context.update({
            'filter_modal_id': 'topVenteFilterModal',
            'day': day,
            'moislib': moislib,
            'annee': annee,
            'top_vente_day': top_vente_day,
            'top_vente_mens': top_vente_mens,
            'nb_vente_tot': nb_vente_tot,
            'nb_piece_vendu': nb_piece_vendu,
            'vente_mens': vente_mens,
            'nb_piece_vendu_year': nb_piece_vendu_year,
            'vente_year': vente_year,
            'nb_piece_vendu_day': nb_piece_vendu_day,
            'vente_day': vente_day,
            'benefice_mensuel': benefice_mensuel,
        })
        context.update(export_urls(self.request, 'export_best_vente_excel', 'export_best_vente_pdf'))
        return context


class BonCommandePaiementListView(LoginRequiredMixin, TemplateView):
    """Liste des bons de commande émis en caisse, filtrés par période (défaut : mois en cours)."""
    login_url = 'connexion'
    template_name = 'mag/bon_cmd_paiement_caisse.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        filt = periode_filter_context(
            self.request, user, reset_url_name='bons_commande_paiement', default='mois',
        )
        date_debut = filt['date_debut']
        date_fin = filt['date_fin']
        localite = filt['localite_active']
        today = date.today()

        qs = (
            BonCommandePaiement.objects.select_related(
                'commande', 'caissier', 'hote_accueil', 'local_entrepot',
            )
            .filter(date_emission__date__range=[date_debut, date_fin])
            .order_by('-date_emission')
        )
        if localite:
            qs = qs.filter(local_entrepot=localite)

        agg = qs.aggregate(
            total_bons=Count('pk'),
            somme_paye=Sum('montant_paye'),
            somme_commande=Sum('total_commande'),
        )

        context.update(filt)
        context.update({
            'filter_modal_id': 'bonCmdPaiementFilterModal',
            'bons_paiement': qs,
            'nb_bons': agg['total_bons'] or 0,
            'nb_bons_jour': qs.filter(date_emission__date=today).count(),
            'total_montant_paye': agg['somme_paye'] or 0,
            'total_commandes': agg['somme_commande'] or 0,
            'today': today,
        })
        return context


login_required(login_url='login')
class PieceRuptureView(TemplateView):
    login_url = 'connexion'
    template_name = 'mag/piece_alerte.html'
    form_class = DateForm
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        localite = get_user_localite(self.request.user)
        alerte_qs = filter_pieces_sous_seuil(Piece.objects.all(), localite)
        piece_alerte = alerte_qs.count()
        liste_piece_alerte = alerte_qs
        context = {
            'piece_alerte': piece_alerte,
            'liste_piece_alerte': liste_piece_alerte,
        }
        return context

class MonStockView(TemplateView):
    login_url = 'connexion'
    template_name = 'mag/stock.html'
    form_class = DateForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        user_group = user.groups.first()
        context['user_group'] = user_group.name if user_group else None
        annee = date.today().year
        moisact = calendar.month_name[date.today().month]

        filt = periode_filter_context(self.request, user, reset_url_name='stock')
        date_debut = filt['date_debut']
        date_fin = filt['date_fin']
        localite = filt['localite_active']
        can_choose = filt['can_choose_localite']

        entre_stock_form = EntrePieceForm()
        edit_piece_form = UpdatePieceForm()
        fournisseurs = Fournisseur.objects.all()
        categories = queryset_categories_avec_sous()

        piece_queryset = filter_piece_catalogue_actif(
            Piece.objects.select_related('categorie', 'sous_categorie', 'utilisateur')
        )
        if localite:
            piece_queryset = piece_queryset.filter(
                stocks__local_entrepot=localite,
                stocks__active_sortie=True,
            ).distinct()
        piece_queryset = piece_queryset.order_by('-date_creation')
        piece_queryset = annotate_pieces_for_localite(piece_queryset, localite)
        piece_queryset = annotate_provenance_derniere_entree(piece_queryset, localite)
        count_piece = sum(getattr(p, 'quantite_disponible', 0) for p in piece_queryset)

        stock_val_qs = StockLocal.objects.all()
        if localite:
            stock_val_qs = stock_val_qs.filter(local_entrepot=localite)
        valeur_piece = stock_val_qs.aggregate(
            total=Sum(
                F('quantite_disponible') * Coalesce(
                    F('prix_unitaire_local'), F('piece__prix_unitaire')
                ),
                output_field=FloatField(),
            )
        )['total'] or 0

        entre_queryset = EntrePiece.objects.filter(date_creation__range=[date_debut, date_fin])
        if localite:
            entre_queryset = entre_queryset.filter(piece__stocks__local_entrepot=localite).distinct()
        total_entre_piece = entre_queryset.aggregate(total=Sum('quantitajout'))['total'] or 0
        valeur_entre_piece = entre_queryset.aggregate(
            total=Sum(F('quantitajout') * F('prix_achat'), output_field=FloatField())
        )['total'] or 0

        vente_qs = PanierItem.objects.filter(
            panier__valide=True,
            panier__panier_paye=True,
            date_creation__range=[date_debut, date_fin],
        )
        if localite:
            vente_qs = vente_qs.filter(panier__local_entrepot=localite)
        nb_piece_vendu = vente_qs.aggregate(total=Sum('quantite'))['total'] or 0
        val_piece_vendu = vente_qs.aggregate(
            total=Sum(F('quantite') * F('piece__prix_unitaire'), output_field=FloatField())
        )['total'] or 0
        cout_total = vente_qs.aggregate(
            total_cout=Sum(F('quantite') * F('piece__prix_achat'), output_field=FloatField())
        )['total_cout'] or 0
        benefice_mensuel = val_piece_vendu - cout_total

        alerte_qs = filter_pieces_sous_seuil(Piece.objects.all(), localite)
        context.update(filt)
        context.update({
            'filter_modal_id': 'stockFilterModal',
            'count_catego': Categorie.objects.count(),
            'piece_queryset': piece_queryset,
            'count_piece': count_piece,
            'valeur_piece': valeur_piece,
            'total_entre_piece': total_entre_piece,
            'valeur_entre_piece': valeur_entre_piece,
            'nb_piece_vendu': nb_piece_vendu,
            'val_piece_vendu': val_piece_vendu,
            'benefice_mensuel': benefice_mensuel,
            'piece_alerte': alerte_qs.count(),
            'liste_piece_alerte': alerte_qs[:10],
            'annee': annee,
            'moisact': moisact,
            'entre_stock_form': entre_stock_form,
            'edit_piece_form': edit_piece_form,
            'fournisseurs': fournisseurs,
            'categories': categories,
            'is_admin_like': can_choose,
            'peut_fixer_prix_local': utilisateur_peut_fixer_prix_local(user) and bool(localite),
            'peut_toggle_sortie_catalogue': utilisateur_peut_toggle_sortie_catalogue(user),
            'peut_toggle_sortie_local': utilisateur_peut_toggle_sortie_local(user) and bool(
                localite or get_user_localite(user)
            ),
        })
        context.update(export_urls(self.request, 'export_stock_excel', 'export_stock_pdf'))
        return context


class PieceArchiveView(TemplateView):
    """Liste des pièces archivées (catalogue ou localité) avec restauration vers le stock actif."""
    login_url = 'connexion'
    template_name = 'mag/piece_archive.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        filt = periode_filter_context(self.request, user, reset_url_name='pieces_archivees')
        localite = filt['localite_active'] or get_user_localite(user)

        piece_queryset = filter_pieces_archivees(Piece.objects.all(), localite)
        piece_queryset = piece_queryset.select_related('categorie', 'sous_categorie').order_by('-date_creation')
        piece_queryset = annotate_pieces_for_localite(piece_queryset, localite)
        piece_queryset = annotate_archive_info(piece_queryset, localite)

        context.update(filt)
        context.update({
            'filter_modal_id': 'archiveFilterModal',
            'piece_queryset': piece_queryset,
            'count_archive': piece_queryset.count(),
        })
        return context


@login_required(login_url='connexion')
@require_POST
def ajax_definir_prix_local(request, pk):
    """Fixe le prix de vente local (StockLocal.prix_unitaire_local) pour la localité active."""
    if not utilisateur_peut_fixer_prix_local(request.user):
        return JsonResponse({'success': False, 'error': 'Action non autorisée.'}, status=403)

    filt = periode_filter_context(request, request.user, reset_url_name='stock')
    localite = filt.get('localite_active') or get_user_localite(request.user)
    if not localite:
        return JsonResponse({
            'success': False,
            'error': 'Sélectionnez une localité pour définir le prix.',
        }, status=400)

    user_local = get_user_localite(request.user)
    if user_local is not None and localite.pk != user_local.pk:
        return JsonResponse({'success': False, 'error': 'Localité non autorisée.'}, status=403)

    piece = get_object_or_404(Piece, pk=pk)
    form = StockLocalPrixForm(request.POST)
    if not form.is_valid():
        err = next(iter(form.errors.values()), ['Données invalides.'])[0]
        return JsonResponse({'success': False, 'error': err}, status=400)

    prix = form.cleaned_data.get('prix_unitaire_local')
    if request.POST.get('prix_unitaire_local', '').strip() == '':
        prix = None

    from .stock_local_service import get_or_create_stock
    stock = get_or_create_stock(piece, localite)
    stock.prix_unitaire_local = prix
    stock.save(update_fields=['prix_unitaire_local', 'date_maj'])

    prix_affiche = get_prix_unitaire(piece, localite)
    msg = (
        f'Prix local enregistré : {prix_affiche} Fcfa.'
        if prix is not None
        else f'Prix catalogue appliqué : {prix_affiche} Fcfa.'
    )
    return JsonResponse({
        'success': True,
        'message': msg,
        'prix_affiche': str(prix_affiche),
        'prix_catalogue': str(piece.prix_unitaire),
    })


def piec_delete(request, pk):
    try:
        piece = get_object_or_404(Piece, id=pk)
        piece.delete()
        qty = get_quantite(piece, get_user_localite(request.user))
        messages.success(request, f"la pièce {piece.designation} - stock {qty} - {piece.prix_unitaire} Fcfa supprimée avec succès.")
    except Exception as e:
        messages.error(request, f"Erreur lors de la suppression : {str(e)}")
    return redirect('stock')

@login_required(login_url='connexion')
def activate_sortie(request, pk):
    """Active la pièce au niveau catalogue (toutes localités)."""
    if not utilisateur_peut_toggle_sortie_catalogue(request.user):
        messages.error(request, "Action non autorisée.")
        return redirect(request.META.get('HTTP_REFERER', 'stock'))
    try:
        piece = get_object_or_404(Piece, id=pk)
        piece.active_sortie = True
        piece.archive_par = None
        piece.archive_le = None
        piece.archive_motif = ''
        piece.save(update_fields=['active_sortie', 'archive_par', 'archive_le', 'archive_motif'])
        messages.success(request, f"La pièce {piece.numero_piece} - {piece.designation} a été réactivée au catalogue.")
        return redirect('stock')
    except Exception as e:
        messages.error(request, f"Erreur lors de l'activation : {str(e)}")
    return redirect(request.META.get('HTTP_REFERER', 'stock'))

@login_required(login_url='connexion')
@require_POST
def deactivate_sortie(request, pk):
    """Archive la pièce au niveau catalogue (toutes localités)."""
    if not utilisateur_peut_toggle_sortie_catalogue(request.user):
        messages.error(request, "Action non autorisée.")
        return redirect(request.META.get('HTTP_REFERER', 'stock'))
    motif = (request.POST.get('archive_motif') or '').strip()
    if not motif:
        messages.error(request, "Le motif d'archivage est obligatoire.")
        return redirect(request.META.get('HTTP_REFERER', 'stock'))
    try:
        piece = get_object_or_404(Piece, id=pk)
        piece.active_sortie = False
        piece.archive_par = request.user
        piece.archive_le = timezone.now()
        piece.archive_motif = motif
        piece.save(update_fields=['active_sortie', 'archive_par', 'archive_le', 'archive_motif'])
        messages.success(
            request,
            f"La pièce {piece.numero_piece} - {piece.designation} a été archivée du catalogue (toutes localités).",
        )
    except Exception as e:
        messages.error(request, f"Erreur lors de la désactivation : {str(e)}")
    return redirect(request.META.get('HTTP_REFERER', 'stock'))

def _localite_pour_toggle_sortie(request, reset_url_name='stock'):
    """Localité cible pour activer/désactiver la vente locale."""
    filt = periode_filter_context(request, request.user, reset_url_name=reset_url_name)
    localite = filt.get('localite_active') or get_user_localite(request.user)
    return localite


@login_required(login_url='connexion')
def activate_sortie_local(request, pk):
    """Active la vente de la pièce dans la localité de l'utilisateur."""
    if not utilisateur_peut_toggle_sortie_local(request.user):
        messages.error(request, "Action non autorisée.")
        return redirect(request.META.get('HTTP_REFERER', 'stock'))
    localite = _localite_pour_toggle_sortie(request)
    if not localite:
        messages.error(request, "Aucune localité sélectionnée.")
        return redirect(request.META.get('HTTP_REFERER', 'stock'))
    user_local = get_user_localite(request.user)
    if user_local is not None and localite.pk != user_local.pk:
        messages.error(request, "Localité non autorisée.")
        return redirect(request.META.get('HTTP_REFERER', 'stock'))
    try:
        piece = get_object_or_404(Piece, pk=pk)
        if not piece.active_sortie:
            messages.warning(request, "La pièce est archivée au catalogue ; réactivez-la d'abord (gestionnaire).")
            return redirect(request.META.get('HTTP_REFERER', 'stock'))
        stock = get_or_create_stock(piece, localite)
        stock.active_sortie = True
        stock.archive_par = None
        stock.archive_le = None
        stock.archive_motif = ''
        stock.save(update_fields=['active_sortie', 'archive_par', 'archive_le', 'archive_motif', 'date_maj'])
        messages.success(
            request,
            f"La pièce {piece.numero_piece} est de nouveau en vente à {localite.nom}.",
        )
        return redirect('stock')
    except Exception as e:
        messages.error(request, f"Erreur lors de l'activation locale : {str(e)}")
    return redirect(request.META.get('HTTP_REFERER', 'stock'))


@login_required(login_url='connexion')
@require_POST
def deactivate_sortie_local(request, pk):
    """Masque la pièce à la vente dans la localité de l'utilisateur."""
    if not utilisateur_peut_toggle_sortie_local(request.user):
        messages.error(request, "Action non autorisée.")
        return redirect(request.META.get('HTTP_REFERER', 'stock'))
    motif = (request.POST.get('archive_motif') or '').strip()
    if not motif:
        messages.error(request, "Le motif d'archivage est obligatoire.")
        return redirect(request.META.get('HTTP_REFERER', 'stock'))
    localite = _localite_pour_toggle_sortie(request)
    if not localite:
        messages.error(request, "Aucune localité sélectionnée.")
        return redirect(request.META.get('HTTP_REFERER', 'stock'))
    user_local = get_user_localite(request.user)
    if user_local is not None and localite.pk != user_local.pk:
        messages.error(request, "Localité non autorisée.")
        return redirect(request.META.get('HTTP_REFERER', 'stock'))
    try:
        piece = get_object_or_404(Piece, pk=pk)
        stock = get_or_create_stock(piece, localite)
        stock.active_sortie = False
        stock.archive_par = request.user
        stock.archive_le = timezone.now()
        stock.archive_motif = motif
        stock.save(update_fields=['active_sortie', 'archive_par', 'archive_le', 'archive_motif', 'date_maj'])
        messages.success(
            request,
            f"La pièce {piece.numero_piece} n'est plus en vente à {localite.nom}.",
        )
    except Exception as e:
        messages.error(request, f"Erreur lors de la désactivation locale : {str(e)}")
    return redirect(request.META.get('HTTP_REFERER', 'stock'))

def piec_delete(request, pk):
    try:
        piece = get_object_or_404(Piece, id=pk)
        piece.delete()
        qty = get_quantite(piece, get_user_localite(request.user))
        messages.success(request, f"la pièce {piece.designation} - stock {qty} - {piece.prix_unitaire} Fcfa supprimée avec succès.")
    except Exception as e:
        messages.error(request, f"Erreur lors de la suppression : {str(e)}")
    return redirect('piece_delete')

def piece_detail(request, pk):
    piece = get_object_or_404(Piece, pk=pk)
    return render(request, 'piece_detail.html', {'piece': piece})

class AddfournisseurView(CreateView):
    login_url = 'connexion'
    model = Fournisseur
    form_class = FournisseurForm
    template_name = 'mag/add_fournisseur.html'
    success_message = 'Fournisseur enregistré avec succès👍✓✓'
    error_message = "Erreur de saisie ✘✘ "
    success_url = reverse_lazy ('nouveau_fournisseur')
    
    def form_valid(self, form):
        reponse = super().form_valid(form)
        messages.success(self.request, self.success_message)
        return reponse
    
    def form_invalid(self, form):
        reponse = super().form_invalid(form)
        messages.error(self.request, self.error_message)
        return reponse
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        filt = periode_filter_context(self.request, user, reset_url_name='nouveau_fournisseur')
        date_debut = filt['date_debut']
        date_fin = filt['date_fin']
        annee = date_fin.year
        moisact = calendar.month_name[date_debut.month] if date_debut.month == date_fin.month else filt['filtre_resume']

        fourn_list = Fournisseur.objects.all()
        all_categories = Categorie.objects.all().order_by('categorie')
        categories_list = [cat.categorie for cat in all_categories]

        entrees_mois = EntrePiece.objects.filter(
            date_creation__range=[date_debut, date_fin]
        )
        
        total_entre_piece = entrees_mois.aggregate(
            total=Sum('quantitajout')
        )['total'] or 0
        
        valeur_entre_piece = entrees_mois.aggregate(
            total=Sum(F('quantitajout') * F('prix_achat'), output_field=FloatField())
        )['total'] or 0
        
        entrees_annee = EntrePiece.objects.filter(
            date_creation__range=[date(date_fin.year, 1, 1), date_fin]
        )
        count_piece = entrees_annee.aggregate(
            total=Sum('quantitajout')
        )['total'] or 0
        
        valeur_piece = entrees_annee.aggregate(
            total=Sum(F('quantitajout') * F('prix_achat'), output_field=FloatField())
        )['total'] or 0
        
        # Pour chaque fournisseur, calculer les stats par catégorie pour le mois en cours
        fourniss_data = []
        for fournisseur in fourn_list:
            entrees_fourn_mois = entrees_mois.filter(fournisseur=fournisseur)
            
            # Total quantité et valeur pour ce fournisseur ce mois
            quant_piec = entrees_fourn_mois.aggregate(
                total=Sum('quantitajout')
            )['total'] or 0
            
            val_piec = entrees_fourn_mois.aggregate(
                total=Sum(F('quantitajout') * F('prix_achat'), output_field=FloatField())
            )['total'] or 0
            
            # Stats par catégorie pour ce fournisseur ce mois
            cat_stats = {}
            for cat in all_categories:
                entrees_cat = entrees_fourn_mois.filter(piece__categorie=cat)
                qte_cat = entrees_cat.aggregate(
                    total=Sum('quantitajout')
                )['total'] or 0
                val_cat = entrees_cat.aggregate(
                    total=Sum(F('quantitajout') * F('prix_achat'), output_field=FloatField())
                )['total'] or 0
                cat_stats[cat.categorie] = {
                    'qte': qte_cat,
                    'valeur': val_cat
                }
            
            fourniss_data.append({
                'f': fournisseur,
                'quant_piec': quant_piec,
                'val_piec': val_piec,
                'categories_dict': cat_stats,
            })
        
        # Formulaires pour les modals
        form = self.get_form()
        edit_form = FournisseurForm()
        
        # Nombre de colonnes pour le colspan (5 colonnes fixes + nombre de catégories)
        total_cols = len(categories_list) + 5
        
        context.update(filt)
        context.update({
            'filter_modal_id': 'fournisseurFilterModal',
            'fourn_list': fourn_list,
            'fourniss_data': fourniss_data,
            'all_categories': categories_list,
            'form': form,
            'edit_form': edit_form,
            'total_entre_piece': total_entre_piece,
            'valeur_entre_piece': valeur_entre_piece,
            'count_piece': count_piece,
            'valeur_piece': valeur_piece,
            'nb_piece_vendu': total_entre_piece,
            'val_piece_vendu': valeur_entre_piece,
            'moisact': moisact,
            'annee': annee,
            'total_cols': total_cols,
        })
        return context

class UpdatefournisseurView(UpdateView):
    model = Fournisseur
    form_class = FournisseurForm
    success_message = 'Fournisseur modifié avec succès✓✓'
    error_message = "Erreur de saisie ✘✘ "
    success_url = reverse_lazy ('nouveau_fournisseur')
    
    def form_valid(self, form):
        reponse = super().form_valid(form)
        messages.success(self.request, self.success_message)
        return reponse
    
    def form_invalid(self, form):
        reponse = super().form_invalid(form)
        messages.error(self.request, self.error_message)
        return redirect('nouveau_fournisseur')
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        forms = self.get_form()
        fourn_list = Fournisseur.objects.all()
        forms = self.get_form()
        f = self.get_object()
        # Pièces de ce fournisseur
        total_alt = Piece.objects.filter(categorie__categorie='ALTO',fournisseur=f, date_creation__month=date.today().month).aggregate(total=Sum('quantite'))['total'] or 0
        total_dzi = Piece.objects.filter(categorie__categorie='DZIRE',fournisseur=f, date_creation__month=date.today().month).aggregate(total=Sum('quantite'))['total'] or 0
        total_swi = Piece.objects.filter(categorie__categorie='SWIFT',fournisseur=f, date_creation__month=date.today().month).aggregate(total=Sum('quantite'))['total'] or 0
        print('')
        print('')
        print('')
        total_pieces = Piece.objects.filter(fournisseur=f, date_creation__month=date.today().month).aggregate(total=Sum('quantite'))['total'] or 0
        val_piecs = Piece.objects.filter(fournisseur=f, date_creation__month=date.today().month).aggregate(total_value=Sum(ExpressionWrapper(F('prix_unitaire') * F('quantite'), output_field=DecimalField())))['total_value'] or 0
        val_alt = Piece.objects.filter(categorie__categorie='ALTO',fournisseur=f, date_creation__month=date.today().month).aggregate(total_value=Sum(ExpressionWrapper(F('prix_unitaire') * F('quantite'), output_field=DecimalField())))['total_value'] or 0
        val_dzi = Piece.objects.filter(categorie__categorie='DZIRE',fournisseur=f, date_creation__month=date.today().month).aggregate(total_value=Sum(ExpressionWrapper(F('prix_unitaire') * F('quantite'), output_field=DecimalField())))['total_value'] or 0
        val_swi = Piece.objects.filter(categorie__categorie='SWIFT',fournisseur=f, date_creation__month=date.today().month).aggregate(total_value=Sum(ExpressionWrapper(F('prix_unitaire') * F('quantite'), output_field=DecimalField())))['total_value'] or 0

        print('')
        print(val_piecs,total_pieces,'##########',)
        print('')
        pieces = Piece.objects.filter(fournisseur=f)

        quant_piec = pieces.aggregate(total=Sum('quantite'))['total'] or 0
        val_piec = pieces.aggregate(total=Sum(F('quantite') * F('prix_unitaire')))['total'] or 0

        # Statistiques par catégorie
        cat_stats = defaultdict(lambda: {'qte': 0, 'valeur': 0})
        all_categories = set()

        for p in pieces:
            cat_label = p.categorie.categorie
            all_categories.add(cat_label)
            cat_stats[cat_label]['qte'] += p.quantite
            cat_stats[cat_label]['valeur'] += p.quantite * float(p.prix_unitaire)

        # Préparer les données à afficher dans le tableau
        fourniss_data = [{
            'f': f,
            'quant_piec': quant_piec,
            'val_piec': val_piec,
            'categories_dict': cat_stats,
        }]
        context.update({
            'total_alt': total_alt,
            'total_dzi': total_dzi,
            'total_swi': total_swi,

            'val_alt': val_alt,
            'val_dzi': val_dzi,
            'val_swi': val_swi,

            'val_piecs':val_piecs,
            'total_pieces':total_pieces,

            'fourn_list': fourn_list,
            'forms': forms,
            'fourns': f,
            
            'fourniss_data': fourniss_data,
            'all_categories': sorted(list(all_categories)),
        })

        return context

def fourn_delete(request, pk):
    try:
        fourn = get_object_or_404(Fournisseur, id=pk)
        fourn.delete()
        messages.success(request, f"Le fournisseur {fourn.nom} {fourn.contact} a été supprimée.")
    except Exception as e:
        messages.error(request, f"Erreur lors de la suppression : {str(e)}")
    return redirect('nouveau_fournisseur')

def valider_livraison(request, ticket_id):
    try:
        ticket = get_object_or_404(Ticket, numero=ticket_id, utilise=True)
        localite = get_user_localite(request.user)
        qs = Panier.objects.filter(ticket=ticket.numero)
        if localite:
            qs = qs.filter(local_entrepot=localite)
        panier_non_livre = qs.first()
        
        if panier_non_livre:
            panier_non_livre.panier_livre = True
            panier_non_livre.date_livr_panier = timezone.now().date()
            panier_non_livre.save()
            messages.success(request, "Livraison effectuée avec succès.")
        else:
            messages.error(request, "Aucun panier trouvé pour ce ticket.")
    except Exception as e:
        messages.error(request, f"Erreur lors de la validation de la livraison : {str(e)}")
    return redirect(request.META.get('HTTP_REFERER', 'livraisons'))

login_required(login_url='login')
class LivraisonView(TemplateView):
    template_name = 'mag/livraison.html'
    form_class = DateForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        filt = periode_filter_context(self.request, user, reset_url_name='livraisons')
        date_debut = filt['date_debut']
        date_fin = filt['date_fin']
        localite = filt['localite_active']
        today = date.today()
        mois = calendar.month_name[today.month]

        base_period = Panier.objects.filter(
            valide=True,
            panier_paye=True,
            commande_en_ligne=False,
            date_creation__range=[date_debut, date_fin],
        )
        if localite:
            base_period = base_period.filter(local_entrepot=localite)

        liste_panier = base_period.filter(panier_livre=False).order_by('-date_creation')
        tot_panier = base_period.count()
        tot_en_at = base_period.filter(panier_livre=False).count()
        tot_panier_day = base_period.filter(date_creation=today).count()

        livre_period = Panier.objects.filter(
            valide=True,
            panier_paye=True,
            commande_en_ligne=False,
            panier_livre=True,
            date_livr_panier__range=[date_debut, date_fin],
        )
        if localite:
            livre_period = livre_period.filter(local_entrepot=localite)
        tot_mens_livre = livre_period.count()
        tot_livre = livre_period.filter(date_livr_panier=today).count()

        context.update(filt)
        context.update({
            'filter_modal_id': 'livraisonFilterModal',
            'liste_panier': liste_panier,
            'tot_en_at': tot_en_at,
            'tot_panier_day': tot_panier_day,
            'tot_panier': tot_panier,
            'tot_livre': tot_livre,
            'tot_mens_livre': tot_mens_livre,
            'mois': mois,
            'Date': today,
        })
        context.update(export_urls(self.request, 'export_livraisons_excel', 'export_livraisons_pdf'))
        return context

def global_history_view(request):
    filt = periode_filter_context(
        request, request.user, reset_url_name='global_history', default='mois',
    )
    date_debut = filt['date_debut']
    date_fin = filt['date_fin']
    history_diff = []
    models = [Panier, PanierItem, Piece, Commande, Ticket]

    for model in models:
        model_history = model.history.filter(
            history_date__date__range=[date_debut, date_fin],
        )
        for record in model_history:
            if record.prev_record:
                diff = record.diff_against(record.prev_record)
                history_diff.append({
                    'record': record,
                    'model': model.__name__,
                    'changed_fields': diff.changed_fields,
                })
            else:
                history_diff.append({
                    'record': record,
                    'model': model.__name__,
                    'changed_fields': None,
                })
    context = {
        'global_history': history_diff,
        'filter_date': date_debut,
        'current_user': request.user,
        'filter_modal_id': 'histGenFilterModal',
        'annee': date_fin.year,
    }
    context.update(filt)
    context.update(export_urls(request, 'export_hist_gen_excel', 'export_hist_gen_pdf'))
    return render(request, 'mag/hist_gen.html', context)

@login_required(login_url='connexion')
def historique_commandes(request):
    user = request.user
    filt = periode_filter_context(request, user, reset_url_name='Historique_commande')
    hist_qs = Commande.history.filter(
        history_date__date__range=[filt['date_debut'], filt['date_fin']],
    ).order_by('-history_date')
    localite = filt['localite_active']
    if localite:
        hist_qs = hist_qs.filter(panier__local_entrepot=localite)

    hist_list = list(hist_qs)
    commande_ids = list({h.id for h in hist_list})
    tickets_map = {}
    bons_map = {}
    if commande_ids:
        tickets_map = {
            t.commande_id: t
            for t in Ticket.objects.filter(commande_id__in=commande_ids)
        }
        bons_map = {
            b.commande_id: b
            for b in BonCommandePaiement.objects.filter(commande_id__in=commande_ids)
        }
    historique_rows = [
        {
            'item': item,
            'ticket': tickets_map.get(item.id),
            'bon': bons_map.get(item.id),
        }
        for item in hist_list
    ]

    context = {
        'historique_rows': historique_rows,
        'filter_modal_id': 'histCmdFilterModal',
    }
    context.update(filt)
    context.update(export_urls(request, 'export_hist_cmd_excel', 'export_hist_cmd_pdf'))
    return render(request, 'mag/hist_cmd.html', context)

def historique_panier(request):
    current_year = now().year
    selected_year = int(request.GET.get('annee', current_year))
    historique_paniers = Panier.history.filter(history_date__year=selected_year).order_by('-history_date')
    last_10_years = [current_year - i for i in range(10)][::-1]

    context = {
        'historique_paniers': historique_paniers,
        'selected_year': selected_year,
        'last_10_years': last_10_years,
    }
    return render(request, 'mag/hist_panier.html', context)

def historique_pieces(request):
    user = request.user
    filt = periode_filter_context(request, user, reset_url_name='Historique_pieces')
    historique = Piece.history.filter(
        history_date__date__range=[filt['date_debut'], filt['date_fin']]
    ).order_by('-history_date')
    context = {'historique_pieces': historique, 'filter_modal_id': 'histPieceFilterModal'}
    context.update(filt)
    return render(request, 'mag/hist_piece.html', context)

@login_required(login_url='connexion')
def historique_entrees_piece(request, pk):
    """
    Affiche l'historique des entrées en stock pour une pièce donnée,
    ainsi que les autres pièces de la même catégorie.
    """
    filt = periode_filter_context(
        request, request.user, reset_url_name='info_piece', reset_url_kwargs={'pk': pk},
    )
    date_debut = filt['date_debut']
    date_fin = filt['date_fin']
    localite = filt['localite_active']
    piece = get_object_or_404(Piece, pk=pk)
    # Entrées de stock pour cette pièce
    entrees_piece = (
        EntrePiece.objects
        .filter(piece=piece, date_creation__range=[date_debut, date_fin])
        .select_related('piece', 'utilisateur', 'fournisseur', 'origine_local')
        .order_by('-date_creation')
    )
    if localite:
        entrees_piece = entrees_piece.filter(local_entrepot=localite)
    # Pièces de la même catégorie (pour le menu de gauche)
    pieces_categorie = (
        Piece.objects
        .filter(categorie=piece.categorie)
        .select_related('categorie', 'sous_categorie')
        .order_by('designation')
    )
    # Statistiques simples pour les cartes du haut
    aujourdhui = date.today()
    mois = aujourdhui.month
    annee = aujourdhui.year
    moisact = calendar.month_name[mois]
    total_entre_piece = entrees_piece.aggregate(
        total=Sum('quantitajout')
    )['total'] or 0
    valeur_entre_piece = entrees_piece.aggregate(
        total=Sum(F('quantitajout') * F('prix_achat'), output_field=FloatField())
    )['total'] or 0
    # Ventes de cette pièce
    vente_qs = PanierItem.objects.filter(
        panier__valide=True,
        panier__panier_paye=True,
        piece=piece,
        date_creation__range=[date_debut, date_fin],
    )
    if localite:
        vente_qs = vente_qs.filter(panier__local_entrepot=localite)
    nb_piece_vendu = vente_qs.aggregate(total=Sum('quantite'))['total'] or 0
    val_piece_vendu = vente_qs.aggregate(
        total=Sum(F('quantite') * F('piece__prix_unitaire'), output_field=FloatField())
    )['total'] or 0

    count_piece = get_quantite(piece, localite)
    valeur_piece = count_piece * piece.prix_unitaire

    # Nombre total de pièces pour l'affichage "Mon stock"
    count_medoc = Piece.objects.count()

    context = {
        'piece': piece,
        'entrees_piece': entrees_piece,
        'pieces_categorie': pieces_categorie,
        'count_medoc': count_medoc,
        'total_entre_piece': total_entre_piece,
        'valeur_entre_piece': valeur_entre_piece,
        'nb_piece_vendu': nb_piece_vendu,
        'val_piece_vendu': val_piece_vendu,
        'count_piece': count_piece,
        'valeur_piece': valeur_piece,
        'annee': annee,
        'moisact': moisact,
        'filter_modal_id': 'infoPieceFilterModal',
    }
    context.update(filt)
    context.update(export_urls(
        request, 'export_entrees_piece_excel', 'export_entrees_piece_pdf',
        url_kwargs={'pk': pk},
    ))
    return render(request, 'mag/historiq_entre_piec.html', context)

# ============================================================================
# DEMANDES DE TRANSFERT INTER-LOCALITÉS (chef d'agence)
# ============================================================================

@login_required(login_url='connexion')
def liste_transferts(request):
    user = request.user
    filt = periode_filter_context(request, user, reset_url_name='liste_transferts')
    localite = filt['localite_active'] or get_user_localite(user)
    qs = DemandeTransfert.objects.select_related(
        'local_demandeur', 'local_donneur', 'demandeur', 'validateur_donneur', 'receveur',
    ).prefetch_related('lignes__piece', 'bon_livraison__livreur').filter(
        date_demande__date__range=[filt['date_debut'], filt['date_fin']]
    )
    if localite and not (user.is_superuser or getattr(user, 'role', None) == 'admin'):
        qs = qs.filter(Q(local_demandeur=localite) | Q(local_donneur=localite))
    elif localite:
        qs = qs.filter(Q(local_demandeur=localite) | Q(local_donneur=localite))

    localites_dest = LocalEntrepot.objects.all()
    if localite:
        localites_dest = localites_dest.exclude(pk=localite.pk)

    ctx = {
        'demandes': qs.order_by('-date_demande')[:100],
        'localites_dest': localites_dest,
        'localite_user': localite,
        'is_chef_agence': user_is_chef_agence(user),
        'filter_modal_id': 'transfertsFilterModal',
        'user_local_pk': str(localite.pk) if localite else '',
    }
    ctx.update(filt)
    return render(request, 'mag/transferts.html', ctx)


@login_required(login_url='connexion')
@require_POST
def creer_demande_transfert_view(request):
    from django.core.exceptions import ValidationError as DjangoValidationError
    local_demandeur = get_user_localite(request.user)
    if not local_demandeur:
        messages.error(request, "Aucun entrepôt assigné à votre compte.")
        return redirect('liste_transferts')
    if getattr(request.user, 'role', None) != 'chefagence' and not request.user.is_superuser:
        messages.error(request, "Seul un chef d'agence peut créer une demande.")
        return redirect('liste_transferts')
    try:
        local_donneur = get_object_or_404(LocalEntrepot, pk=request.POST.get('local_donneur'))
        motif = request.POST.get('motif', '')
        lignes = _parse_lignes_post(request.POST)
        demande = creer_demande_transfert(
            request.user, local_demandeur, local_donneur, motif, lignes
        )
        messages.success(request, f"Demande {demande.numero_demande} envoyée à {local_donneur.nom}.")
    except (DjangoValidationError, ValueError) as e:
        messages.error(request, str(e))
    return redirect('liste_transferts')


@login_required(login_url='connexion')
@require_POST
def annuler_demande_demandeur_view(request, demande_id):
    from django.core.exceptions import ValidationError as DjangoValidationError
    demande = get_object_or_404(DemandeTransfert, pk=demande_id)
    try:
        annuler_demande_par_demandeur(demande, request.user)
        messages.success(request, f"Demande {demande.numero_demande} annulée.")
    except DjangoValidationError as e:
        messages.error(request, str(e))
    return redirect('liste_transferts')


@login_required(login_url='connexion')
@require_POST
def valider_demande_donneur_view(request, demande_id):
    from decimal import Decimal, InvalidOperation
    from django.core.exceptions import ValidationError as DjangoValidationError

    demande = get_object_or_404(DemandeTransfert, pk=demande_id)
    try:
        numero_bon = request.POST.get('numero_bon_donneur', '')
        livreur_id = request.POST.get('livreur_id') or None
        raw_ajust = (request.POST.get('cout_ajustement') or '0').strip().replace(',', '.')
        try:
            cout_ajustement = Decimal(raw_ajust) if raw_ajust else Decimal('0')
        except (InvalidOperation, ValueError):
            cout_ajustement = Decimal('0')
        motif_ajust = request.POST.get('motif_ajustement', '')
        observations = request.POST.get('observations_livraison', '')

        demande, bon = valider_demande_par_donneur(
            demande,
            request.user,
            numero_bon,
            livreur_id=livreur_id,
            cout_ajustement=cout_ajustement,
            motif_ajustement=motif_ajust,
            observations_livraison=observations,
        )
        messages.success(
            request,
            f"Demande {demande.numero_demande} validée. "
            f"Bon de livraison {bon.numero_bon_livraison} créé "
            f"(coût : {bon.cout_total:,.0f} F).",
        )
    except DjangoValidationError as e:
        err = e.messages[0] if getattr(e, 'messages', None) else str(e)
        messages.error(request, err)
    return redirect('liste_transferts')


@login_required(login_url='connexion')
@require_POST
def annuler_demande_donneur_view(request, demande_id):
    from django.core.exceptions import ValidationError as DjangoValidationError
    demande = get_object_or_404(DemandeTransfert, pk=demande_id)
    try:
        annuler_demande_par_donneur(demande, request.user)
        messages.success(request, f"Demande {demande.numero_demande} refusée.")
    except DjangoValidationError as e:
        messages.error(request, str(e))
    return redirect('liste_transferts')


@login_required(login_url='connexion')
@require_POST
def recevoir_demande_transfert_view(request, demande_id):
    from django.core.exceptions import ValidationError as DjangoValidationError
    demande = get_object_or_404(DemandeTransfert, pk=demande_id)
    try:
        numero_bon = request.POST.get('numero_bon_commande', '')
        confirmer_reception_demande(demande, request.user, numero_bon)
        messages.success(request, f"Demande {demande.numero_demande} reçue : stocks mis à jour.")
    except DjangoValidationError as e:
        messages.error(request, str(e))
    return redirect('liste_transferts')


@login_required(login_url='connexion')
def ajax_detail_demande_transfert(request, demande_id):
    demande = get_object_or_404(
        DemandeTransfert.objects.prefetch_related('lignes__piece').select_related(
            'local_demandeur', 'local_donneur', 'demandeur', 'validateur_donneur', 'receveur',
            'bon_livraison__livreur', 'bon_livraison__tarif_applique',
        ),
        pk=demande_id,
    )
    if not utilisateur_peut_voir_demande(request.user, demande):
        return JsonResponse({'success': False, 'error': 'Accès refusé.'}, status=403)
    user = request.user
    html = render_to_string(
        'mag/partials/_demande_transfert_detail.html',
        {
            'demande': demande,
            'user': user,
            'user_local_pk': getattr(user.local_entrepot, 'pk', None),
            'est_chef_donneur': utilisateur_est_chef_donneur(user, demande),
            'est_chef_demandeur': utilisateur_est_chef_demandeur(user, demande),
            'peut_gerer_livraison': utilisateur_peut_gerer_livraison_donneur(user, demande),
        },
        request=request,
    )
    return JsonResponse({'success': True, 'html': html})


def _nom_fichier_bon_commande_transfert(demande):
    """Nom de fichier pour téléchargement / enregistrement du PDF."""
    from urllib.parse import quote
    numero = (demande.numero_demande or 'demande').replace('/', '-').replace('\\', '-')
    nom_ascii = f"Bon_de_commande_{numero}.pdf"
    nom_utf8 = f"Bon de commande {demande.numero_demande}.pdf"
    return nom_ascii, quote(nom_utf8)


def _context_imprimer_demande_transfert(demande):
    """Contexte commun pour la fiche imprimable / PDF d'une demande."""
    lignes = list(demande.lignes.select_related('piece').all())
    total_quantite = 0
    total_valeur = Decimal('0')
    for ligne in lignes:
        total_quantite += ligne.quantite
        pu = ligne.piece.prix_unitaire
        ligne.total_ligne = pu * ligne.quantite
        total_valeur += ligne.total_ligne
    min_rows = 8
    empty_rows = range(max(0, min_rows - len(lignes)))
    return {
        'demande': demande,
        'lignes': lignes,
        'total_quantite': total_quantite,
        'total_valeur': total_valeur,
        'empty_rows': empty_rows,
        'auto_print': False,
    }


@login_required(login_url='connexion')
def imprimer_demande_transfert(request, demande_id):
    """Fiche « Bon de commande » imprimable (HTML) ou PDF (?format=pdf)."""
    demande = get_object_or_404(
        DemandeTransfert.objects.select_related(
            'local_demandeur', 'local_donneur', 'demandeur', 'validateur_donneur', 'receveur'
        ),
        pk=demande_id,
    )
    if not utilisateur_peut_voir_demande(request.user, demande):
        messages.error(request, "Accès refusé à cette demande.")
        return redirect('liste_transferts')

    if request.GET.get('format') == 'pdf':
        ctx = _context_imprimer_demande_transfert(demande)
        try:
            pdf_bytes = generate_demande_transfert_pdf(
                demande,
                ctx['lignes'],
                total_quantite=ctx['total_quantite'],
                total_valeur=ctx['total_valeur'],
            )
        except Exception as exc:
            return HttpResponse(f'Erreur PDF : {exc}', status=500)
        nom_ascii, nom_utf8_enc = _nom_fichier_bon_commande_transfert(demande)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'inline; filename="{nom_ascii}"; filename*=UTF-8\'\'{nom_utf8_enc}'
        )
        return response

    context = _context_imprimer_demande_transfert(demande)
    context['auto_print'] = request.GET.get('print') == '1'
    nom_ascii, _ = _nom_fichier_bon_commande_transfert(demande)
    context['pdf_filename'] = nom_ascii
    context['print_title'] = titre_bon_commande(demande)
    html_content = render_to_string('mag/imprimer_demande_transfert.html', context, request=request)
    return HttpResponse(html_content)


@login_required(login_url='connexion')
def ajax_livreurs_localite(request, local_pk):
    """Liste les livreurs actifs d'une localité + coût prévisionnel."""
    from .bon_livraison_service import livreurs_disponibles, calculer_cout_base
    from .models import BonLivraison

    local = get_object_or_404(LocalEntrepot, pk=local_pk)
    if getattr(request.user, 'local_entrepot_id', None) not in (None, local.pk):
        if not (request.user.is_superuser or getattr(request.user, 'role', None) == 'admin'):
            return JsonResponse({'success': False, 'error': 'Accès refusé.'}, status=403)

    livreurs = [
        {
            'pk': u.pk,
            'username': u.username,
            'first_name': u.first_name or '',
            'last_name': u.last_name or '',
        }
        for u in livreurs_disponibles(local)
    ]

    cout_info = None
    demande_id = request.GET.get('demande_id')
    if demande_id:
        try:
            demande = DemandeTransfert.objects.select_related(
                'local_donneur', 'local_demandeur',
            ).get(pk=demande_id)
            distance, cout_base, tarif = calculer_cout_base(
                demande.local_donneur, demande.local_demandeur,
            )
            cout_info = {
                'distance_km': float(distance),
                'tarif_par_km': float(tarif.cout_par_km),
                'cout_base': float(cout_base),
                'tarif_id': tarif.pk,
                'coords_ok': (
                    demande.local_donneur.a_coordonnees
                    and demande.local_demandeur.a_coordonnees
                ),
            }
        except DemandeTransfert.DoesNotExist:
            pass

    return JsonResponse({'success': True, 'livreurs': livreurs, 'cout': cout_info})


def _context_imprimer_bon_livraison(bon):
    demande = bon.demande_transfert
    lignes = list(demande.lignes.select_related('piece').all())
    total_quantite = sum(l.quantite for l in lignes)
    total_valeur = sum(l.piece.prix_unitaire * l.quantite for l in lignes)
    min_rows = 8
    empty_rows = range(max(0, min_rows - len(lignes)))
    return {
        'bon': bon,
        'demande': demande,
        'lignes': lignes,
        'total_quantite': total_quantite,
        'total_valeur_marchandise': total_valeur,
        'empty_rows': empty_rows,
        'auto_print': False,
    }


@login_required(login_url='connexion')
def imprimer_bon_livraison(request, bon_id):
    from .models import BonLivraison

    bon = get_object_or_404(
        BonLivraison.objects.select_related(
            'demande_transfert__local_donneur',
            'demande_transfert__local_demandeur',
            'livreur', 'cree_par', 'tarif_applique',
        ),
        pk=bon_id,
    )
    if not utilisateur_peut_voir_demande(request.user, bon.demande_transfert):
        messages.error(request, 'Accès refusé.')
        return redirect('liste_transferts')

    context = _context_imprimer_bon_livraison(bon)
    context['auto_print'] = request.GET.get('print') == '1'
    context['print_title'] = f"Bon de livraison {bon.numero_bon_livraison}"
    return render(request, 'mag/imprimer_bon_livraison.html', context)


@login_required(login_url='connexion')
@require_POST
def marquer_livraison_en_route(request, bon_id):
    from .models import BonLivraison
    from .stock_transfers import _notifier_chefs_local, _publish_mqtt_demande

    bon = get_object_or_404(
        BonLivraison.objects.select_related('demande_transfert__local_demandeur'),
        pk=bon_id,
    )
    demande = bon.demande_transfert
    if not utilisateur_peut_gerer_livraison_donneur(request.user, demande):
        messages.error(request, 'Action réservée au chef d\'agence donneur.')
        return redirect('liste_transferts')
    if bon.statut != 'en_preparation':
        messages.error(request, "Le bon n'est plus en attente d'expédition.")
        return redirect('liste_transferts')
    bon.marquer_en_route()
    _notifier_chefs_local(
        demande.local_demandeur,
        titre=f'Livraison en cours — {demande.numero_demande}',
        message=(
            f"La livraison {bon.numero_bon_livraison} est en route vers "
            f"{demande.local_demandeur.nom}."
        ),
        type_notif='info',
    )
    _publish_mqtt_demande(demande, 'en_route')
    messages.success(request, f"Livraison {bon.numero_bon_livraison} en route.")
    return redirect('liste_transferts')


@login_required(login_url='connexion')
@require_POST
def marquer_livraison_livre(request, bon_id):
    from .models import BonLivraison
    from .stock_transfers import _notifier_chefs_local, _publish_mqtt_demande

    bon = get_object_or_404(
        BonLivraison.objects.select_related('demande_transfert__local_demandeur'),
        pk=bon_id,
    )
    demande = bon.demande_transfert
    if not utilisateur_peut_gerer_livraison_donneur(request.user, demande):
        messages.error(request, 'Action réservée au chef d\'agence donneur.')
        return redirect('liste_transferts')
    if bon.statut != 'en_route':
        messages.error(request, 'Marquez d\'abord la livraison « en route ».')
        return redirect('liste_transferts')
    bon.marquer_livre()
    _notifier_chefs_local(
        demande.local_demandeur,
        titre=f'Livraison livrée — {demande.numero_demande}',
        message=(
            f"La livraison {bon.numero_bon_livraison} est arrivée. "
            f"Vous pouvez confirmer la réception avec le bon n° {demande.numero_bon_donneur}."
        ),
        type_notif='success',
    )
    _publish_mqtt_demande(demande, 'livre')
    messages.success(request, f"Livraison {bon.numero_bon_livraison} marquée livrée.")
    return redirect('liste_transferts')


# ============================================================================
# VUES POUR LES NOTIFICATIONS D'ALERTE DE STOCK
# ============================================================================

@login_required(login_url='connexion')
def get_notifications(request):
    """
    Vue AJAX pour récupérer les notifications non lues de l'utilisateur.

    Déclenche aussi l'envoi programmé des alertes stock (4×/jour) si le créneau
    horaire l'exige (throttle global 90 s).

    Règle de localité :
      - admin / superuser : aucune restriction (voit toutes les alertes).
      - gestionnaire / accueil / caissier (+ autres rôles avec une localité) :
        les alertes stock sont filtrées pour n'afficher que les pièces de
        sa propre localité.
    """
    from django.core.cache import cache
    from stock.stock_alerts import (
        process_stock_alert_schedule,
        get_next_creneau,
        get_stock_alert_slots,
    )

    alert_sync = None
    if cache.add('stock_alert_poll_lock', '1', timeout=90):
        try:
            alert_sync = process_stock_alert_schedule()
        except Exception as exc:
            alert_sync = {'error': str(exc)}

    user_role = getattr(request.user, 'role', None)
    is_admin_like = request.user.is_superuser or user_role == 'admin'
    user_localite = getattr(request.user, 'local_entrepot', None)

    notifications = Notification.objects.filter(
        utilisateur=request.user,
        lu=False,
    ).order_by('-date_creation')[:10]

    notifications_data = []
    for notif in notifications:
        if notif.type_notification == 'stock_alerte' and notif.pieces_alerte.exists():
            pieces_qs = notif.pieces_alerte.all()
            for piece in pieces_qs:
                if not is_admin_like and user_localite:
                    stock = StockLocal.objects.filter(
                        piece=piece, local_entrepot=user_localite
                    ).first()
                    if not stock or stock.quantite_disponible >= stock.seuil_local:
                        continue
                    qty, seuil = stock.quantite_disponible, stock.seuil_local
                    loc_nom = user_localite.nom
                else:
                    qty = piece.quantite_totale
                    seuil = piece.seuil
                    loc_nom = None
                notifications_data.append({
                    'id': str(notif.id),
                    'titre': f"Alerte Stock : {piece.designation}",
                    'message': f"{piece.designation} ({piece.numero_piece}) est en dessous du seuil. "
                               f"Quantité : {qty} / Seuil : {seuil}",
                    'type': notif.type_notification,
                    'date': notif.date_creation.strftime('%d/%m/%Y %H:%M'),
                    'lu': notif.lu,
                    'localite': loc_nom,
                })
        else:
            notif_url = None
            if notif.type_notification == 'transfert_demande':
                notif_url = reverse('liste_transferts')
            elif notif.type_notification == 'commande_en_ligne':
                try:
                    notif_url = reverse('cmd_line')
                except Exception:
                    try:
                        notif_url = reverse('ecom_cmd_line')
                    except Exception:
                        notif_url = None
            notifications_data.append({
                'id': str(notif.id),
                'titre': notif.titre,
                'message': notif.message,
                'type': notif.type_notification,
                'date': notif.date_creation.strftime('%d/%m/%Y %H:%M'),
                'lu': notif.lu,
                'localite': None,
                'url': notif_url,
            })

    nb_non_lues = len(notifications_data)

    from ecom.services import (
        count_commandes_ligne_en_attente,
        count_livraisons_cmd_ligne_a_livrer,
    )
    nb_cmd_ligne_attente = count_commandes_ligne_en_attente(request.user)
    nb_livraison_cmd_a_livrer = count_livraisons_cmd_ligne_a_livrer(request.user)

    slots = get_stock_alert_slots()
    horaires = [f"{h:02d}h{m:02d}" for h, m in slots]

    return JsonResponse({
        'notifications': notifications_data,
        'nb_non_lues': nb_non_lues,
        'nb_cmd_ligne_attente': nb_cmd_ligne_attente,
        'nb_livraison_cmd_a_livrer': nb_livraison_cmd_a_livrer,
        'nb_interfaces_notif': nb_cmd_ligne_attente + nb_livraison_cmd_a_livrer,
        'is_admin_like': is_admin_like,
        'user_localite': user_localite.nom if user_localite else None,
        'alertes_stock': {
            'horaires': horaires,
            'prochain_creneau': get_next_creneau(),
            'sync': alert_sync,
        },
    })

@login_required(login_url='connexion')
@require_POST
def marquer_notification_lue(request, notification_id):
    """
    Vue pour marquer une notification comme lue
    """
    try:
        notification = get_object_or_404(
            Notification,
            id=notification_id,
            utilisateur=request.user
        )
        notification.lu = True
        notification.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required(login_url='connexion')
@require_POST
def marquer_toutes_notifications_lues(request):
    """
    Vue pour marquer toutes les notifications comme lues
    """
    try:
        Notification.objects.filter(
            utilisateur=request.user,
            lu=False
        ).update(lu=True)
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

