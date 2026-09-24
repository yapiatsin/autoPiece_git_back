from django.contrib import admin
from django.utils.html import format_html

from .models import (
    CustomUser,
    TypeCustomPermission,
    CustomPermission,
    PWD_FORGET,
    ProfilUser,
    LocalEntrepot,
    CreneauDisponibilite,
    GoogleIdentity,
)


class ProfilUserInline(admin.StackedInline):
    """Profil associé, visible depuis la fiche compte."""

    model = ProfilUser
    can_delete = False
    extra = 0
    fk_name = 'user'
    fieldsets = (
        ('Informations personnelles', {
            'fields': (
                'photo', 'date_naissance', 'adresse', 'ville', 'pays', 'code_postal',
            ),
        }),
        ('Informations professionnelles', {
            'fields': ('poste', 'numero_employe', 'date_embauche', 'statut'),
        }),
        ('Préférences & activité', {
            'fields': ('bio', 'derniere_connexion', 'est_verifie'),
        }),
        ('Métadonnées', {
            'classes': ('collapse',),
            'fields': ('date_creation', 'date_modification'),
        }),
    )
    readonly_fields = ('numero_employe', 'date_creation', 'date_modification')


class CustomUserAdmin(admin.ModelAdmin):
    list_display = [
        'username', 'email', 'role', 'is_active', 'genre',
        'local_entrepot', 'plafond_remise',
    ]
    list_filter = ['username', 'email', 'role', 'is_active', 'genre', 'local_entrepot']
    list_editable = ['plafond_remise']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    inlines = [ProfilUserInline]


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
    list_display = [
        'code', 'nom', 'fne_point_de_vente', 'plafond_remise', 'contact',
        'latitude', 'longitude', 'statut', 'statut_ouverture_display',
    ]
    list_filter = ['statut', 'nom']
    search_fields = ['nom', 'contact', 'fne_point_de_vente']
    list_editable = ['statut', 'fne_point_de_vente', 'plafond_remise']
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


@admin.register(GoogleIdentity)
class GoogleIdentityAdmin(admin.ModelAdmin):
    """Comptes Google liés.

    Supprimer une ligne délie le compte : l'utilisateur devra reconfirmer par
    code à sa prochaine connexion Google. Utile au départ d'un employé ou
    quand une adresse Google change de mains.
    """

    list_display = ['user', 'email', 'created_at', 'last_login_at']
    list_filter = ['created_at', 'last_login_at']
    search_fields = ['user__username', 'user__email', 'email', 'sub']
    ordering = ['-created_at']
    list_select_related = ['user']
    # `sub` vient de Google : le modifier casserait le lien sans rien réparer.
    readonly_fields = ['sub', 'email', 'picture', 'created_at', 'last_login_at']
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        # Une identité ne se crée que par le parcours de connexion, qui seul
        # peut vérifier le jeton auprès de Google.
        return False


@admin.register(ProfilUser)
class ProfilUserAdmin(admin.ModelAdmin):
    list_display = [
        'photo_apercu',
        'user',
        'nom_complet_display',
        'numero_employe',
        'poste',
        'ville',
        'pays',
        'statut',
        'est_verifie',
        'est_actif_display',
        'derniere_connexion',
        'date_creation',
    ]
    list_filter = [
        'statut', 'est_verifie', 'pays', 'ville',
        'date_embauche', 'date_creation',
    ]
    search_fields = [
        'user__username', 'user__email', 'user__first_name', 'user__last_name',
        'numero_employe', 'poste', 'ville', 'adresse', 'bio',
    ]
    list_select_related = ['user']
    ordering = ['-date_creation']
    list_per_page = 25
    date_hierarchy = 'date_creation'
    readonly_fields = (
        'pid', 'numero_employe', 'photo_apercu',
        'nom_complet_display', 'est_actif_display',
        'date_creation', 'date_modification',
    )
    autocomplete_fields = ['user']
    fieldsets = (
        (None, {
            'fields': ('user', 'pid', 'photo', 'photo_apercu'),
        }),
        ('Informations personnelles', {
            'fields': (
                'nom_complet_display',
                'date_naissance', 'adresse', 'ville', 'pays', 'code_postal',
            ),
        }),
        ('Informations professionnelles', {
            'fields': ('poste', 'numero_employe', 'date_embauche', 'statut', 'est_actif_display'),
        }),
        ('Préférences & activité', {
            'fields': ('bio', 'derniere_connexion', 'est_verifie'),
        }),
        ('Métadonnées', {
            'classes': ('collapse',),
            'fields': ('date_creation', 'date_modification'),
        }),
    )

    @admin.display(description='Photo')
    def photo_apercu(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" alt="" style="height:40px;width:40px;object-fit:cover;border-radius:50%;" />',
                obj.photo.url,
            )
        return '—'

    @admin.display(description='Nom complet', ordering='user__first_name')
    def nom_complet_display(self, obj):
        return obj.nom_complet

    @admin.display(description='Actif', boolean=True)
    def est_actif_display(self, obj):
        return obj.est_actif


# CustomUserAdmin : search_fields requis par autocomplete_fields de ProfilUser
admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(TypeCustomPermission)
admin.site.register(CustomPermission, CustomPermissionAdmin)
admin.site.register(PWD_FORGET)
