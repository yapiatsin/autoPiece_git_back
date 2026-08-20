from django import template

register = template.Library()

@register.filter
def mul(value, arg):
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return ''

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key, {'qte': 0, 'valeur': 0})


@register.filter
def statut_demande_affichage(demande, user):
    if demande is None:
        return ''
    return demande.get_statut_affichage(user)


@register.filter
def statut_demande_slug(demande, user):
    if demande is None:
        return ''
    return demande.get_statut_affichage_slug(user)


@register.filter
def statut_bon_affichage(bon, user):
    if bon is None:
        return ''
    return bon.get_statut_affichage(user)