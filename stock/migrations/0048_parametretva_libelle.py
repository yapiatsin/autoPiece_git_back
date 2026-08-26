from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0047_pieceimage'),
    ]

    operations = [
        migrations.AddField(
            model_name='parametretva',
            name='libelle',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Ex. TVA standard, TVA réduite…',
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name='historicalparametretva',
            name='libelle',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Ex. TVA standard, TVA réduite…',
                max_length=100,
            ),
        ),
        migrations.AlterModelOptions(
            name='parametretva',
            options={
                'ordering': ['-active', 'taux', 'pk'],
                'verbose_name': 'Paramètre TVA',
                'verbose_name_plural': 'Paramètres TVA',
            },
        ),
    ]
