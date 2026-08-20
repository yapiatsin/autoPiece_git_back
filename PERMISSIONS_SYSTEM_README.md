# 🎉 Système de Gestion des Permissions Personnalisées

Un système complet et moderne pour gérer les permissions personnalisées dans votre application Django avec support Excel et génération automatique depuis les URLs.

## ✨ Fonctionnalités

### 🚀 Génération Automatique depuis les URLs
Générez automatiquement toutes les permissions depuis vos fichiers `urls.py` :
```bash
python manage.py generate_permissions --update
```

### 📊 Import/Export Excel
- **Importer** des permissions depuis un fichier Excel
- **Exporter** toutes les permissions vers Excel
- Format standardisé avec colonnes : Nom, Catégorie, URL

### 🌐 Interface Web Moderne
- Interface intuitive avec recherche et filtres
- Gestion des catégories de permissions
- CRUD complet (Créer, Lire, Modifier, Supprimer)
- Modales AJAX pour une expérience fluide

## 📋 Utilisation

### 1. Génération depuis les URLs

**Via la ligne de commande :**
```bash
python manage.py generate_permissions
python manage.py generate_permissions --update  # Met à jour les permissions existantes
```

**Via l'interface web :**
- Allez sur `/permissions/`
- Cliquez sur "Générer depuis URLs"

### 2. Import depuis Excel

**Format Excel attendu :**

| Colonne A | Colonne B | Colonne C |
|-----------|-----------|-----------|
| Nom de la Permission | Catégorie | URL/Name |
| Ajouter Panier | Paniers | add_panier |
| Tableau de Bord | Gestion du Stock | tbord |

**Via la ligne de commande :**
```bash
python manage.py import_permissions_excel chemin/vers/fichier.xlsx
python manage.py import_permissions_excel chemin/vers/fichier.xlsx --update
```

**Via l'interface web :**
- Allez sur `/permissions/`
- Cliquez sur "Importer Excel"
- Sélectionnez votre fichier
- Optionnellement cochez "Mettre à jour les permissions existantes"

### 3. Export vers Excel

**Via la ligne de commande :**
```bash
python manage.py export_permissions_excel
python manage.py export_permissions_excel --output mon_fichier.xlsx --path /chemin/sauvegarde
```

**Via l'interface web :**
- Allez sur `/permissions/`
- Cliquez sur "Exporter Excel"
- Le fichier sera téléchargé automatiquement

### 4. Gestion via l'Interface Web

**Accéder à la liste des permissions :**
```
/permissions/
```

**Fonctionnalités disponibles :**
- ✅ Recherche par nom, URL ou catégorie
- ✅ Filtrage par catégorie
- ✅ Création de nouvelles permissions
- ✅ Modification des permissions existantes
- ✅ Suppression de permissions
- ✅ Gestion des catégories

**Gérer les catégories :**
```
/permissions/categories/
```

## 🔧 Commandes Management Disponibles

### `generate_permissions`
Génère automatiquement les permissions depuis les URLs Django.

**Options :**
- `--update` : Met à jour les permissions existantes au lieu de les ignorer
- `--prefix` : Préfixe à ajouter aux URLs (défaut: `stocks/`)

### `import_permissions_excel`
Importe les permissions depuis un fichier Excel.

**Arguments :**
- `file_path` : Chemin vers le fichier Excel (requis)

**Options :**
- `--update` : Met à jour les permissions existantes
- `--skip-header` : Ignore la première ligne (par défaut: True)

### `export_permissions_excel`
Exporte les permissions vers un fichier Excel.

**Options :**
- `--output` : Nom du fichier de sortie (défaut: `permissions_export.xlsx`)
- `--path` : Chemin où sauvegarder le fichier (défaut: répertoire courant)

## 📁 URLs Disponibles

| URL | Description |
|-----|-------------|
| `/permissions/` | Liste des permissions |
| `/permissions/create/` | Créer une permission |
| `/permissions/<id>/update/` | Modifier une permission |
| `/permissions/<id>/delete/` | Supprimer une permission |
| `/permissions/generate-from-urls/` | Générer depuis URLs (web) |
| `/permissions/import-excel/` | Importer depuis Excel |
| `/permissions/export-excel/` | Exporter vers Excel |
| `/permissions/categories/` | Liste des catégories |
| `/permissions/categories/create/` | Créer une catégorie |
| `/permissions/categories/<id>/update/` | Modifier une catégorie |
| `/permissions/categories/<id>/delete/` | Supprimer une catégorie |

## 🎨 Structure des Catégories

Les permissions sont automatiquement catégorisées selon les modules détectés :

- **Gestion du Stock** : URLs contenant `stocks/`
- **Ventes** : URLs contenant `vente`
- **Catégories** : URLs contenant `categorie`
- **Paniers** : URLs contenant `panier`
- **Proformas** : URLs contenant `proforma`
- **Caisse** : URLs contenant `caisse`
- **Livraisons** : URLs contenant `livraison`
- **Fournisseurs** : URLs contenant `fournisseur`
- **Pièces** : URLs contenant `piece`
- **Historiques** : URLs contenant `Historique`
- **Notifications** : URLs contenant `notification`
- **Comptes** : URLs contenant `compte`
- **Permissions** : URLs contenant `permission`
- **Profil** : URLs contenant `profil`
- **Autres** : Catégorie par défaut

## 💡 Utilisation dans les Vues

Pour protéger une vue avec une permission personnalisée, utilisez le mixin :

```python
from Userauths.mixins import CustomPermissionRequiredMixin

class MaVue(CustomPermissionRequiredMixin, LoginRequiredMixin, CreateView):
    permission_url = 'add_panier'  # Le nom de l'URL
    # ... reste du code
```

## 📝 Notes Importantes

1. **Format Excel** : Assurez-vous que votre fichier Excel respecte le format (Nom, Catégorie, URL)
2. **URLs uniques** : Le champ `url` dans `CustomPermission` doit être unique (c'est l'identifiant)
3. **Catégories** : Créez des catégories avant d'importer des permissions si nécessaire
4. **Génération** : La génération automatique ignore les URLs admin, static et media par défaut

## 🎯 Exemple de Workflow Complet

1. **Générer les permissions de base :**
   ```bash
   python manage.py generate_permissions --update
   ```

2. **Exporter vers Excel pour révision :**
   - Via l'interface web : `/permissions/` → "Exporter Excel"

3. **Modifier le fichier Excel si nécessaire**

4. **Réimporter :**
   ```bash
   python manage.py import_permissions_excel permissions_export.xlsx --update
   ```

5. **Attribuer les permissions aux utilisateurs via l'interface :**
   - `/Add compte` ou `/modifier permissions/<id>/`

## 🚀 C'est tout !

Vous avez maintenant un système complet de gestion des permissions avec génération automatique, import/export Excel et une interface web moderne. Enjoy! 🎉

