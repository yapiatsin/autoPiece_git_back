"""
Template tags pour les permissions personnalisées
"""
from django import template
from django.urls import reverse, NoReverseMatch

register = template.Library()


@register.filter
def can_reverse_url(url_name):
    """
    Vérifie si une URL peut être générée sans paramètres
    Retourne True si l'URL peut être générée, False sinon
    """
    try:
        reverse(url_name)
        return True
    except (NoReverseMatch, Exception):
        return False


@register.simple_tag
def safe_url(url_name, default_url='#'):
    """
    Génère une URL de manière sécurisée, retourne default_url si elle ne peut pas être générée
    """
    try:
        return reverse(url_name)
    except (NoReverseMatch, Exception):
        return default_url