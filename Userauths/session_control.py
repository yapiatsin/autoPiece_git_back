"""Une seule session web active par compte utilisateur.

À chaque connexion réussie, les autres sessions Django du même compte sont
supprimées et la clé courante est mémorisée sur CustomUser.active_session_key.
Le middleware déconnecte tout navigateur dont la session n'est plus la
session active — indispensable pour la caisse (même compte sur deux postes).
"""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model, logout
from django.contrib.messages import error as messages_error
from django.contrib.sessions.models import Session
from django.shortcuts import redirect
from django.utils import timezone

logger = logging.getLogger(__name__)

MESSAGE_SESSION_REMPLACEE = (
    "Votre session a été fermée car ce compte est connecté ailleurs. "
    "Une seule connexion est autorisée à la fois (notamment en caisse)."
)


def _user_model():
    """Modèle utilisateur réel (évite type(SimpleLazyObject).objects)."""
    return get_user_model()


def claim_exclusive_session(request, user) -> str:
    """Après login : enregistre la session courante et invalide les autres."""
    if not getattr(user, 'is_authenticated', False) or not getattr(user, 'pk', None):
        return ''
    if not request.session.session_key:
        request.session.save()
    key = request.session.session_key or ''
    if not key:
        return ''

    user_id = str(user.pk)
    now = timezone.now()
    obsolete = []
    for session in Session.objects.filter(expire_date__gte=now).iterator():
        if session.session_key == key:
            continue
        try:
            data = session.get_decoded()
        except Exception:
            continue
        if str(data.get('_auth_user_id', '')) == user_id:
            obsolete.append(session.session_key)
    if obsolete:
        Session.objects.filter(session_key__in=obsolete).delete()

    previous = (getattr(user, 'active_session_key', '') or '').strip()
    if previous and previous != key:
        Session.objects.filter(session_key=previous).delete()

    if previous != key:
        _user_model().objects.filter(pk=user.pk).update(active_session_key=key)
        user.active_session_key = key
        logger.info(
            'Session exclusive pour %s : %s (anciennes invalidées : %s)',
            user.username, key[:8], len(obsolete) + (1 if previous and previous != key else 0),
        )
    return key


def clear_active_session(user) -> None:
    """À la déconnexion : libère la session exclusive du compte."""
    if not user or not getattr(user, 'pk', None):
        return
    key = (getattr(user, 'active_session_key', '') or '').strip()
    if key:
        Session.objects.filter(session_key=key).delete()
    _user_model().objects.filter(pk=user.pk).update(active_session_key='')
    try:
        user.active_session_key = ''
    except Exception:
        pass


def enforce_single_session(request):
    """
    Si l'utilisateur est authentifié mais sa session n'est plus la session
    active du compte → logout + redirect connexion.
    Retourne une HttpResponse de redirection, ou None pour continuer.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return None

    # Auth JWT / API sans session magasin : ne pas appliquer cette règle.
    if not request.session.session_key or not request.session.get('_auth_user_id'):
        return None

    current = request.session.session_key or ''
    stored = (getattr(user, 'active_session_key', '') or '').strip()

    # Première requête après déploiement / compte sans clé : rattacher.
    if not stored:
        claim_exclusive_session(request, user)
        return None

    if current and current == stored:
        return None

    # Session remplacée ailleurs (ou cookie obsolète).
    logout(request)
    messages_error(request, MESSAGE_SESSION_REMPLACEE)
    return redirect('connexion')
