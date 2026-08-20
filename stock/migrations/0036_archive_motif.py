from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0035_remove_piece_archive_local_entrepot'),
    ]

    operations = [
        migrations.AddField(
            model_name='piece',
            name='archive_motif',
            field=models.TextField(
                blank=True,
                default='',
                help_text="Motif de l'archivage catalogue.",
                max_length=500,
            ),
        ),
        migrations.AddField(
            model_name='historicalpiece',
            name='archive_motif',
            field=models.TextField(
                blank=True,
                default='',
                help_text="Motif de l'archivage catalogue.",
                max_length=500,
            ),
        ),
        migrations.AddField(
            model_name='stocklocal',
            name='archive_motif',
            field=models.TextField(
                blank=True,
                default='',
                help_text="Motif de l'archivage dans cette localité.",
                max_length=500,
            ),
        ),
        migrations.AddField(
            model_name='historicalstocklocal',
            name='archive_motif',
            field=models.TextField(
                blank=True,
                default='',
                help_text="Motif de l'archivage dans cette localité.",
                max_length=500,
            ),
        ),
    ]
