from django.urls import path
from .views import *

urlpatterns = [
    path('', pbholdingsiteview, name='pbholdingsite'),
    path('Se-connecter', loginview, name='connexion'),
    path('Inscription', register_view, name='register'),
    path('activation/<str:token>/', activate_account_view, name='activate-account'),
    path('renvoyer-activation/', resend_activation_view, name='resend-activation'),
    path('Deconnexion', Deconnexion, name='deconnexion'),

    path('mot-de-passe-oublie/', ForgotPasswordView.as_view(), name='forgot'),
    path('otp/', OptValid.as_view(), name='otp'),
    path('request-email/', RequestEmailView.as_view(), name='request_email'),
    path('verify-otp/', VerifyOtpView.as_view(), name='verify_otp'),
    path('changer-mot-de-passe/',PasswordChangeView.as_view(), name='password_change'),
    path('password_change/done/', PasswordChangeDoneView.as_view(), name='password_change_done'),
    path('profil/changer-mot-de-passe/', change_password_profile, name='change_password'),
    path('add-compte', AddCompte, name='add_compte'),
    path('comptes/export-excel/', export_comptes_excel, name='export_comptes_excel'),
    path('comptes-clients/', list_comptes_clients, name='compte_client'),
    path('comptes-clients/export-excel/', export_comptes_clients_excel, name='export_comptes_clients_excel'),
    path('comptes-clients/<int:pk>/detail/', detail_compte_client, name='detail_compte_client'),
    path('comptes-clients/<int:pk>/fiche-pdf/', imprimer_fiche_client_pdf, name='fiche_client_pdf'),
    path('comptes-clients/<int:pk>/modifier/', UpdateCompteClientView.as_view(), name='update_compte_client'),
    path('comptes-clients/<int:pk>/supprimer/', delete_compte_client, name='del_compte_client'),
    path('modifier-un-compte/<int:pk>/auto pièce', UpdateCompteView.as_view(), name='update_compte'),
    path('modifier-permissions/<int:pk>/', update_permissions, name='update_permissions'),
    path('activer-compte/<int:pk>/auto pièce', ActivateCompte, name='active_compte'),
    path('désactive-compte/<int:pk>/auto pièce', DeactivatCompte, name='deactive_compte'),
    path('supprimer-un-compte/<int:pk>/auto pièce', delete_compte, name='del_compte'),
    
    # URLs pour la gestion des permissions personnalisées
    path('permissions/', list_permissions, name='list_permissions'),
    path('permissions/create/', create_permission, name='create_permission'),
    path('permissions/<int:pk>/update/', update_permission, name='update_permission'),
    path('permissions/<int:pk>/delete/', delete_permission, name='delete_permission'),
    path('permissions/import-excel/', import_permissions_excel, name='import_permissions_excel'),
    path('permissions/export-excel/', export_permissions_excel, name='export_permissions_excel'),
    
    # URLs pour la gestion des catégories de permissions
    path('permissions/categories/', list_categories, name='list_perm_categories'),
    path('permissions/categories/create/', create_category, name='create_perm_category'),
    path('permissions/categories/<int:pk>/update/', update_category, name='update_perm_category'),
    path('permissions/categories/<int:pk>/delete/', delete_category, name='delete_perm_category'),

    # Localités / entrepôts
    path('localites/', add_localite, name='add_localite'),
    path('localites/<uuid:pk>/modifier/', update_localite, name='update_localite'),
    path('localites/<uuid:pk>/supprimer/', delete_localite, name='delete_localite'),
]
