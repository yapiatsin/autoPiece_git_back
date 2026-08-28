# Generated manually for ChatConversation.closed_at

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ecom', '0007_chat_conversation_message'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatconversation',
            name='closed_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
