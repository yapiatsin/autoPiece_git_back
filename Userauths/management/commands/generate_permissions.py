"""
Commande Django pour générer automatiquement les permissions personnalisées
depuis les URLs du périmètre magasin (stocks + comptes/permissions/localités).
"""
from django.core.management.base import BaseCommand
from django.urls import get_resolver

from Userauths.models import CustomPermission, TypeCustomPermission
from Userauths.permissions_utils import (
    EXEMPT_URL_NAMES,
    PROTECTED_USERAUTHS_URL_NAMES,
    STOCK_PATH_PREFIX,
)


class Command(BaseCommand):
    help = (
        'Génère les CustomPermission pour /stocks/ et les URLs Userauths '
        'comptes/permissions/localités (exclut auth/profil/mdp).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--update',
            action='store_true',
            help='Met à jour les permissions existantes',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(
            'Génération des permissions (périmètre magasin)...\n'
        ))

        update = options['update']
        resolver = get_resolver()

        def extract_urls(url_patterns_list, prefix='', namespace=''):
            patterns = []
            for pattern in url_patterns_list:
                if hasattr(pattern, 'url_patterns'):
                    new_prefix = prefix + str(pattern.pattern)
                    new_namespace = namespace
                    if pattern.namespace:
                        new_namespace = (
                            f'{namespace}:{pattern.namespace}'
                            if namespace
                            else pattern.namespace
                        )
                    patterns.extend(
                        extract_urls(pattern.url_patterns, new_prefix, new_namespace)
                    )
                else:
                    url_path = prefix + str(pattern.pattern)
                    name = pattern.name
                    if namespace and name:
                        name = f'{namespace}:{name}'
                    if name:
                        patterns.append({
                            'path': url_path,
                            'name': name,
                            'pattern': str(pattern.pattern),
                        })
            return patterns

        all_urls = extract_urls(resolver.url_patterns)

        def bare_url_name(name):
            return name.split(':')[-1] if name else name

        def is_in_scope(url_info):
            name = bare_url_name(url_info['name'])
            path = url_info['path'].replace('\\', '/')
            if name in EXEMPT_URL_NAMES:
                return False
            # Magasin
            if path.startswith(STOCK_PATH_PREFIX.lstrip('/')) or f'/{STOCK_PATH_PREFIX.lstrip("/")}' in f'/{path}':
                return True
            if 'stocks/' in path:
                return True
            # Userauths protégés
            if name in PROTECTED_USERAUTHS_URL_NAMES:
                return True
            return False

        excluded_patterns = ('admin', 'static', 'media', '__debug__', 'api/')
        filtered_urls = [
            url for url in all_urls
            if not any(ex in url['path'] for ex in excluded_patterns)
            and is_in_scope(url)
        ]

        self.stdout.write(f'{len(filtered_urls)} URLs dans le périmètre\n')

        categories_map = {
            'dashboard': 'Dashboard',
            'tbord': 'Dashboard',
            'tableau': 'Dashboard',
            'stock': 'Stocks',
            'stocks/': 'Stocks',
            'categorie': 'Stocks',
            'sous_categorie': 'Stocks',
            'sous-categorie': 'Stocks',
            'fournisseur': 'Stocks',
            'piece': 'Stocks',
            'panier': 'Interfaces',
            'proforma': 'Interfaces',
            'caisse': 'Interfaces',
            'livraison': 'Interfaces',
            'cmd_line': 'Interfaces',
            'zones': 'Interfaces',
            'transfert': 'Interfaces',
            'imprimante': 'Interfaces',
            'interface': 'Interfaces',
            'historique': 'Liste',
            'Historique': 'Liste',
            'vente': 'Liste',
            'commande': 'Liste',
            'ticket': 'Liste',
            'notification': 'Liste',
            'liste': 'Liste',
            'export': 'Liste',
            'compte': 'Comptes',
            'permission': 'Comptes',
            'localite': 'Comptes',
        }

        main_categories = ['Dashboard', 'Stocks', 'Interfaces', 'Liste', 'Comptes']
        for cat_name in main_categories:
            TypeCustomPermission.objects.get_or_create(
                categorie=cat_name,
                defaults={'categorie': cat_name},
            )

        default_cat, _ = TypeCustomPermission.objects.get_or_create(
            categorie='Autres',
            defaults={'categorie': 'Autres'},
        )

        created_count = 0
        updated_count = 0
        skipped_count = 0

        for url_info in filtered_urls:
            url_name = bare_url_name(url_info['name'])
            url_path = url_info['path'].lower()
            url_name_lower = url_name.lower()

            category = default_cat
            category_found = False
            for key, cat_name in categories_map.items():
                if key in url_path or key in url_name_lower:
                    category, _ = TypeCustomPermission.objects.get_or_create(
                        categorie=cat_name,
                        defaults={'categorie': cat_name},
                    )
                    category_found = True
                    break

            if not category_found:
                category = default_cat

            permission_name = url_name.replace('_', ' ').replace('-', ' ').title()
            url_identifier = url_name

            if update:
                _, created = CustomPermission.objects.update_or_create(
                    url=url_identifier,
                    defaults={
                        'name': permission_name,
                        'categorie': category,
                    },
                )
                if created:
                    created_count += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'  Créée: {permission_name} ({url_identifier})'
                    ))
                else:
                    updated_count += 1
                    self.stdout.write(self.style.WARNING(
                        f'  Mise à jour: {permission_name} ({url_identifier})'
                    ))
            else:
                if CustomPermission.objects.filter(url=url_identifier).exists():
                    skipped_count += 1
                    self.stdout.write(self.style.WARNING(
                        f'  Ignorée (existe déjà): {permission_name}'
                    ))
                else:
                    CustomPermission.objects.create(
                        name=permission_name,
                        categorie=category,
                        url=url_identifier,
                    )
                    created_count += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'  Créée: {permission_name} ({url_identifier})'
                    ))

        self.stdout.write(self.style.SUCCESS('\nRésumé:\n'))
        self.stdout.write(self.style.SUCCESS(f'  Permissions créées: {created_count}'))
        if update:
            self.stdout.write(self.style.WARNING(
                f'  Permissions mises à jour: {updated_count}'
            ))
        if skipped_count > 0:
            self.stdout.write(self.style.WARNING(
                f'  Permissions ignorées: {skipped_count}'
            ))
        self.stdout.write(self.style.SUCCESS('\nTerminé.'))
