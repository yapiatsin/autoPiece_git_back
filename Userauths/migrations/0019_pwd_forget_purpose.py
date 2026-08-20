from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Userauths', '0018_localentrepot_statut'),
    ]

    operations = [
        migrations.AddField(
            model_name='pwd_forget',
            name='purpose',
            field=models.CharField(
                choices=[
                    ('password_reset', 'Réinitialisation mot de passe'),
                    ('activation', 'Activation compte'),
                ],
                db_index=True,
                default='password_reset',
                max_length=32,
            ),
        ),
    ]
