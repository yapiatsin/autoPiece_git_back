from django.conf import settings


def pusher_config(request):
    """Expose la clé publique Pusher aux templates (jamais le secret)."""
    return {
        'PUSHER_KEY': getattr(settings, 'PUSHER_KEY', '') or '',
        'PUSHER_CLUSTER': getattr(settings, 'PUSHER_CLUSTER', 'eu') or 'eu',
    }
