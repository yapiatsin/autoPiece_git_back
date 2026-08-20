"""Routes API v1 — client mobile."""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from api.views import account, auth, cart, catalogue, checkout, favorites, home, localites, orders, search

urlpatterns = [
    # Auth
    path('auth/register/', auth.RegisterView.as_view(), name='v1_register'),
    path('auth/register/otp/verify/', auth.RegisterOtpVerifyView.as_view(), name='v1_register_otp_verify'),
    path('auth/register/otp/resend/', auth.RegisterOtpResendView.as_view(), name='v1_register_otp_resend'),
    path('auth/register/otp/status/', auth.RegisterOtpStatusView.as_view(), name='v1_register_otp_status'),
    path('auth/login/', auth.LoginView.as_view(), name='v1_login'),
    path('auth/logout/', auth.LogoutView.as_view(), name='v1_logout'),
    path('auth/me/', auth.MeView.as_view(), name='v1_me'),
    path('auth/password/change/', auth.PasswordChangeView.as_view(), name='v1_password_change'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='v1_token_refresh'),
    path('auth/token/verify/', TokenVerifyView.as_view(), name='v1_token_verify'),

    # Accueil
    path('home/', home.HomeView.as_view(), name='v1_home'),

    # Localités
    path('localites/', localites.LocaliteListView.as_view(), name='v1_localites'),
    path('localites/select/', localites.LocaliteSelectView.as_view(), name='v1_localites_select'),

    # Catalogue
    path('catalog/categories/', catalogue.CategoryListView.as_view(), name='v1_categories'),
    path('catalog/products/', catalogue.ProductListView.as_view(), name='v1_products'),
    path('catalog/products/<int:pk>/', catalogue.ProductDetailView.as_view(), name='v1_product_detail'),

    # Recherche
    path('search/recent/', search.SearchRecentView.as_view(), name='v1_search_recent'),
    path('search/popular/', search.SearchPopularView.as_view(), name='v1_search_popular'),

    # Panier
    path('cart/', cart.CartView.as_view(), name='v1_cart'),
    path('cart/items/', cart.CartAddItemView.as_view(), name='v1_cart_add'),
    path('cart/items/<int:item_id>/', cart.CartUpdateItemView.as_view(), name='v1_cart_update'),
    path('cart/pieces/<int:piece_id>/quantity/', cart.CartSetPieceQuantityView.as_view(), name='v1_cart_set_qty'),

    # Checkout
    path('checkout/', checkout.CheckoutPreviewView.as_view(), name='v1_checkout'),
    path('checkout/villes/', checkout.CheckoutVillesView.as_view(), name='v1_checkout_villes'),
    path('checkout/communes/', checkout.CheckoutCommunesView.as_view(), name='v1_checkout_communes'),
    path('checkout/frais/', checkout.CheckoutFraisView.as_view(), name='v1_checkout_frais'),
    path('checkout/confirm/', checkout.CheckoutConfirmView.as_view(), name='v1_checkout_confirm'),

    # Commandes
    path('orders/', orders.OrderListView.as_view(), name='v1_orders'),
    path('orders/<str:commande_id>/', orders.OrderDetailView.as_view(), name='v1_order_detail'),
    path('orders/<str:commande_id>/cancel/', orders.OrderCancelView.as_view(), name='v1_order_cancel'),
    path('orders/<str:commande_id>/confirm-receipt/', orders.OrderConfirmReceiptView.as_view(), name='v1_order_confirm'),
    path('orders/<str:commande_id>/invoice/', orders.OrderInvoiceView.as_view(), name='v1_order_invoice'),

    # Compte
    path('account/', account.AccountView.as_view(), name='v1_account'),
    path('account/address/', account.AccountAddressView.as_view(), name='v1_account_address'),
    path('account/photo/', account.AccountPhotoView.as_view(), name='v1_account_photo'),

    # Favoris & vues récentes
    path('favorites/', favorites.FavoriteListView.as_view(), name='v1_favorites'),
    path('favorites/<int:piece_id>/', favorites.FavoriteAddView.as_view(), name='v1_favorite_add'),
    path('favorites/<int:piece_id>/remove/', favorites.FavoriteRemoveView.as_view(), name='v1_favorite_remove'),
    path('favorites/<int:piece_id>/toggle/', favorites.FavoriteToggleView.as_view(), name='v1_favorite_toggle'),
    path('recently-viewed/', favorites.RecentlyViewedView.as_view(), name='v1_recently_viewed'),
]
