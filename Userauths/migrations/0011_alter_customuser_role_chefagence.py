from django.db import migrations, models


class Migration(migrations.Migration):
    """Ajoute le rôle « chef agence » aux choix de CustomUser.role."""

    dependencies = [
        ('Userauths', '0010_alter_customuser_role_gestionnaire'),
    ]

    _ROLE_CHOICES = [
        ('accueil',      'Service Accueil'),
        ('caissier',     'Caissier(ère)'),
        ('livreur',      'Livreur(euse)'),
        ('chefagence',   'Chef agence'),
        ('gestionnaire', 'Gestionnaire de stock'),
        ('admin',        'Administrateur'),
        ('utilisateur',  'Utilisateur'),
    ]

    operations = [
        migrations.AlterField(
            model_name='customuser',
            name='role',
            field=models.CharField(
                choices=_ROLE_CHOICES,
                default='caissier',
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='historicalcustomuser',
            name='role',
            field=models.CharField(
                choices=_ROLE_CHOICES,
                default='caissier',
                max_length=20,
            ),
        ),
    ]
