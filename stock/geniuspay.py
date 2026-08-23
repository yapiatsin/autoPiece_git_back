"""Client HTTP GeniusPay (clés uniquement côté serveur)."""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT = 30
WEBHOOK_MAX_AGE_SECONDS = 300

_MESSAGES_ERREUR = {
    'INVALID_API_KEY': (
        'Clé API GeniusPay invalide. Vérifiez GENIUSPAY_API_KEY et '
        'GENIUSPAY_API_SECRET dans le fichier .env (Sandbox vs Production).'
    ),
    'MISSING_API_KEY': (
        'Clé API GeniusPay manquante. Renseignez GENIUSPAY_API_KEY et '
        'GENIUSPAY_API_SECRET dans le fichier .env.'
    ),
    'MERCHANT_INACTIVE': 'Compte marchand GeniusPay désactivé.',
}


class GeniusPayError(Exception):
    def __init__(self, message, code=None, http_status=None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def _env(name, default=''):
    """Lit le .env à chaque appel (le runserver ne recharge pas .env tout seul)."""
    env_file = Path(settings.BASE_DIR) / '.env'
    if env_file.is_file():
        try:
            from decouple import Config, RepositoryEnv
            value = Config(RepositoryEnv(str(env_file)))(name, default=default)
            if value not in (None, ''):
                return str(value).strip()
        except Exception:
            pass
    return str(getattr(settings, name, default) or default).strip()


def _headers():
    api_key = _env('GENIUSPAY_API_KEY')
    api_secret = _env('GENIUSPAY_API_SECRET')
    if not api_key or not api_secret:
        raise GeniusPayError(
            _MESSAGES_ERREUR['MISSING_API_KEY'],
            code='MISSING_API_KEY',
            http_status=401,
        )
    return {
        'X-API-Key': api_key,
        'X-API-Secret': api_secret,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }


def _base_url():
    return (
        _env('GENIUSPAY_BASE_URL', 'https://geniuspay.ci/api/v1/merchant')
        or 'https://geniuspay.ci/api/v1/merchant'
    ).rstrip('/')


def montant_xof(value) -> int:
    """Montant entier en XOF (l'API GeniusPay n'accepte pas les centimes)."""
    return int(Decimal(str(value or 0)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _parse_error(payload, http_status):
    if not isinstance(payload, dict):
        return GeniusPayError(
            'Réponse GeniusPay invalide.',
            http_status=http_status,
        )
    err = payload.get('error') or {}
    if isinstance(err, dict):
        code = err.get('code')
        message = err.get('message') or payload.get('message') or 'Erreur GeniusPay.'
    else:
        message = str(err) or 'Erreur GeniusPay.'
        code = None
    if code in _MESSAGES_ERREUR:
        message = _MESSAGES_ERREUR[code]
    return GeniusPayError(message, code=code, http_status=http_status)


def _request(method, path, *, json_body=None, params=None):
    url = f"{_base_url()}{path}"
    try:
        response = requests.request(
            method,
            url,
            headers=_headers(),
            json=json_body,
            params=params,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.exception('GeniusPay réseau: %s', exc)
        raise GeniusPayError(
            'Impossible de joindre GeniusPay. Réessayez dans un instant.',
        ) from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.status_code >= 400 or (
        isinstance(payload, dict) and payload.get('success') is False
    ):
        raise _parse_error(payload, response.status_code)

    if isinstance(payload, dict) and 'data' in payload:
        return payload['data']
    return payload


def initier_paiement(
    amount,
    *,
    description='',
    customer=None,
    metadata=None,
    success_url=None,
    error_url=None,
    currency='XOF',
):
    """
    Crée un paiement en mode checkout (sans payment_method).
    Retourne data: id, reference, checkout_url, status, ...
    """
    montant = montant_xof(amount)
    min_amount = int(getattr(settings, 'GENIUSPAY_MIN_AMOUNT', 200) or 200)
    if montant < min_amount:
        raise GeniusPayError(
            f'Le montant minimum GeniusPay est de {min_amount} FCFA.',
            code='VALIDATION_ERROR',
            http_status=422,
        )
    body = {
        'amount': montant,
        'currency': currency or 'XOF',
        'description': (description or '')[:500],
    }
    if customer:
        body['customer'] = {k: v for k, v in customer.items() if v}
    if metadata:
        body['metadata'] = metadata
    if success_url:
        body['success_url'] = success_url
    if error_url:
        body['error_url'] = error_url
    return _request('POST', '/payments', json_body=body)


def recuperer_paiement(reference: str):
    if not reference:
        raise GeniusPayError(
            'Référence de paiement manquante.',
            code='VALIDATION_ERROR',
            http_status=422,
        )
    ref = str(reference).strip()
    return _request('GET', f'/payments/{ref}')


def verifier_signature_webhook(raw_body: bytes, timestamp: str, signature: str) -> bool:
    """
    signature = HMAC-SHA256(timestamp + '.' + json_payload, secret)
    Utilise le corps brut, sans ré-encoder le JSON.
    """
    secret = _env('GENIUSPAY_WEBHOOK_SECRET')
    if not secret:
        logger.warning('GENIUSPAY_WEBHOOK_SECRET vide : webhook rejeté.')
        return False
    if not timestamp or not signature:
        return False
    try:
        ts = int(str(timestamp).strip())
    except (TypeError, ValueError):
        return False
    if abs(int(time.time()) - ts) > WEBHOOK_MAX_AGE_SECONDS:
        return False
    if isinstance(raw_body, bytes):
        payload = raw_body.decode('utf-8')
    else:
        payload = str(raw_body or '')
    expected = hmac.new(
        secret.encode('utf-8'),
        f'{ts}.{payload}'.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    provided = str(signature).strip()
    if provided.lower().startswith('sha256='):
        provided = provided.split('=', 1)[1]
    if len(provided) != len(expected):
        return False
    return hmac.compare_digest(expected, provided)
