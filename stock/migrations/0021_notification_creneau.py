from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0020_alter_historicalpiece_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='creneau',
            field=models.CharField(blank=True, db_index=True, max_length=32, null=True),
        ),
    ]
