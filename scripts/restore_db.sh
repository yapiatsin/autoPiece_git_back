#!/bin/bash
# Restaure un dump PostgreSQL produit par backup_db.sh.
#   ./scripts/restore_db.sh backups/db-20260908-020000.sql.gz
# ATTENTION : ecrase integralement la base actuelle.
set -euo pipefail

DUMP="${1:?Usage: restore_db.sh <fichier.sql.gz>}"
cd "$(dirname "$0")/.."

DB_NAME="${DB_NAME:-autopiece}"
DB_USER="${DB_USER:-autopiece}"

read -r -p "Ecraser la base '${DB_NAME}' avec ${DUMP} ? [oui/NON] " reply
[ "$reply" = "oui" ] || { echo "Annule."; exit 1; }

echo "[restore] Arret de l'application..."
docker compose stop autopiece-web

echo "[restore] Recreation de la base..."
docker compose exec -T autopiece-db psql -U "$DB_USER" -d postgres \
  -c "DROP DATABASE IF EXISTS \"${DB_NAME}\";"
docker compose exec -T autopiece-db psql -U "$DB_USER" -d postgres \
  -c "CREATE DATABASE \"${DB_NAME}\" OWNER \"${DB_USER}\";"

echo "[restore] Chargement du dump..."
gunzip -c "$DUMP" | docker compose exec -T autopiece-db psql -U "$DB_USER" -d "$DB_NAME"

echo "[restore] Redemarrage de l'application..."
docker compose up -d autopiece-web
echo "[restore] Termine."
