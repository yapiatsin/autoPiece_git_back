from django.db import migrations


class Migration(migrations.Migration):
    """Migration neutralisee.

    Cette migration ajoutait `actif` sur Categorie et HistoricalCategorie. Le
    champ est desormais deja cree par 0001_initial (regenere apres coup), si
    bien qu'un `migrate` sur une base neuve echouait avec :

        ProgrammingError: column "actif" of relation "stock_categorie"
        already exists

    Le fichier est conserve, sans operation, parce qu'il est deja enregistre
    comme applique dans les bases existantes : le supprimer casserait leur
    historique de migrations.
    """

    dependencies = [
        ('stock', '0001_initial'),
    ]

    operations = []
