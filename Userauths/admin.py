from django.contrib import admin

from .models import (
    CustomUser,
    TypeCustomPermission,
    CustomPermission,
    PWD_FORGET,
    ProfilUser,
    LocalEntrepot,
    CreneauDisponibilite,
)


class CustomUserAdmin(admin.ModelAdmin):
    list_display = ['username', 'email', 'role', 'is_active', 'genre', 'local_entrepot']
    list_filter = ['username', 'email', 'role', 'is_active', 'genre', 'local_entrepot']

class CustomPermissionAdmin(admin.ModelAdmin):
    list_display = ['name','categorie__categorie', 'url']
    list_filter = ['name', 'categorie__categorie', 'url']
    search_fields = ['name', 'categorie__categorie', 'url']
    ordering = ['name', 'categorie__categorie', 'url']
    list_editable = ['url']
    list_per_page = 10
    list_max_show_all = 100
    list_select_related = ['categorie',]


class CreneauDisponibiliteInline(admin.TabularInline):
    model = CreneauDisponibilite
    extra = 1
    min_num = 0
    can_delete = True
    fields = ('jour', 'heure_ouverture', 'heure_fermeture')
    ordering = ('jour', 'heure_ouverture')
    verbose_name = 'Créneau'
    verbose_name_plural = 'Créneaux de disponibilité (optionnel)'


@admin.register(LocalEntrepot)
class LocalEntrepotAdmin(admin.ModelAdmin):
    list_display = ['code', 'nom', 'latitude', 'longitude', 'statut', 'statut_ouverture_display']
    list_filter = ['statut', 'nom']
    search_fields = ['nom']
    list_editable = ['statut']
    inlines = [CreneauDisponibiliteInline]

    @admin.display(description='Libellé statut', boolean=False)
    def statut_ouverture_display(self, obj):
        return obj.statut_ouverture


@admin.register(CreneauDisponibilite)
class CreneauDisponibiliteAdmin(admin.ModelAdmin):
    list_display = [
        'local_entrepot',
        'get_jour_display',
        'heure_ouverture',
        'heure_fermeture',
        'statut',
    ]
    list_filter = ['jour', 'local_entrepot']
    search_fields = ['local_entrepot__nom']
    ordering = ['local_entrepot__nom', 'jour']


admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(TypeCustomPermission)
admin.site.register(CustomPermission, CustomPermissionAdmin)
admin.site.register(PWD_FORGET)
admin.site.register(ProfilUser)
