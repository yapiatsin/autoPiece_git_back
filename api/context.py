"""Contexte requête API mobile (localité, panier)."""
from django.db.models import Sum

from Userauths.models import LocalEntrepot
from stock.models import PanierItem

from ecom.services import get_local_from_code, queryset_panier_online_actif

LOCAL_HEADER = 'HTTP_X_ECOM_LOCAL'


def get_local_code_from_request(request) -> str:
    """Code localité depuis header, query ou profil utilisateur."""
    django_request = getattr(request, '_request', request)
    code = (
        django_request.META.get(LOCAL_HEADER)
        or request.query_params.get('local')
        or ''
    ).strip()
    if code:
        return code
    user = getattr(request, 'user', None)
    if user and getattr(user, 'is_authenticated', False) and user.local_entrepot_id:
        return str(user.local_entrepot.code)
    return ''


def get_local_from_request(request) -> LocalEntrepot | None:
    code = get_local_code_from_request(request)
    if code:
        local = get_local_from_code(code)
        if local:
            return local
    user = getattr(request, 'user', None)
    if user and getattr(user, 'is_authenticated', False):
        return getattr(user, 'local_entrepot', None)
    return None


def local_payload(local: LocalEntrepot | None) -> dict | None:
    if not local:
        return None
    return {'code': str(local.code), 'nom': local.nom}


def get_cart_count(user, local: LocalEntrepot | None) -> int:
    if not user or not getattr(user, 'is_authenticated', False) or not local:
        return 0
    panier = queryset_panier_online_actif(user, local).first()
    if not panier:
        return 0
    return (
        PanierItem.objects.filter(panier=panier).aggregate(total=Sum('quantite'))['total'] or 0
    )


def django_request(request):
    """Requête Django sous-jacente (GET session pour services ecom)."""
    return getattr(request, '_request', request)
