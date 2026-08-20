from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0023_migrate_piece_stock_to_stocklocal'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='historicalpiece',
            name='local_piece',
        ),
        migrations.RemoveField(
            model_name='historicalpiece',
            name='quantite_disponible',
        ),
        migrations.RemoveField(
            model_name='piece',
            name='local_piece',
        ),
        migrations.RemoveField(
            model_name='piece',
            name='quantite_disponible',
        ),
        migrations.AlterField(
            model_name='entrepiece',
            name='local_entrepot',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='entrees_stock',
                to='Userauths.localentrepot',
            ),
        ),
    ]
