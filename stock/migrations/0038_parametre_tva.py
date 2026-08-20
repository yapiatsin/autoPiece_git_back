# Generated manually — TVA optionnelle en caisse

from decimal import Decimal

import simple_history.models
from django.conf import settings
from django.db import migrations, models


def creer_parametre_tva_defaut(apps, schema_editor):
    ParametreTVA = apps.get_model('stock', 'ParametreTVA')
    if not ParametreTVA.objects.exists():
        ParametreTVA.objects.create(active=False, taux=Decimal('18.00'))


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0037_alter_historicalpiece_active_sortie_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ParametreTVA',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('active', models.BooleanField(
                    default=False,
                    help_text="Si activé, la case TVA apparaît en caisse lors du paiement.",
                )),
                ('taux', models.DecimalField(
                    decimal_places=2,
                    default=Decimal('18.00'),
                    help_text='Taux de TVA en pourcentage (ex. 18 pour 18 %).',
                    max_digits=5,
                )),
                ('date_maj', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Paramètre TVA',
                'verbose_name_plural': 'Paramètres TVA',
            },
        ),
        migrations.CreateModel(
            name='HistoricalParametreTVA',
            fields=[
                ('id', models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name='ID')),
                ('active', models.BooleanField(
                    default=False,
                    help_text="Si activé, la case TVA apparaît en caisse lors du paiement.",
                )),
                ('taux', models.DecimalField(
                    decimal_places=2,
                    default=Decimal('18.00'),
                    help_text='Taux de TVA en pourcentage (ex. 18 pour 18 %).',
                    max_digits=5,
                )),
                ('date_maj', models.DateTimeField(blank=True, editable=False)),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('history_user', models.ForeignKey(
                    null=True, on_delete=models.deletion.SET_NULL, related_name='+',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'historical Paramètre TVA',
                'verbose_name_plural': 'historical Paramètres TVA',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.AddField(
            model_name='commande',
            name='montant_tva',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Montant TVA appliqué au paiement (optionnel).',
                max_digits=10,
            ),
        ),
        migrations.AddField(
            model_name='commande',
            name='tva_appliquee',
            field=models.BooleanField(
                default=False,
                help_text='Indique si la TVA a été cochée et appliquée au paiement.',
            ),
        ),
        migrations.AddField(
            model_name='historicalcommande',
            name='montant_tva',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Montant TVA appliqué au paiement (optionnel).',
                max_digits=10,
            ),
        ),
        migrations.AddField(
            model_name='historicalcommande',
            name='tva_appliquee',
            field=models.BooleanField(
                default=False,
                help_text='Indique si la TVA a été cochée et appliquée au paiement.',
            ),
        ),
        migrations.RunPython(creer_parametre_tva_defaut, migrations.RunPython.noop),
    ]
