from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0018_rename_piece_local_entrepot_local_piece'),
    ]

    operations = [
        migrations.AddField(
            model_name='historicalpiece',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='pieces'),
        ),
        migrations.AddField(
            model_name='piece',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='pieces'),
        ),
    ]
