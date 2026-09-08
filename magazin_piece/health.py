"""Sonde de sante : verifie que Django repond et que la base est joignable."""
from django.db import connections
from django.db.utils import OperationalError
from django.http import JsonResponse


def healthz(request):
    """Retourne 200 si la base repond, 503 sinon (lu par Docker et Caddy)."""
    try:
        connections["default"].cursor()
    except OperationalError as exc:
        return JsonResponse({"status": "error", "database": str(exc)}, status=503)
    return JsonResponse({"status": "ok"})
