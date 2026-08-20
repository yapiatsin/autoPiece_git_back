"""Ajoute la permission menu « Transferts inter-localités » (Stocks)."""

from django.db import migrations


def add_transfert_permission(apps, schema_editor):
    TypeCustomPermission = apps.get_model('Userauths', 'TypeCustomPermission')
    CustomPermission = apps.get_model('Userauths', 'CustomPermission')
    CustomUser = apps.get_model('Userauths', 'CustomUser')

    category, _ = TypeCustomPermission.objects.get_or_create(categorie='Stocks')
    perm, created = CustomPermission.objects.get_or_create(
        url='liste_transferts',
        defaults={
            'name': 'Transferts inter-localités',
            'categorie': category,
        },
    )
    if not created:
        return

    for role in ('admin', 'gestionnaire'):
        for user in CustomUser.objects.filter(role=role, is_active=True):
            user.custom_permissions.add(perm)


def remove_transfert_permission(apps, schema_editor):
    CustomPermission = apps.get_model('Userauths', 'CustomPermission')
    CustomPermission.objects.filter(url='liste_transferts').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0025_rename_stock_stock_piece_i_idx_stock_stock_piece_i_87bb66_idx_and_more'),
    ]

    operations = [
        migrations.RunPython(add_transfert_permission, remove_transfert_permission),
    ]
