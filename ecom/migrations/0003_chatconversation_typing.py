from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ecom', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatconversation',
            name='client_typing_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='chatconversation',
            name='staff_typing_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
