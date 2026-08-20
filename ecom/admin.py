from django.contrib import admin

from .models import (
    CommuneLivraison,
    FavoriPiece,
    NewsletterAbonne,
    PaysLivraison,
    RecherchePopulaire,
    RechercheRecente,
    VilleLivraison,
    VueRecentePiece,
)


@admin.register(FavoriPiece)
class FavoriPieceAdmin(admin.ModelAdmin):
    list_display = ['utilisateur', 'piece', 'date_ajout']
    search_fields = ['utilisateur__username', 'utilisateur__email', 'piece__numero_piece', 'piece__designation']
    list_filter = ['date_ajout']
    raw_id_fields = ['utilisateur', 'piece']
    list_select_related = ['utilisateur', 'piece']
    ordering = ['-date_ajout']


@admin.register(VueRecentePiece)
class VueRecentePieceAdmin(admin.ModelAdmin):
    list_display = ['utilisateur', 'piece', 'date_vue']
    search_fields = ['utilisateur__username', 'utilisateur__email', 'piece__numero_piece', 'piece__designation']
    list_filter = ['date_vue']
    raw_id_fields = ['utilisateur', 'piece']
    list_select_related = ['utilisateur', 'piece']
    ordering = ['-date_vue']


@admin.register(NewsletterAbonne)
class NewsletterAbonneAdmin(admin.ModelAdmin):
    list_display = ['email', 'accepte_offres', 'actif', 'date_inscription']
    search_fields = ['email']
    list_filter = ['actif', 'accepte_offres', 'date_inscription']
    ordering = ['-date_inscription']
    readonly_fields = ['date_inscription', 'date_mise_a_jour']


@admin.register(RecherchePopulaire)
class RecherchePopulaireAdmin(admin.ModelAdmin):
    list_display = ['terme_affiche', 'compteur', 'derniere_recherche']
    search_fields = ['terme', 'terme_affiche']
    ordering = ['-compteur', '-derniere_recherche']
    readonly_fields = ['derniere_recherche']


@admin.register(RechercheRecente)
class RechercheRecenteAdmin(admin.ModelAdmin):
    list_display = ['terme_affiche', 'utilisateur', 'session_key', 'date_recherche']
    search_fields = ['terme', 'terme_affiche', 'utilisateur__username', 'utilisateur__email', 'session_key']
    list_filter = ['date_recherche']
    raw_id_fields = ['utilisateur']
    ordering = ['-date_recherche']
    readonly_fields = ['date_recherche']


class VilleLivraisonInline(admin.TabularInline):
    model = VilleLivraison
    extra = 0
    fields = ['nom', 'frais_livraison', 'actif']


class CommuneLivraisonInline(admin.TabularInline):
    model = CommuneLivraison
    extra = 0
    fields = ['nom', 'actif']


@admin.register(PaysLivraison)
class PaysLivraisonAdmin(admin.ModelAdmin):
    list_display = ['nom', 'code', 'actif']
    list_filter = ['actif']
    search_fields = ['nom', 'code']
    list_editable = ['actif']
    inlines = [VilleLivraisonInline]


@admin.register(VilleLivraison)
class VilleLivraisonAdmin(admin.ModelAdmin):
    list_display = ['nom', 'pays', 'frais_livraison', 'actif']
    list_filter = ['actif', 'pays']
    search_fields = ['nom', 'pays__nom']
    list_editable = ['frais_livraison', 'actif']
    list_select_related = ['pays']
    inlines = [CommuneLivraisonInline]


@admin.register(CommuneLivraison)
class CommuneLivraisonAdmin(admin.ModelAdmin):
    list_display = ['nom', 'ville', 'actif']
    list_filter = ['actif', 'ville__pays', 'ville']
    search_fields = ['nom', 'ville__nom']
    list_editable = ['actif']
    list_select_related = ['ville', 'ville__pays']
