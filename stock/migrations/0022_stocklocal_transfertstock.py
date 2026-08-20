# Generated manually for multi-location stock refactor

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import simple_history.models


class Migration(migrations.Migration):

    dependencies = [
        ('Userauths', '0010_alter_customuser_role_gestionnaire'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('stock', '0021_notification_creneau'),
    ]

    operations = [
        migrations.CreateModel(
            name='StockLocal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantite_disponible', models.PositiveIntegerField(default=0)),
                ('seuil_local', models.PositiveIntegerField(default=0)),
                ('emplacement', models.CharField(blank=True, default='', max_length=255)),
                ('date_maj', models.DateTimeField(auto_now=True)),
                ('local_entrepot', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stocks', to='Userauths.localentrepot')),
                ('piece', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stocks', to='stock.piece')),
            ],
            options={
                'verbose_name': 'Stock local',
                'verbose_name_plural': 'Stocks par localité',
            },
        ),
        migrations.CreateModel(
            name='HistoricalStockLocal',
            fields=[
                ('id', models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name='ID')),
                ('quantite_disponible', models.PositiveIntegerField(default=0)),
                ('seuil_local', models.PositiveIntegerField(default=0)),
                ('emplacement', models.CharField(blank=True, default='', max_length=255)),
                ('date_maj', models.DateTimeField(blank=True, editable=False)),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('history_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('local_entrepot', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='Userauths.localentrepot')),
                ('piece', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='stock.piece')),
            ],
            options={
                'verbose_name': 'historical Stock local',
                'verbose_name_plural': 'historical Stocks par localité',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.AddField(
            model_name='entrepiece',
            name='local_entrepot',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='entrees_stock', to='Userauths.localentrepot'),
        ),
        migrations.AddField(
            model_name='historicalentrepiece',
            name='local_entrepot',
            field=models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='Userauths.localentrepot'),
        ),
        migrations.AlterField(
            model_name='piece',
            name='emplacement',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AlterField(
            model_name='piece',
            name='seuil',
            field=models.PositiveIntegerField(default=0, help_text='Seuil catalogue (défaut si seuil local non défini)'),
        ),
        migrations.CreateModel(
            name='TransfertStock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('numero', models.CharField(max_length=30, unique=True)),
                ('quantite', models.PositiveIntegerField()),
                ('statut', models.CharField(choices=[('en_attente', 'En attente'), ('en_transit', 'En transit'), ('recu', 'Reçu'), ('annule', 'Annulé')], default='en_attente', max_length=15)),
                ('motif', models.TextField(blank=True)),
                ('date_demande', models.DateTimeField(auto_now_add=True)),
                ('date_envoi', models.DateTimeField(blank=True, null=True)),
                ('date_reception', models.DateTimeField(blank=True, null=True)),
                ('demandeur', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='transferts_demandes', to=settings.AUTH_USER_MODEL)),
                ('local_destination', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='transferts_entrants', to='Userauths.localentrepot')),
                ('local_source', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='transferts_sortants', to='Userauths.localentrepot')),
                ('piece', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='transferts', to='stock.piece')),
                ('receveur', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='transferts_recus', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-date_demande'],
            },
        ),
        migrations.CreateModel(
            name='HistoricalTransfertStock',
            fields=[
                ('id', models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name='ID')),
                ('numero', models.CharField(db_index=True, max_length=30)),
                ('quantite', models.PositiveIntegerField()),
                ('statut', models.CharField(choices=[('en_attente', 'En attente'), ('en_transit', 'En transit'), ('recu', 'Reçu'), ('annule', 'Annulé')], default='en_attente', max_length=15)),
                ('motif', models.TextField(blank=True)),
                ('date_demande', models.DateTimeField(blank=True, editable=False)),
                ('date_envoi', models.DateTimeField(blank=True, null=True)),
                ('date_reception', models.DateTimeField(blank=True, null=True)),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('demandeur', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('history_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('local_destination', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='Userauths.localentrepot')),
                ('local_source', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='Userauths.localentrepot')),
                ('piece', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='stock.piece')),
                ('receveur', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'historical transfert stock',
                'verbose_name_plural': 'historical transfert stocks',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.AddConstraint(
            model_name='transfertstock',
            constraint=models.CheckConstraint(
                condition=~models.Q(local_source=models.F('local_destination')),
                name='transfert_source_diff_destination',
            ),
        ),
        migrations.AddIndex(
            model_name='stocklocal',
            index=models.Index(fields=['piece', 'local_entrepot'], name='stock_stock_piece_i_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='stocklocal',
            unique_together={('piece', 'local_entrepot')},
        ),
    ]
