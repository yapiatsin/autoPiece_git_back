import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0046_geniuspay_payment_method'),
    ]

    operations = [
        migrations.CreateModel(
            name='PieceImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='pieces/galerie')),
                ('ordre', models.PositiveSmallIntegerField(default=0)),
                ('legende', models.CharField(blank=True, default='', max_length=255)),
                ('date_creation', models.DateTimeField(auto_now_add=True)),
                ('piece', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='images_supplementaires', to='stock.piece')),
            ],
            options={
                'verbose_name': 'Image supplémentaire',
                'verbose_name_plural': 'Images supplémentaires',
                'ordering': ['ordre', 'pk'],
            },
        ),
    ]
