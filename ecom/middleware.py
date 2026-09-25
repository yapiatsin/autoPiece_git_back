"""
Navigation fluide de la boutique (static/e_assets/js/ecom-spa-nav.js).

Une requête HTMX suit les redirections toute seule. Si l'une d'elles sort de la boutique
(connexion, back-office, passerelle de paiement…), la page finale n'a pas de #ecom-main
et le navigateur devrait la redemander : la chaîne de redirections, parfois avec effets
de bord (création de panier…), serait jouée deux fois. On transforme donc ces redirections
en en-tête ``HX-Redirect`` : HTMX fait une seule navigation classique vers la cible.
"""
import re
from urllib.parse import urlsplit

from django.http import HttpResponse

# Mêmes exclusions que EXCLUDE_PATH_RE dans ecom-spa-nav.js
HORS_BOUTIQUE_RE = re.compile(
    r'^/('
    r'facture/|checkout/|commande/valider|commande/[^/]+/payer|paiement/'
    r'|authentification/|accounts/|i18n/|admin/|stocks/|mag/|livraison/'
    r'|api/|webhooks/|media/|static/'
    r')',
    re.IGNORECASE,
)
REDIRECT_CODES = {301, 302, 303, 307, 308}


def _sort_de_la_boutique(request, location: str) -> bool:
    parts = urlsplit(location)
    if parts.netloc and parts.netloc != request.get_host():
        return True
    return bool(HORS_BOUTIQUE_RE.match(parts.path or '/'))


class HtmxRedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Le back-office (mag-spa-nav.js) utilise aussi HTMX : ne toucher qu'aux requêtes
        # parties d'une page de la boutique.
        page = request.headers.get('HX-Current-URL', '')
        if (
            request.headers.get('HX-Request') == 'true'
            and page
            and not _sort_de_la_boutique(request, page)
            and response.status_code in REDIRECT_CODES
            and response.has_header('Location')
            and _sort_de_la_boutique(request, response['Location'])
        ):
            hx = HttpResponse(status=200)
            hx['HX-Redirect'] = response['Location']
            for cookie in response.cookies.values():
                hx.cookies[cookie.key] = cookie
            return hx
        return response
