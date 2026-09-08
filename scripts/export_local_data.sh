#!/bin/bash
# Exporte les donnees de la base SQLite locale vers data_export.json, au format
# attendu par `loaddata` sur le VPS PostgreSQL.
#
# Tables techniques exclues : contenttypes et auth.permission sont recrees par
# `migrate` (les reimporter provoque des collisions de cles primaires) ;
# admin.logentry et sessions.session n'ont aucune valeur metier.
#
# Les cles primaires reelles sont conservees (pas de --natural-foreign) pour
# deux raisons :
#   - les tables d'audit simple_history contiennent des references vers des
#     enregistrements supprimes ; --natural-foreign echoue dessus, alors que
#     PostgreSQL les accepte (ces colonnes ont db_constraint=False) ;
#   - aucun groupe ni permission directe n'est utilise dans ce projet, les cles
#     naturelles n'apportent donc rien.
# Verifier ce dernier point avec scripts/clean_orphan_fks.py avant tout export.
#
# Usage, depuis la racine du projet :
#   ./scripts/export_local_data.sh
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python}"
[ -x env/bin/python ] && PYTHON="env/bin/python"
[ -x env/Scripts/python.exe ] && PYTHON="env/Scripts/python.exe"

# PYTHONUTF8=1 : sous Windows, --output ecrit sinon en cp1252 et echoue sur
# les emojis presents dans certaines fiches produit.
DB_ENGINE=sqlite PYTHONUTF8=1 "$PYTHON" manage.py dumpdata \
    --exclude contenttypes \
    --exclude auth.permission \
    --exclude admin.logentry \
    --exclude sessions.session \
    --indent 2 \
    --output data_export.json

echo "Export termine : data_export.json ($(du -h data_export.json | cut -f1))"
echo
echo "Etapes suivantes :"
echo "  scp data_export.json root@<IP_VPS>:/opt/autopiece/"
echo "  scp -r media/. root@<IP_VPS>:/opt/autopiece/media/"
echo "  ssh root@<IP_VPS>"
echo "    cd /opt/autopiece"
echo "    docker compose cp data_export.json autopiece_web:/tmp/data_export.json"
echo "    docker compose exec -T autopiece_web python manage.py loaddata /tmp/data_export.json"
