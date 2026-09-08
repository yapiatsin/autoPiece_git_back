"""Vide la base de production puis y charge un export produit par dumpdata.

Pourquoi ce script plutot qu'un simple `loaddata` : au premier `migrate`, le
signal post_migrate de l'application `stock` insere des donnees par defaut
(categories, moyens de paiement, bareme de timbres...). Ces lignes occupent les
memes contraintes d'unicite que les donnees exportees mais avec d'autres cles
primaires, et `loaddata` echoue alors sur :

    duplicate key value violates unique constraint "stock_moyenpaiement_nom_key"

`manage.py flush` ne convient pas non plus : il re-emet post_migrate et
reinsere aussitot ces memes valeurs par defaut. On vide donc les tables
directement, on charge l'export, puis on relance `migrate` pour reconstruire
les types de contenu et les permissions (le seeder, base sur get_or_create,
retrouve alors les lignes importees et n'ajoute rien).

    docker compose exec -T autopiece-web python scripts/reset_and_load.py /tmp/data.json --yes

ATTENTION : toutes les donnees applicatives presentes sont detruites.
"""
import argparse
import os
import sys
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "magazin_piece.settings")
django.setup()

from django.core.management import call_command  # noqa: E402
from django.core.management.color import no_style  # noqa: E402
from django.db import connection  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", help="chemin du fichier JSON produit par dumpdata")
    parser.add_argument("--yes", action="store_true",
                        help="ne pas demander de confirmation")
    args = parser.parse_args()

    fixture = Path(args.fixture)
    if not fixture.is_file():
        sys.exit(f"Fichier introuvable : {fixture}")

    db = connection.settings_dict
    target = f"{db['NAME']} sur {db['HOST'] or 'local'}"
    if not args.yes:
        reply = input(f"Effacer toutes les donnees de '{target}' ? [oui/NON] ")
        if reply.strip().lower() != "oui":
            sys.exit("Annule.")

    tables = connection.introspection.django_table_names(only_existing=True,
                                                         include_views=False)
    print(f"[1/3] Vidage de {len(tables)} tables...")
    sql = connection.ops.sql_flush(no_style(), tables,
                                   reset_sequences=True, allow_cascade=True)
    connection.ops.execute_sql_flush(sql)

    print(f"[2/3] Chargement de {fixture}...")
    call_command("loaddata", str(fixture), verbosity=2)

    # post_migrate recree les ContentType et Permission supprimes par le vidage,
    # et le seeder retrouve les lignes importees sans les dupliquer.
    print("[3/3] Reconstruction des types de contenu et des permissions...")
    call_command("migrate", verbosity=0)

    print("\nImport termine.")


if __name__ == "__main__":
    main()
