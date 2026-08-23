from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_moyen_geniuspay(apps, schema_editor):
    MoyenPaiement = apps.get_model('stock', 'MoyenPaiement')
    MoyenPaiement.objects.get_or_create(
        code='geniuspay',
        defaults={'nom': 'Paiement numérique', 'actif': True},
    )


def unseed_moyen_geniuspay(apps, schema_editor):
    MoyenPaiement = apps.get_model('stock', 'MoyenPaiement')
    MoyenPaiement.objects.filter(code='geniuspay').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0042_zones_livraison_panier_adresse'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='GeniusPayPaiement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reference', models.CharField(db_index=True, max_length=64, unique=True)),
                ('source', models.CharField(choices=[('ecom', 'E-commerce'), ('caisse', 'Caisse')], max_length=16)),
                ('statut', models.CharField(choices=[('pending', 'En attente'), ('processing', 'En cours'), ('completed', 'Complété'), ('failed', 'Échoué'), ('cancelled', 'Annulé'), ('expired', 'Expiré')], default='pending', max_length=20)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('checkout_url', models.TextField(blank=True, default='')),
                ('environment', models.CharField(blank=True, default='', max_length=20)),
                ('appliquer_tva', models.BooleanField(default=False)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('raw_response', models.JSONField(blank=True, default=dict)),
                ('date_creation', models.DateTimeField(auto_now_add=True)),
                ('date_maj', models.DateTimeField(auto_now=True)),
                ('caissier', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='paiements_geniuspay_caisse', to=settings.AUTH_USER_MODEL)),
                ('commande', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='paiements_geniuspay', to='stock.commande')),
            ],
            options={
                'verbose_name': 'Paiement GeniusPay',
                'verbose_name_plural': 'Paiements GeniusPay',
                'ordering': ['-date_creation'],
            },
        ),
        migrations.RunPython(seed_moyen_geniuspay, unseed_moyen_geniuspay),
    ]
