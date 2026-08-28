# Generated manually for ChatConversation / ChatMessage

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ecom', '0006_seed_zones_livraison_ci'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ChatConversation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('session_key', models.CharField(blank=True, db_index=True, default='', max_length=40)),
                ('status', models.CharField(choices=[('pending', 'En attente'), ('active', 'Active'), ('refused', 'Refusée'), ('closed', 'Fermée')], db_index=True, default='pending', max_length=20)),
                ('handler_mode', models.CharField(choices=[('staff', 'Conseiller'), ('ai', 'IA')], default='staff', max_length=20)),
                ('subject', models.CharField(blank=True, default='', max_length=255)),
                ('last_message_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('client', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='chat_conversations_client', to=settings.AUTH_USER_MODEL)),
                ('staff', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='chat_conversations_staff', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Conversation chat',
                'verbose_name_plural': 'Conversations chat',
                'ordering': ['-last_message_at', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ChatMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sender_type', models.CharField(choices=[('client', 'Client'), ('staff', 'Staff'), ('system', 'Système'), ('bot', 'Bot')], max_length=20)),
                ('body', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='ecom.chatconversation')),
                ('sender', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='chat_messages', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Message chat',
                'verbose_name_plural': 'Messages chat',
                'ordering': ['created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='chatconversation',
            index=models.Index(fields=['status', '-last_message_at'], name='ecom_chat_status_lm_idx'),
        ),
        migrations.AddIndex(
            model_name='chatconversation',
            index=models.Index(fields=['session_key', 'status'], name='ecom_chat_sess_st_idx'),
        ),
        migrations.AddIndex(
            model_name='chatconversation',
            index=models.Index(fields=['client', 'status'], name='ecom_chat_client_st_idx'),
        ),
        migrations.AddIndex(
            model_name='chatmessage',
            index=models.Index(fields=['conversation', 'created_at'], name='ecom_chat_msg_conv_idx'),
        ),
    ]
