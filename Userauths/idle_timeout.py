"""Déconnexion automatique après 30 minutes d'inactivité (boutique, magasin, comptes).

Source de vérité côté serveur : la session garde l'heure de la dernière action.
Ne comptent comme « action » que les requêtes faites par l'utilisateur :
  - navigation (Sec-Fetch-Mode: navigate), navigation fluide HTMX, envois de formulaire (POST…) ;
  - le « maintien » envoyé par static/apps/assets/js/idle-logout.js quand l'utilisateur
    clique, tape ou fait défiler sans recharger de page.
Les appels automatiques (notifications, messagerie, filtres AJAX en GET) ne prolongent pas la session.
"""
from __future__ import annotations

import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from .session_control import clear_active_session

SESSION_KEY = '_derniere_activite'
IDLE_TIMEOUT = int(getattr(settings, 'IDLE_TIMEOUT_SECONDS', 30 * 60))
# Marge serveur : dans un onglet ouvert, c'est idle-logout.js qui déconnecte (avertissement
# compris) ; le serveur ne coupe qu'ensuite, ou si tous les onglets ont été fermés.
IDLE_GRACE = 90
# Écrire la session au plus une fois par minute (évite une écriture à chaque requête)
WRITE_INTERVAL = 60
MESSAGE_INACTIVITE = (
    "Vous avez été déconnecté après 30 minutes d'inactivité. Reconnectez-vous pour continuer."
)
IGNORED_PREFIXES = ('/static/', '/media/', '/api/', '/webhooks/', '/healthz/', '/favicon')


def _is_user_action(request) -> bool:
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        return True
    if request.headers.get('HX-Request') == 'true':
        return True
    mode = request.headers.get('Sec-Fetch-Mode')
    if mode:
        return mode == 'navigate'
    # Navigateur ancien sans Sec-Fetch-* : tout sauf l'AJAX déclaré
    return request.headers.get('X-Requested-With') != 'XMLHttpRequest'


def _wants_json(request) -> bool:
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    mode = request.headers.get('Sec-Fetch-Mode')
    if mode and mode != 'navigate':
        return True
    return 'application/json' in request.headers.get('Accept', '')


def _expired_response(request):
    login_url = reverse('connexion')
    if request.method == 'GET' and request.headers.get('Sec-Fetch-Mode', 'navigate') == 'navigate':
        login_url = f"{login_url}?{urlencode({'next': request.get_full_path()})}"
    if request.headers.get('HX-Request') == 'true':
        response = HttpResponse(status=200)
        response['HX-Redirect'] = login_url
        return response
    if _wants_json(request):
        return JsonResponse(
            {'success': False, 'session_expired': True, 'login_url': login_url,
             'error': MESSAGE_INACTIVITE},
            status=401,
        )
    return redirect(login_url)


class IdleTimeoutMiddleware:
    """À placer après AuthenticationMiddleware et MessageMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if (
            user is None
            or not user.is_authenticated
            or not request.session.get('_auth_user_id')     # JWT (application mobile) : non concerné
            or request.path.startswith(IGNORED_PREFIXES)
        ):
            return self.get_response(request)

        now = int(time.time())
        last = request.session.get(SESSION_KEY)
        if last is not None and now - int(last) >= IDLE_TIMEOUT + IDLE_GRACE:
            est_client = getattr(user, 'role', None) == 'client' and not user.is_superuser
            clear_active_session(user)
            logout(request)
            messages.warning(request, MESSAGE_INACTIVITE)
            if est_client and not request.path.startswith('/stocks/'):
                # La boutique est publique : le client continue en visiteur
                return self.get_response(request)
            return _expired_response(request)

        if last is None or (_is_user_action(request) and now - int(last) >= WRITE_INTERVAL):
            request.session[SESSION_KEY] = now
        return self.get_response(request)


@require_POST
def session_keepalive(request):
    """Appelé par idle-logout.js quand l'utilisateur agit sans recharger la page."""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'session_expired': True}, status=401)
    return JsonResponse({'success': True, 'timeout': IDLE_TIMEOUT})
