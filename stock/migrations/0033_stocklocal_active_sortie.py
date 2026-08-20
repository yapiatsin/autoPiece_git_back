from django.db import migrations, models


def propager_active_sortie_vers_stocklocal(apps, schema_editor):
    Piece = apps.get_model('stock', 'Piece')
    StockLocal = apps.get_model('stock', 'StockLocal')
    for stock in StockLocal.objects.select_related('piece').iterator():
        piece_active = stock.piece.active_sortie
        stock.active_sortie = False if piece_active is False else True
        stock.save(update_fields=['active_sortie'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0032_alter_baremetimbre_montant_max_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='stocklocal',
            name='active_sortie',
            field=models.BooleanField(
                default=True,
                help_text='Si False, la pièce est masquée à la vente dans cette localité uniquement.',
            ),
        ),
        migrations.AddField(
            model_name='historicalstocklocal',
            name='active_sortie',
            field=models.BooleanField(
                default=True,
                help_text='Si False, la pièce est masquée à la vente dans cette localité uniquement.',
            ),
        ),
        migrations.RunPython(propager_active_sortie_vers_stocklocal, noop),
    ]
