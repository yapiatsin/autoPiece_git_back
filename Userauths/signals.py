# signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import CustomUser, ProfilUser

@receiver(post_save, sender=CustomUser)
def creer_ou_mettre_a_jour_profil(sender, instance, created, **kwargs):
    if created:
        ProfilUser.objects.create(user=instance)
    else:
        # Utilisateurs créés avant ProfilUser peuvent ne pas avoir de profil
        profil, _ = ProfilUser.objects.get_or_create(user=instance)
        profil.save()