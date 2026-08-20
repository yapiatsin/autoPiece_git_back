from decimal import Decimal

from django.db import migrations


ABIDJAN_COMMUNES = [
    'Abobo',
    'Adjamé',
    'Attécoubé',
    'Cocody',
    'Koumassi',
    'Marcory',
    'Plateau',
    'Port-Bouët',
    'Treichville',
    'Yopougon',
]


def seed_zones(apps, schema_editor):
    PaysLivraison = apps.get_model('ecom', 'PaysLivraison')
    VilleLivraison = apps.get_model('ecom', 'VilleLivraison')
    CommuneLivraison = apps.get_model('ecom', 'CommuneLivraison')

    pays, _ = PaysLivraison.objects.get_or_create(
        code='CI',
        defaults={'nom': "Côte d'Ivoire", 'actif': True},
    )
    if not pays.actif:
        pays.actif = True
        pays.save(update_fields=['actif'])

    ville, _ = VilleLivraison.objects.get_or_create(
        pays=pays,
        nom='Abidjan',
        defaults={'frais_livraison': Decimal('2000.00'), 'actif': True},
    )
    for nom in ABIDJAN_COMMUNES:
        CommuneLivraison.objects.get_or_create(
            ville=ville,
            nom=nom,
            defaults={'actif': True},
        )


def unseed_zones(apps, schema_editor):
    PaysLivraison = apps.get_model('ecom', 'PaysLivraison')
    PaysLivraison.objects.filter(code='CI').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('ecom', '0005_zones_livraison_panier_adresse'),
    ]

    operations = [
        migrations.RunPython(seed_zones, unseed_zones),
    ]
