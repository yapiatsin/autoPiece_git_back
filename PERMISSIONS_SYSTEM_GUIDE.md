# Guide du Système de Permissions Personnalisées

## Vue d'ensemble

Le système de permissions personnalisées permet de contrôler l'accès aux différentes pages de l'application en fonction des permissions assignées à chaque utilisateur. Les permissions sont organisées par catégories (Dashboard, Stocks, Interfaces, Listes, Comptes).

## Fonctionnalités

### 1. Menu de Navigation Dynamique

Le menu de navigation affiche automatiquement les catégories et permissions que l'utilisateur possède :
- **Dashboard** : Affiché comme un lien simple
- **Stocks, Interfaces, Listes** : Affichés avec un sous-menu contenant les permissions
- **Comptes** : Affiché dans le menu utilisateur (nom d'utilisateur)

### 2. Vérification Automatique des Permissions

Le middleware `CustomPermissionMiddleware` intercepte automatiquement toutes les requêtes et vérifie si l'utilisateur a la permission nécessaire pour accéder à la page.

**Si l'utilisateur n'a pas la permission :**
- Une page d'erreur avec un modal "Désolé, accès interdit" s'affiche
- Pour les requêtes AJAX, un JSON avec le HTML du modal est retourné

### 3. Utilisation dans les Vues

#### Pour les vues basées sur les classes :

```python
from Userauths.mixins import CustomPermissionRequiredMixin

class MaVue(CustomPermissionRequiredMixin, TemplateView):
    permission_url = 'nom_de_l_url'  # Le nom défini dans urls.py
    template_name = 'mon_template.html'
```

#### Pour les vues basées sur les fonctions :

```python
from Userauths.decorators import custom_permission_required

@custom_permission_required('nom_de_l_url')
def ma_vue(request):
    # Votre code ici
    return render(request, 'mon_template.html')
```

**Note :** Si `permission_url` n'est pas spécifié, il sera automatiquement détecté depuis l'URL de la requête.

## Structure des Modèles

### CustomPermission
- `name` : Nom de la permission (affiché dans le menu)
- `url` : Nom de l'URL Django (name dans urls.py)
- `categorie` : Catégorie à laquelle appartient la permission
- `users` : Utilisateurs ayant cette permission

### TypeCustomPermission
- `categorie` : Nom de la catégorie (Dashboard, Stocks, Interfaces, Listes, Comptes)

## Gestion des Permissions

### Via l'interface web :
1. Aller dans **Comptes > Permissions** pour gérer les permissions
2. Aller dans **Comptes > Catégories permissions** pour gérer les catégories

### Via les commandes de management :
```bash
# Générer automatiquement les permissions depuis les URLs
python manage.py generate_permissions --update

# Exporter les permissions vers Excel
python manage.py export_permissions_excel

# Importer les permissions depuis Excel
python manage.py import_permissions_excel
```

## Configuration

### Context Processor

Le context processor `user_permissions_menu` est automatiquement ajouté dans `settings.py` et fournit :
- `user_menu_categories` : Liste des catégories avec leurs permissions pour le menu

### Middleware

Le middleware `CustomPermissionMiddleware` vérifie automatiquement les permissions sur chaque requête.

**URLs exclues :**
- `/Se connecter`, `/Deconnexion`
- `/admin/`
- `/static/`, `/media/`
- `/__debug__/`

**URLs publiques (accessibles à tous les utilisateurs authentifiés) :**
- `/` (page d'accueil)
- `/profil/`, `/change_password/`

## Cas Spéciaux

### Superusers
Les superusers ont automatiquement accès à toutes les pages, peu importe les permissions assignées.

### URLs sans permission
Si une URL n'a pas de permission correspondante dans la base de données, l'accès est autorisé (pour éviter de bloquer des URLs non gérées).

## Dépannage

### Le menu ne s'affiche pas correctement
- Vérifier que le context processor est bien ajouté dans `settings.py`
- Vérifier que les catégories existent dans la base de données
- Vérifier que l'utilisateur a des permissions assignées

### L'accès est toujours refusé
- Vérifier que la permission existe dans la base de données avec le bon `url` (nom de l'URL)
- Vérifier que l'utilisateur a bien cette permission assignée
- Vérifier que le middleware est bien activé dans `settings.py`

### Le modal d'erreur ne s'affiche pas
- Vérifier que les templates `access_denied.html` et `access_denied_modal.html` existent
- Pour les requêtes AJAX, vérifier que le header `X-Requested-With: XMLHttpRequest` est envoyé

