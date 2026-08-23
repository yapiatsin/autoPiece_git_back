from django.contrib import admin
from .models import (
    Categorie, SousCategorie, Piece, Fournisseur, PanierItem, Panier, Ticket, Commande,
    MoyenPaiement, EntrePiece, Notification, StockLocal, TransfertStock,
    DemandeTransfert, LigneDemandeTransfert, BaremeTimbre, ParametreTVA, BonCommandePaiement,
    GeniusPayPaiement,
    TarifLivraison, PalierLivraison, BonLivraison,
)

@admin.register(Categorie)
class CategorieAdmin(admin.ModelAdmin):
    list_display = ['cid', 'categorie']
    search_fields = ['cid', 'categorie']


@admin.register(SousCategorie)
class SousCategorieAdmin(admin.ModelAdmin):
    list_display = ['sid', 'nom', 'categorie', 'ordre', 'actif']
    list_filter = ['categorie', 'actif']
    search_fields = ['sid', 'nom', 'categorie__categorie']
    list_editable = ['ordre', 'actif']

@admin.register(MoyenPaiement)
class MoyenPaiementAdmin(admin.ModelAdmin):
    list_display = ['nom', 'code', 'actif', 'date_creation']
    search_fields = ['nom', 'code']
    list_filter = ['actif']


@admin.register(GeniusPayPaiement)
class GeniusPayPaiementAdmin(admin.ModelAdmin):
    list_display = ['reference', 'commande', 'source', 'statut', 'payment_method', 'amount', 'environment', 'date_creation']
    list_filter = ['source', 'statut', 'payment_method', 'environment']
    search_fields = ['reference', 'commande__numero_commande']
    readonly_fields = ['reference', 'raw_response', 'metadata', 'date_creation', 'date_maj']


@admin.register(BaremeTimbre)
class BaremeTimbreAdmin(admin.ModelAdmin):
    list_display = ['montant_min', 'montant_max', 'montant_timbre', 'actif', 'date_creation']
    list_filter = ['actif']
    ordering = ['montant_min']


@admin.register(ParametreTVA)
class ParametreTVAAdmin(admin.ModelAdmin):
    list_display = ['active', 'taux', 'date_maj']
    list_filter = ['active']


class StockLocalInline(admin.TabularInline):
    model = StockLocal
    extra = 0
    fields = [
        'local_entrepot', 'quantite_disponible', 'seuil_local', 'prix_unitaire_local',
        'emplacement', 'active_sortie', 'archive_par', 'archive_le',
    ]

@admin.register(Piece)
class PieceAdmin(admin.ModelAdmin):
    list_display = [
        'categorie', 'sous_categorie', 'numero_piece', 'designation', 'prix_achat', 'prix_unitaire',
        'seuil', 'emplacement', 'active_sortie', 'archive_par', 'archive_le', 'utilisateur',
    ]
    search_fields = ['numero_piece', 'designation']
    list_filter = ['categorie', 'sous_categorie', 'active_sortie']
    autocomplete_fields = ['categorie', 'sous_categorie']
    inlines = [StockLocalInline]

@admin.register(StockLocal)
class StockLocalAdmin(admin.ModelAdmin):
    list_display = [
        'piece', 'local_entrepot', 'quantite_disponible', 'seuil_local',
        'prix_unitaire_local', 'active_sortie', 'emplacement', 'date_maj', 'archive_par', 'archive_le',
    ]
    list_filter = ['local_entrepot', 'active_sortie', 'archive_par', 'archive_le']
    search_fields = ['piece__numero_piece', 'piece__designation', 'archive_par__username', 'local_entrepot__nom']

class LigneDemandeTransfertInline(admin.TabularInline):
    model = LigneDemandeTransfert
    extra = 0


class PalierLivraisonInline(admin.TabularInline):
    model = PalierLivraison
    extra = 1
    fields = ['ordre', 'km_min', 'km_max', 'cout_par_km']


@admin.register(TarifLivraison)
class TarifLivraisonAdmin(admin.ModelAdmin):
    list_display = ['cout_par_km', 'actif', 'date_effet', 'date_fin', 'cree_par']
    list_filter = ['actif']
    inlines = [PalierLivraisonInline]


@admin.register(BonLivraison)
class BonLivraisonAdmin(admin.ModelAdmin):
    list_display = [
        'numero_bon_livraison', 'demande_transfert', 'livreur', 'distance_km',
        'cout_base', 'cout_ajustement', 'statut', 'date_creation',
    ]
    list_filter = ['statut', 'livreur']
    search_fields = ['numero_bon_livraison', 'demande_transfert__numero_demande']


@admin.register(DemandeTransfert)
class DemandeTransfertAdmin(admin.ModelAdmin):
    list_display = [
        'numero_demande', 'local_demandeur', 'local_donneur', 'statut',
        'numero_bon_donneur', 'date_demande',
    ]
    list_filter = ['statut', 'local_demandeur', 'local_donneur']
    search_fields = ['numero_demande', 'numero_bon_donneur', 'numero_bon_commande']
    inlines = [LigneDemandeTransfertInline]


@admin.register(TransfertStock)
class TransfertStockAdmin(admin.ModelAdmin):
    list_display = ['numero', 'piece', 'quantite', 'local_source', 'local_destination', 'statut', 'date_demande']
    list_filter = ['statut', 'local_source', 'local_destination']
    search_fields = ['numero', 'piece__numero_piece']

@admin.register(Fournisseur)
class FournisseurAdmin(admin.ModelAdmin):
    list_display = ['nom', 'contact']
    search_fields = ['nom']

@admin.register(Panier)
class PanierAdmin(admin.ModelAdmin):
    list_display = ['id', 'ticket', 'valide', 'panier_paye', 'panier_livre', 'local_entrepot', 'proforma']
    list_filter = ['valide', 'panier_paye', 'proforma', 'local_entrepot']

@admin.register(PanierItem)
class PanierItemAdmin(admin.ModelAdmin):
    list_display = ['panier', 'piece', 'quantite']
    search_fields = ['piece__numero_piece']

@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ['numero', 'commande', 'utilisateur', 'utilise', 'date_save']
    search_fields = ['numero']

@admin.register(Commande)
class CommandeAdmin(admin.ModelAdmin):
    list_display = [
        'numero_commande', 'statut_commande', 'total', 'montant_tva', 'montant_timbre',
        'paye', 'date_creation', 'utilisateur',
    ]
    list_filter = ['statut_commande', 'paye']

@admin.register(EntrePiece)
class EntrePieceAdmin(admin.ModelAdmin):
    list_display = ['piece', 'local_entrepot', 'quantitajout', 'origine_type', 'origine_local', 'prix_achat', 'fournisseur', 'date']
    list_filter = ['local_entrepot', 'origine_type', 'fournisseur']

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['titre', 'type_notification', 'utilisateur', 'lu', 'date_creation']
    list_filter = ['type_notification', 'lu']

@admin.register(BonCommandePaiement)
class BonCommandePaiementAdmin(admin.ModelAdmin):
    list_display = ['numero_bon', 'commande', 'ticket_numero', 'local_entrepot', 'caissier', 'hote_accueil', 'client_nom', 'moyen_paiement_nom', 'montant_paye', 'montant_reste', 'total_commande', 'date_emission']
    list_filter = ['local_entrepot', 'caissier', 'hote_accueil']
    search_fields = ['numero_bon', 'ticket_numero']