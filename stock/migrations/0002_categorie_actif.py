from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='categorie',
            name='actif',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='historicalcategorie',
            name='actif',
            field=models.BooleanField(default=True),
        ),
    ]
