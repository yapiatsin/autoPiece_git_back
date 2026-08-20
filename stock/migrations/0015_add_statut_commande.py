# Generated manually - statut_commande pour Commande

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0014_historicalpanier_nom_client_panier_nom_client'),
    ]

    operations = [
        migrations.AddField(
            model_name='commande',
            name='statut_commande',
            field=models.CharField(
                choices=[
                    ('en_attente', 'En attente'),
                    ('valider', 'Validée'),
                    ('annuler', 'Annulée'),
                    ('livrer', 'Livrée'),
                ],
                default='en_attente',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='historicalcommande',
            name='statut_commande',
            field=models.CharField(
                choices=[
                    ('en_attente', 'En attente'),
                    ('valider', 'Validée'),
                    ('annuler', 'Annulée'),
                    ('livrer', 'Livrée'),
                ],
                default='en_attente',
                max_length=20,
            ),
        ),
    ]
