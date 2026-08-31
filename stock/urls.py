from django.urls import path
from stock.views import *
from stock.geniuspay_views import caisse_geniuspay_statut, caisse_geniuspay_retour
from stock.views import imprimer_bon_commande_vente
from stock.export_views import (
    export_liste_ventes_excel, export_liste_ventes_pdf,
    export_liste_commandes_excel, export_liste_commandes_pdf,
    export_stock_excel, export_stock_pdf,
    export_caisse_ventes_excel, export_caisse_ventes_pdf,
    export_best_vente_excel, export_best_vente_pdf,
    export_hist_cmd_excel, export_hist_cmd_pdf,
    export_hist_gen_excel, export_hist_gen_pdf,
    export_pieces_categorie_excel, export_pieces_categorie_pdf,
    export_entrees_piece_excel, export_entrees_piece_pdf,
    export_livraisons_excel, export_livraisons_pdf,
    export_cmd_line_excel, export_cmd_line_pdf,
    export_livraison_cmd_online_excel, export_livraison_cmd_online_pdf,
)
from ecom.views import (
    cmd_line,
    ajax_cmd_line_detail,
    ajax_livraison_cmd_detail,
    cmd_line_assigner_livreur,
    cmd_line_valider,
    LivraisonCmdOnlineView,
    ZonesLivraisonView,
    zones_livraison_delete,
    zones_livraison_save,
    zones_livraison_toggle,
)

# from . import views
from .views import *
from . import views
urlpatterns = [
    #piece
    path('tableau-de-bords', TableauBordsView.as_view(), name='tbord'),
    path('top-vente', topBestPiecView.as_view(), name='topventes'),
    path('piece-en-rupture', PieceRuptureView.as_view(), name='piece_rupture'),
    path('mes-ventes', VenteView.as_view(), name='mesventes'),
    path('vente/export-excel/', export_ventes_excel, name='export_ventes_excel'),
    
    path('nouvelle-categorie', AddCategorieView.as_view(), name="add_categorie"),
    path('modifier_categorie/<int:pk>/edit', UpdateCategorieView.as_view(), name='update_categorie'),
    path('sous-categorie/nouvelle/', add_sous_categorie, name='add_sous_categorie'),
    path('sous-categorie/modele-excel/', download_modele_sous_categories_excel, name='download_modele_sous_categories_excel'),
    path('sous-categorie/import-excel/', import_sous_categories_excel, name='import_sous_categories_excel'),
    path('sous-categorie/<int:pk>/edit', UpdateSousCategorieView.as_view(), name='update_sous_categorie'),
    path('sous-categorie/<int:pk>/delete', delete_sous_categorie, name='delete_sous_categorie'),
    path('ajax/sous-categories/', ajax_sous_categories, name='ajax_sous_categories'),
    path('produit/<int:pk>/pièce', AddPieceView.as_view(), name='add_piece'),
    path('produit/<int:pk>/modele-excel/', download_modele_pieces_excel, name='download_modele_pieces_excel'),
    path('supprimer-categorie/<int:pk>/fatme', delete_categorie, name="delet_categorie"),

    path('nouveau-panier', AddPanierView.as_view(), name="paniers"),
    path('ajax/search-articles/', ajax_search_articles, name='ajax_search_articles'),
    path('ajax/search-articles-proforma/', ajax_search_articles_proforma, name='ajax_search_articles_proforma'),
    # Vue unifiée (fusion des 4 anciennes fonctions). L'action est passée via kwargs
    # pour chaque URL, ce qui conserve les noms d'URL existants et le support
    # rétro-compatible (redirection si appel non-AJAX).
    path('Article/<int:pk>/ajouter_au_panier', panier_action, {'action': 'add'}, name='add_panier'),
    path('ajax/add_panier/<int:pk>/', panier_action, {'action': 'increment'}, name='ajax_add_panier'),
    path('ajax/remove_panier/<int:pk>/', panier_action, {'action': 'decrement'}, name='ajax_remove_panier'),
    path('ajax/delete_panier/<int:pk>/', panier_action, {'action': 'delete'}, name='ajax_delete_panier'),
    # Endpoint générique (optionnel) : action passée dans le body POST.
    path('ajax/panier/<int:pk>/', panier_action, name='panier_action'),
    path('ajax/panier-accueil/etat/', ajax_panier_accueil_state, name='ajax_panier_accueil_state'),
    path('valide-panier', valider_paniers, name='valid_panier'),
    
    # URLs pour la proforma
    path('nouvelle-proforma', AddProformaView.as_view(), name='add_proforma'),
    # Vue unifiée proforma — même noms d'URL conservés pour rétro-compatibilité
    path('Article/<int:pk>/ajouter_au_panier_proforma', panier_proforma_action, {'action': 'add'},       name='add_panier_proforma'),
    path('ajax/add_panier_proforma/<int:pk>/',          panier_proforma_action, {'action': 'increment'}, name='ajax_add_panier_proforma'),
    path('ajax/remove_panier_proforma/<int:pk>/',       panier_proforma_action, {'action': 'decrement'}, name='ajax_remove_panier_proforma'),
    path('ajax/delete_panier_proforma/<int:pk>/',       panier_proforma_action, {'action': 'delete'},    name='ajax_delete_panier_proforma'),
    # Endpoint générique : action dans le POST body
    path('ajax/panier_proforma/<int:pk>/',              panier_proforma_action, name='panier_proforma_action'),
    
    path('valider_proforma', valider_proforma, name='valider_proforma'),
    path('valider_proforma/<str:ticket_id>/', valider_proforma, name='valider_proforma'),
    path('proformas-en-attente', ProformaAttenteView.as_view(), name='proforma_attente'),
    path('ajax/search-proformas/', ajax_search_proformas, name='ajax_search_proformas'),
    path('ajax/detail_proforma/<str:ticket_id>/', ajax_detail_proforma, name='ajax_detail_proforma'),
    path('valider_panier_proforma/<str:ticket_id>/', valider_panier_proforma, name='valider_panier_proforma'),
    path('supprimer_proforma/<str:ticket_id>/', supprimer_proforma, name='supprimer_proforma'),
    path('imprimer_proforma/<str:ticket_id>/', imprimer_proforma_pdf, name='imprimer_proforma_pdf'),
    path('imprimer_bon_commande/<str:ticket_id>/', imprimer_recu_commande, name='imprimer_recu_commande'),

    # Module de connexion d'imprimante USB générique
    path('imprimante/scan/', printer_scan_view, name='printer_scan'),
    path('imprimante/connect/', printer_connect_view, name='printer_connect'),
    path('imprimante/test/', printer_test_view, name='printer_test'),
    path('ajax/reload_paniers/', ajax_reload_paniers, name='ajax_reload_paniers'),
    path('ajax/reload_liste_commandes/', ajax_reload_liste_commandes, name='ajax_reload_liste_commandes'),
    path('ajax/caisse_detail/<str:ticket_id>/', ajax_caisse_detail, name='ajax_caisse_detail'),
    path('ajax/calcul-timbre/', ajax_calcul_timbre, name='ajax_calcul_timbre'),

    path('caisse/paiement/', Caisse, name='caissiere'),
    path('caisse/paiement/geniuspay/retour/', caisse_geniuspay_retour, name='caisse_geniuspay_retour'),
    path('caisse/paiement/<str:ticket_id>/geniuspay/statut/', caisse_geniuspay_statut, name='caisse_geniuspay_statut'),
    path('caisse/paiement/<str:ticket_id>/', valider_panier_paiement, name='valid_pay_article'),
    path('caisse/bon-commande/<str:ticket_numero>/imprimer/', imprimer_bon_commande_vente, name='imprimer_bon_commande_vente'),
    path('caisse/reimprimer-recu/<str:ticket_numero>/', reimprimer_recu_paiement, name='reimprimer_recu_paiement'),
    path('bons-commande-paiement/', BonCommandePaiementListView.as_view(), name='bons_commande_paiement'),

    path('livraison/', LivraisonView.as_view(), name='livraisons'),
    path('livraison/valider/<str:ticket_id>/', valider_livraison, name='valider_livraison'),
    path('ajax/reload_livraisons/', ajax_reload_livraisons, name='ajax_reload_livraisons'),
    path('commandes-en-ligne/', cmd_line, name='cmd_line'),
    path('commandes-en-ligne/<str:commande_id>/detail/', ajax_cmd_line_detail, name='cmd_line_detail'),
    path('commandes-en-ligne/<str:commande_id>/valider/', cmd_line_valider, name='cmd_line_valider'),
    path('commandes-en-ligne/<str:commande_id>/assigner/', cmd_line_assigner_livreur, name='cmd_line_assigner'),
    path('livraison-en-ligne/', LivraisonCmdOnlineView.as_view(), name='livraison_cmd_online'),
    path('livraison-en-ligne/<str:commande_id>/detail/', ajax_livraison_cmd_detail, name='livraison_cmd_detail'),
    path('zones-livraison/', ZonesLivraisonView.as_view(), name='zones_livraison'),
    path('zones-livraison/save/', zones_livraison_save, name='zones_livraison_save'),
    path('zones-livraison/toggle/', zones_livraison_toggle, name='zones_livraison_toggle'),
    path('zones-livraison/delete/', zones_livraison_delete, name='zones_livraison_delete'),
    
    path('liste-des-pieces/', MonStockView.as_view(), name="stock"),
    path('pieces-archivees/', PieceArchiveView.as_view(), name='pieces_archivees'),
    path('piece/<int:pk>/prix-local/', ajax_definir_prix_local, name='ajax_definir_prix_local'),
    path('piece/<int:pk>/entrestock', EntreSockPieceView.as_view(), name='entrestock'),
    path('piece/<int:pk>/',piece_detail, name='piece_detail'),
    
    path('nouveau-fournisseur',AddfournisseurView.as_view(), name='nouveau_fournisseur'),
    path('modifier_fournisseur/<int:pk>/edit',UpdatefournisseurView.as_view(), name='update_fournisseur'),
    path('modifier_piece/<int:pk>/edit',UpdatepieceView.as_view(), name='update_piece'),
    path('detail_piece/<int:pk>/info',historique_entrees_piece, name='info_piece'),
    path('piece/<int:pk>/delete/', piece_delete, name='piece_delete'),
    path('piece/<int:pk>/activate_sortie/', activate_sortie, name='activate_sortie'),
    path('piece/<int:pk>/deactivate_sortie/', deactivate_sortie, name='deactivate_sortie'),
    path('piece/<int:pk>/activate_sortie_local/', activate_sortie_local, name='activate_sortie_local'),
    path('piece/<int:pk>/deactivate_sortie_local/', deactivate_sortie_local, name='deactivate_sortie_local'),
    
    # URLs pour les notifications
    path('notifications/', get_notifications, name='get_notifications'),
    path('notifications/liste/', ListeNotificationsView.as_view(), name='liste_notifications'),
    path('notifications/<str:notification_id>/detail/', notification_detail, name='notification_detail'),
    path('notifications/<str:notification_id>/delete/', notification_delete, name='notification_delete'),
    path('notifications/<str:notification_id>/marquer-lue/', marquer_notification_lue, name='marquer_notification_lue'),
    path('notifications/marquer-toutes-lues/', marquer_toutes_notifications_lues, name='marquer_toutes_notifications_lues'),
    
    path('fournisseur/<int:pk>/delete/', fourn_delete, name='fourniss'), 
    path('details_commande/<int:commande_id>/', views.details_commande, name='details_commande'),
    #piece
    path('Historique/', global_history_view, name='global_history'), 
    path('Historique-commande/', historique_commandes, name='Historique_commande'),
    path('Historique-panier/', historique_panier, name='Historique_panier'),
    path('Historique-pieces/', historique_pieces, name='Historique_pieces'),
    path('liste-commandes/', Liste_CmdeView.as_view(), name='liste_commandes'),
    path('liste-ventes/', ListeVentesView.as_view(), name='liste_ventes'),

    # Exports Excel / PDF (filtres GET conservés)
    path('export/ventes/excel/', export_liste_ventes_excel, name='export_liste_ventes_excel'),
    path('export/ventes/pdf/', export_liste_ventes_pdf, name='export_liste_ventes_pdf'),
    path('export/commandes/excel/', export_liste_commandes_excel, name='export_liste_commandes_excel'),
    path('export/commandes/pdf/', export_liste_commandes_pdf, name='export_liste_commandes_pdf'),
    path('export/stock/excel/', export_stock_excel, name='export_stock_excel'),
    path('export/stock/pdf/', export_stock_pdf, name='export_stock_pdf'),
    path('export/caisse-ventes/excel/', export_caisse_ventes_excel, name='export_caisse_ventes_excel'),
    path('export/caisse-ventes/pdf/', export_caisse_ventes_pdf, name='export_caisse_ventes_pdf'),
    path('export/meilleures-ventes/excel/', export_best_vente_excel, name='export_best_vente_excel'),
    path('export/meilleures-ventes/pdf/', export_best_vente_pdf, name='export_best_vente_pdf'),
    path('export/historique-commandes/excel/', export_hist_cmd_excel, name='export_hist_cmd_excel'),
    path('export/historique-commandes/pdf/', export_hist_cmd_pdf, name='export_hist_cmd_pdf'),
    path('export/historique-general/excel/', export_hist_gen_excel, name='export_hist_gen_excel'),
    path('export/historique-general/pdf/', export_hist_gen_pdf, name='export_hist_gen_pdf'),
    path('export/pieces/<int:pk>/excel/', export_pieces_categorie_excel, name='export_pieces_categorie_excel'),
    path('export/pieces/<int:pk>/pdf/', export_pieces_categorie_pdf, name='export_pieces_categorie_pdf'),
    path('export/entrees-piece/<int:pk>/excel/', export_entrees_piece_excel, name='export_entrees_piece_excel'),
    path('export/entrees-piece/<int:pk>/pdf/', export_entrees_piece_pdf, name='export_entrees_piece_pdf'),
    path('export/livraisons/excel/', export_livraisons_excel, name='export_livraisons_excel'),
    path('export/livraisons/pdf/', export_livraisons_pdf, name='export_livraisons_pdf'),
    path('export/commandes-en-ligne/excel/', export_cmd_line_excel, name='export_cmd_line_excel'),
    path('export/commandes-en-ligne/pdf/', export_cmd_line_pdf, name='export_cmd_line_pdf'),
    path('export/livraison-en-ligne/excel/', export_livraison_cmd_online_excel, name='export_livraison_cmd_online_excel'),
    path('export/livraison-en-ligne/pdf/', export_livraison_cmd_online_pdf, name='export_livraison_cmd_online_pdf'),

    # Transferts entre localités (chefs d'agence)
    path('transferts/', liste_transferts, name='liste_transferts'),
    path('transferts/creer/', creer_demande_transfert_view, name='creer_demande_transfert'),
    path('transferts/<int:demande_id>/annuler-demandeur/', annuler_demande_demandeur_view, name='annuler_demande_demandeur'),
    path('transferts/<int:demande_id>/valider-donneur/', valider_demande_donneur_view, name='valider_demande_donneur'),
    path('transferts/<int:demande_id>/annuler-donneur/', annuler_demande_donneur_view, name='annuler_demande_donneur'),
    path('transferts/<int:demande_id>/recevoir/', recevoir_demande_transfert_view, name='recevoir_demande_transfert'),
    path('transferts/<int:demande_id>/detail/', ajax_detail_demande_transfert, name='ajax_detail_demande_transfert'),
    path('transferts/<int:demande_id>/imprimer/', imprimer_demande_transfert, name='imprimer_demande_transfert'),
    path('transferts/bon-livraison/<int:bon_id>/imprimer/', imprimer_bon_livraison, name='imprimer_bon_livraison'),
    path('transferts/ajax/livreurs/<uuid:local_pk>/', ajax_livreurs_localite, name='ajax_livreurs_localite'),

    # Gestion des paramètres
    path('parametres/', GestionParametreView.as_view(), name='gestion_parametre'),
    path('parametres/tva/save/', parametre_tva_save, name='parametre_tva_save'),
    path('parametres/tva/<int:pk>/toggle/', parametre_tva_toggle, name='parametre_tva_toggle'),
    path('parametres/tva/<int:pk>/delete/', parametre_tva_delete, name='parametre_tva_delete'),
    path('parametres/timbre/save/', bareme_timbre_save, name='bareme_timbre_save'),
    path('parametres/timbre/<int:pk>/toggle/', bareme_timbre_toggle, name='bareme_timbre_toggle'),
    path('parametres/timbre/<int:pk>/delete/', bareme_timbre_delete, name='bareme_timbre_delete'),
    path('parametres/paiement/<int:pk>/toggle/', moyen_paiement_toggle, name='moyen_paiement_toggle'),
    path('parametres/paiement/<int:pk>/delete/', moyen_paiement_delete, name='moyen_paiement_delete'),
]
