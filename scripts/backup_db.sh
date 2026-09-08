#!/bin/bash
# Sauvegarde la base PostgreSQL et les medias dans ./backups.
# A lancer depuis /opt/autopiece. Exemple de planification quotidienne :
#   0 2 * * * cd /opt/autopiece && ./scripts/backup_db.sh >> backups/cron.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p backups

STAMP="$(date +%Y%m%d-%H%M%S)"

# Les identifiants sont lus dans le .env, pas dans l'environnement du shell :
# cron n'herite de rien, et une valeur codee en dur ferait echouer la sauvegarde
# le jour ou DB_USER change — exactement le moment ou l'on en aurait besoin.
env_value() {
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" .env 2>/dev/null | head -1
}
DB_NAME="${DB_NAME:-$(env_value DB_NAME)}"
DB_USER="${DB_USER:-$(env_value DB_USER)}"
DB_NAME="${DB_NAME:-autopiece}"
DB_USER="${DB_USER:-autopiece}"

echo "[backup] Dump PostgreSQL -> backups/db-${STAMP}.sql.gz"
docker compose exec -T autopiece-db pg_dump -U "$DB_USER" -d "$DB_NAME" \
  | gzip > "backups/db-${STAMP}.sql.gz"

echo "[backup] Archive des medias -> backups/media-${STAMP}.tar.gz"
tar czf "backups/media-${STAMP}.tar.gz" media

# Retention : on ne garde que les 14 dernieres sauvegardes de chaque type.
ls -1t backups/db-*.sql.gz    | tail -n +15 | xargs -r rm --
ls -1t backups/media-*.tar.gz | tail -n +15 | xargs -r rm --

echo "[backup] Termine."
