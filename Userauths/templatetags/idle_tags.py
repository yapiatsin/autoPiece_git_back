"""{% idle_logout_script %} : déconnexion automatique après inactivité (utilisateurs connectés)."""
from django import template
from django.conf import settings
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import format_html

register = template.Library()


@register.simple_tag(takes_context=True)
def idle_logout_script(context):
    request = context.get('request')
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return ''
    return format_html(
        '<script src="{}?v=1" data-timeout="{}" data-warning="120" '
        'data-keepalive-url="{}" data-logout-url="{}"></script>',
        static('apps/assets/js/idle-logout.js'),
        int(getattr(settings, 'IDLE_TIMEOUT_SECONDS', 30 * 60)),
        reverse('session_keepalive'),
        reverse('deconnexion'),
    )
