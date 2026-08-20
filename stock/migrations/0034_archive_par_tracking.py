import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Userauths', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('stock', '0033_stocklocal_active_sortie'),
    ]

    operations = [
        migrations.AddField(
            model_name='piece',
            name='archive_par',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='pieces_archivees_catalogue',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='piece',
            name='archive_le',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='piece',
            name='archive_local_entrepot',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='pieces_archivees_catalogue',
                to='Userauths.localentrepot',
            ),
        ),
        migrations.AddField(
            model_name='historicalpiece',
            name='archive_par',
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name='+',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='historicalpiece',
            name='archive_le',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='historicalpiece',
            name='archive_local_entrepot',
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name='+',
                to='Userauths.localentrepot',
            ),
        ),
        migrations.AddField(
            model_name='stocklocal',
            name='archive_par',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='stocks_archives',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='stocklocal',
            name='archive_le',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='historicalstocklocal',
            name='archive_par',
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name='+',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='historicalstocklocal',
            name='archive_le',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
