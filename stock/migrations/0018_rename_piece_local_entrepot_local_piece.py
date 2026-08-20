from django.db import migrations


class Migration(migrations.Migration):
    """Renomme Piece.local_entrepot → Piece.local_piece (+ modèle historique)."""

    dependencies = [
        ('stock', '0017_historicalpanier_local_entrepot_and_more'),
    ]

    operations = [
        migrations.RenameField(
            model_name='piece',
            old_name='local_entrepot',
            new_name='local_piece',
        ),
        migrations.RenameField(
            model_name='historicalpiece',
            old_name='local_entrepot',
            new_name='local_piece',
        ),
    ]
