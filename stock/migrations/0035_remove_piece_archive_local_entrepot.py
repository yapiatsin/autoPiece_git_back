from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0034_archive_par_tracking'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='historicalpiece',
            name='archive_local_entrepot',
        ),
        migrations.RemoveField(
            model_name='piece',
            name='archive_local_entrepot',
        ),
    ]
