from django import template

register = template.Library()

@register.filter
def mul(value, arg):
    """Multiplie la valeur par l'argument."""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return ''
