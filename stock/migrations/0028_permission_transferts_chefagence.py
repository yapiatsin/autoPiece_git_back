"""Accorde le menu Transferts aux chefs d'agence."""

from django.db import migrations


def grant_chefagence(apps, schema_editor):
    CustomPermission = apps.get_model('Userauths', 'CustomPermission')
    CustomUser = apps.get_model('Userauths', 'CustomUser')
    perm = CustomPermission.objects.filter(url='liste_transferts').first()
    if not perm:
        return
    for user in CustomUser.objects.filter(role='chefagence', is_active=True):
        user.custom_permissions.add(perm)


def revoke_chefagence(apps, schema_editor):
    CustomPermission = apps.get_model('Userauths', 'CustomPermission')
    CustomUser = apps.get_model('Userauths', 'CustomUser')
    perm = CustomPermission.objects.filter(url='liste_transferts').first()
    if not perm:
        return
    for user in CustomUser.objects.filter(role='chefagence'):
        user.custom_permissions.remove(perm)


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0027_demande_transfert_workflow'),
        ('Userauths', '0011_alter_customuser_role_chefagence'),
    ]

    operations = [
        migrations.RunPython(grant_chefagence, revoke_chefagence),
    ]
