from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView
from django.views.i18n import set_language
from django.views.static import serve
from ecom.views import page_not_found
from stock.geniuspay_views import geniuspay_webhook

urlpatterns = [
    path('admin/', admin.site.urls, name='admin'),
    path('i18n/', include('django.conf.urls.i18n')),
    path('webhooks/geniuspay/', geniuspay_webhook, name='geniuspay_webhook'),
    path('stocks/', include('stock.urls')),
    path('authentification/', include('Userauths.urls')),
    path('api/v1/', include('api.urls.v1')),
    path('api/', include('api.urls')),
    path('', include('ecom.urls')),
    # path('', include('account.urls'))
]+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

#urlpatterns +=staticfiles_urlpatterns
handler404 = 'ecom.views.page_not_found'

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
else:
    urlpatterns += [
        re_path(
            r'^static/(?P<path>.*)$',
            serve,
            {'document_root': settings.STATIC_ROOT},
        ),
        re_path(
            r'^media/(?P<path>.*)$',
            serve,
            {'document_root': settings.MEDIA_ROOT},
        ),
    ]

# Catch-all : toute URL non reconnue affiche la page 404 personnalisee
# (fonctionne meme quand DEBUG=True, ou Django masque handler404).
urlpatterns += [
    re_path(r'^.*$', page_not_found),
]
