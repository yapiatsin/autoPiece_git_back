from django.db import migrations, models


class Migration(migrations.Migration):
    """Ajoute le rôle 'gestionnaire' aux choix de CustomUser.role."""

    dependencies = [
        ('Userauths', '0009_rename_siteuser_localentrepot_and_more'),
    ]

    _ROLE_CHOICES = [
        ('accueil',      'Service Accueil'),
        ('caissier',     'Caissier(ère)'),
        ('livreur',      'Livreur(euse)'),
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
