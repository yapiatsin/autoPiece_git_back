"""Client HTTP FNE — Facture Normalisée Électronique de la DGI (clé uniquement côté serveur).

Référence : « Procédure d'interfaçage des entreprises par API » (DGI, mai 2025).
  POST $url/external/invoices/sign          certification d'une facture de vente
  POST $url/external/invoices/{id}/refund   certification d'une facture d'avoir
Authentification : Authorization: Bearer <clé API de l'espace FNE, onglet Paramétrage>.
"""
from __future__ import annotations

import logging

import requests

# Même lecture du .env à chaque appel que GeniusPay : le runserver ne recharge
# pas le .env tout seul, et la clé change entre l'environnement de test et la prod.
from stock.geniuspay import _env

logger = logging.getLogger(__name__)

URL_TEST = 'http://54.247.95.108/ws'
TIMEOUT = 45

# Valeurs admises par l'API (annexe 1 de la procédure).
TAXES = ('TVA', 'TVAB', 'TVAC', 'TVAD', 'TVAE')
PAYMENT_METHODS = ('cash', 'card', 'check', 'mobile-money', 'transfer', 'deferred')
TEMPLATES = ('B2C', 'B2B', 'B2G', 'B2F')

_MESSAGES_ERREUR = {
    401: (
        'Clé API FNE refusée. Vérifiez FNE_API_KEY dans le fichier .env '
        '(espace FNE > Paramétrage). La clé de test ne fonctionne pas en production.'
    ),
    500: (
        'La plateforme FNE a refusé la signature (HTTP 500). Cause fréquente : '
        'solde de stickers à 0 — achetez des stickers dans l\'espace FNE '
        '(Gestion des stickers), puis relancez le bouton FNE.'
    ),
}

# Traductions des refus de validation les plus courants (procédure DGI mai 2025).
_TRADUCTIONS = {
    'Establishment is invalid': (
        "Établissement FNE inconnu : FNE_ETABLISSEMENT doit reprendre exactement "
        "le nom déclaré dans l'espace FNE (ex. « P & B AUTO-PIECES »)."
    ),
    'Point of sale is invalid': (
        "Point de vente FNE inconnu : le champ « Point de vente FNE » de la localité "
        "doit reprendre exactement un point de vente déclaré dans l'espace FNE."
    ),
    'Point of sale is not valid': (
        "Point de vente FNE inconnu : le champ « Point de vente FNE » de la localité "
        "doit reprendre exactement un point de vente déclaré dans l'espace FNE."
    ),
    'Error signing invoice': (
        "La DGI n'a pas pu signer la facture (Error signing invoice). "
        "Vérifiez le solde de stickers (espace FNE > Gestion des stickers) : "
        "un solde à 0 bloque toute certification. Puis relancez."
    ),
    'Invalid API Key': (
        'Clé API FNE refusée (Invalid API Key). Vérifiez FNE_API_KEY '
        'dans le fichier .env (espace FNE > Paramétrage).'
    ),
    'invoice_signing_error': (
        "La DGI n'a pas pu signer la facture. Vérifiez le solde de stickers "
        "(espace FNE > Gestion des stickers), puis relancez."
    ),
}


class FNEError(Exception):
    def __init__(self, message, http_status=None, details=None):
        super().__init__(message)
        self.http_status = http_status
        self.details = details or {}


def est_configuree() -> bool:
    return bool(_env('FNE_API_KEY'))


def base_url() -> str:
    return (_env('FNE_BASE_URL', URL_TEST) or URL_TEST).rstrip('/')


def environnement() -> str:
    return 'test' if base_url() == URL_TEST.rstrip('/') else 'production'


def _headers():
    api_key = _env('FNE_API_KEY')
    if not api_key:
        raise FNEError(
            'Clé API FNE manquante. Renseignez FNE_API_KEY dans le fichier .env.',
            http_status=401,
        )
    return {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }


def _aplatir_erreurs(errors) -> list[str]:
    """{"champ": {"regle": "message"}} → ["message", …] (format des refus 400)."""
    messages = []
    if isinstance(errors, dict):
        for value in errors.values():
            if isinstance(value, dict):
                messages.extend(str(v) for v in value.values() if v)
            elif isinstance(value, (list, tuple)):
                messages.extend(str(v) for v in value if v)
            elif value:
                messages.append(str(value))
    elif isinstance(errors, (list, tuple)):
        messages.extend(str(v) for v in errors if v)
    return messages


def _parse_error(payload, http_status) -> FNEError:
    if not isinstance(payload, dict):
        payload = {}
    details = payload.get('errors') or {}
    messages = [_TRADUCTIONS.get(m, m) for m in _aplatir_erreurs(details)]
    brut = str(payload.get('message') or '').strip()
    err_code = str(payload.get('error') or '').strip()
    if messages:
        message = ' ; '.join(dict.fromkeys(messages))
    elif brut in _TRADUCTIONS:
        message = _TRADUCTIONS[brut]
    elif err_code in _TRADUCTIONS:
        message = _TRADUCTIONS[err_code]
    elif http_status in _MESSAGES_ERREUR:
        # 500 générique : préférer le message stickers si la DGI signale une
        # erreur de signature plutôt que « plateforme indisponible ».
        if http_status == 500 and (
            'sign' in brut.lower() or err_code == 'invoice_signing_error'
        ):
            message = _TRADUCTIONS['Error signing invoice']
        else:
            message = _MESSAGES_ERREUR[http_status]
    else:
        message = brut or f'Erreur FNE (HTTP {http_status}).'
    return FNEError(message, http_status=http_status, details=details)


def _post(path, body):
    url = f'{base_url()}{path}'
    try:
        response = requests.post(url, headers=_headers(), json=body, timeout=TIMEOUT)
    except requests.Timeout as exc:
        logger.error('FNE délai dépassé %s', url)
        # La DGI a pu certifier sans que la réponse nous parvienne : relancer
        # aveuglément créerait une seconde facture dans la série numérotée.
        raise FNEError(
            "La plateforme FNE n'a pas répondu à temps (cause fréquente : solde de "
            "stickers à 0, ou réseau lent). Vérifiez dans l'espace FNE si la facture "
            "a déjà été émise avant de relancer la certification (évite un doublon "
            "dans la série numérotée).",
        ) from exc
    except requests.RequestException as exc:
        logger.exception('FNE réseau: %s', exc)
        raise FNEError(
            'Impossible de joindre la plateforme FNE. Réessayez dans un instant.',
        ) from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.status_code >= 400:
        logger.warning(
            'FNE erreur POST %s status=%s payload=%s',
            url,
            response.status_code,
            payload or (response.text or '')[:500],
        )
        raise _parse_error(payload, response.status_code)
    return payload if isinstance(payload, dict) else {}


def certifier_facture(body: dict) -> dict:
    """
    Certifie une facture de vente (API #1).
    Retourne : ncc, reference, token (URL de vérification à mettre en QR code),
    warning, balance_sticker, invoice {id, items[{id, …}], amount, vatAmount, fiscalStamp, …}.
    """
    return _post('/external/invoices/sign', body)


def certifier_avoir(invoice_id: str, items: list[dict]) -> dict:
    """
    Certifie une facture d'avoir (API #2) sur une facture déjà certifiée.
    `items` : [{"id": <id de l'article dans invoice.items>, "quantity": n}, …].
    """
    if not invoice_id:
        raise FNEError("Identifiant de la facture FNE d'origine manquant.")
    return _post(f'/external/invoices/{invoice_id}/refund', {'items': items})
