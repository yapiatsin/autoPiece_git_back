from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0045_default_seeders'),
    ]

    operations = [
        migrations.AddField(
            model_name='geniuspaypaiement',
            name='payment_method',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
    ]
