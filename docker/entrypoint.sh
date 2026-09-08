#!/bin/sh
# Prepare l'application avant de ceder la main a gunicorn.
set -e

echo "[entrypoint] Attente de la base de donnees..."
python - <<'PYEOF'
import os
import sys
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "magazin_piece.settings")
django.setup()

from django.db import connections
from django.db.utils import OperationalError

deadline = time.time() + 60
while True:
    try:
        connections["default"].cursor()
        break
    except OperationalError as exc:
        if time.time() > deadline:
            sys.exit(f"Base injoignable apres 60s : {exc}")
        time.sleep(2)
print("Base de donnees prete.")
PYEOF

echo "[entrypoint] Application des migrations..."
python manage.py migrate --noinput

echo "[entrypoint] Collecte des fichiers statiques..."
python manage.py collectstatic --noinput --clear

echo "[entrypoint] Compilation des traductions..."
python manage.py compilemessages 2>/dev/null || echo "  (ignoree)"

# Cree un compte administrateur au premier demarrage si les trois variables
# DJANGO_SUPERUSER_* sont fournies. Sinon l'etape est ignoree en silence.
if [ -n "$DJANGO_SUPERUSER_PASSWORD" ] && [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
    echo "[entrypoint] Verification du compte administrateur..."
    python manage.py createsuperuser --noinput \
        --username "$DJANGO_SUPERUSER_USERNAME" \
        --email "${DJANGO_SUPERUSER_EMAIL:-admin@example.com}" 2>/dev/null \
        || echo "  (le compte existe deja)"
fi

echo "[entrypoint] Demarrage : $*"
exec "$@"
