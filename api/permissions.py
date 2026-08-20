"""
Permissions API e-commerce.

- IsClient          : role == 'client' (clients web/mobile v1).
- IsClientEcommerce : alias legacy (role client).
- IsStaff           : personnel interne.
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS

STAFF_ROLES = ('accueil', 'caissier', 'livreur', 'admin', 'chefagence', 'gestionnaire')
CLIENT_ROLE = 'client'


class IsClient(BasePermission):
    message = 'Réservé aux clients e-commerce.'

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and getattr(u, 'role', None) == CLIENT_ROLE)


class IsClientEcommerce(IsClient):
    """Alias rétrocompatibilité."""


class IsStaff(BasePermission):
    message = 'Réservé au personnel interne.'

    def has_permission(self, request, view):
        u = request.user
        return bool(
            u and u.is_authenticated and (
                u.is_superuser or getattr(u, 'role', None) in STAFF_ROLES
            )
        )


class IsAdmin(BasePermission):
    message = 'Réservé aux administrateurs.'

    def has_permission(self, request, view):
        u = request.user
        return bool(
            u and u.is_authenticated and (
                u.is_superuser or getattr(u, 'role', None) == 'admin'
            )
        )


class IsClientOwner(BasePermission):
    """L'objet appartient au client connecté."""

    def has_object_permission(self, request, view, obj):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if getattr(u, 'role', None) != CLIENT_ROLE:
            return False
        owner = getattr(obj, 'utilisateur', None) or getattr(obj, 'user', None)
        if owner == u:
            return True
        panier = getattr(obj, 'panier', None)
        if panier and panier.utilisateur_id == u.pk:
            return True
        return False


class IsOwnerOrStaff(BasePermission):
    """Lecture/écriture si propriétaire ou staff."""

    def has_object_permission(self, request, view, obj):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if u.is_superuser or getattr(u, 'role', None) in STAFF_ROLES:
            return True
        owner = getattr(obj, 'utilisateur', None) or getattr(obj, 'user', None)
        if owner == u:
            return True
        panier = getattr(obj, 'panier', None)
        return bool(panier and panier.utilisateur_id == u.pk)


class ReadOnlyOrStaff(BasePermission):
    """Lecture ouverte, écriture réservée au personnel."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        u = request.user
        return bool(
            u and u.is_authenticated and (
                u.is_superuser or getattr(u, 'role', None) in STAFF_ROLES
            )
        )
