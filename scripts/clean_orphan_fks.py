"""Detecte (et corrige) les cles etrangeres orphelines de la base SQLite locale.

SQLite n'applique pas les contraintes de cle etrangere : des lignes peuvent
pointer vers un enregistrement supprime. PostgreSQL, lui, les applique, et
`dumpdata --natural-foreign` echoue des la premiere reference cassee. Ce script
doit donc etre passe avant la migration vers PostgreSQL.

    python scripts/clean_orphan_fks.py            # rapport seul, ne modifie rien
    python scripts/clean_orphan_fks.py --apply    # met les references cassees a NULL

Les colonnes non nullables sont signalees mais jamais modifiees : elles
demandent une decision metier (supprimer la ligne ou la rattacher ailleurs).
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "magazin_piece.settings")
django.setup()

from django.apps import apps  # noqa: E402
from django.conf import settings  # noqa: E402
from django.db.models import ForeignKey, OneToOneField  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="applique les corrections au lieu de seulement les lister")
    args = parser.parse_args()

    if args.apply:
        db_path = Path(settings.DATABASES["default"]["NAME"])
        if db_path.exists():
            backup = db_path.with_suffix(db_path.suffix + ".before-cleanup")
            shutil.copy2(db_path, backup)
            print(f"Sauvegarde de securite : {backup}\n")

    # Les cles primaires valides sont mises en cache : un modele peut etre la
    # cible de plusieurs cles etrangeres.
    valid_pks = {}
    fixed = blocked = 0

    for model in apps.get_models():
        for field in model._meta.get_fields():
            if not isinstance(field, (ForeignKey, OneToOneField)):
                continue
            target = field.related_model
            if target is None or target._meta.abstract:
                continue

            label = target._meta.label
            if label not in valid_pks:
                valid_pks[label] = set(target._base_manager.values_list("pk", flat=True))

            column = field.attname
            orphans = (model._base_manager
                       .exclude(**{column: None})
                       .exclude(**{f"{column}__in": valid_pks[label]}))
            count = orphans.count()
            if not count:
                continue

            origin = f"{model._meta.label}.{column} -> {label}"
            if field.null:
                if args.apply:
                    orphans.update(**{column: None})
                    print(f"CORRIGE  {origin} : {count} ligne(s) mises a NULL")
                else:
                    print(f"A CORRIGER  {origin} : {count} ligne(s) seront mises a NULL")
                fixed += count
            else:
                print(f"BLOQUANT  {origin} : {count} ligne(s), colonne NON nullable "
                      f"— intervention manuelle requise")
                blocked += count

    print()
    if not fixed and not blocked:
        print("Aucune reference orpheline. La base est prete pour PostgreSQL.")
    elif args.apply:
        print(f"{fixed} reference(s) corrigee(s), {blocked} bloquante(s).")
    else:
        print(f"{fixed} reference(s) corrigeable(s), {blocked} bloquante(s). "
              f"Relancer avec --apply pour appliquer.")

    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
