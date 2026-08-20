"""
Commande Django management pour envoyer les alertes de stock quotidiennement
Usage: python manage.py send_stock_alerts
"""
from django.core.management.base import BaseCommand
from stock.stock_alerts import (
    detecter_pieces_en_alerte,
    get_active_creneau,
    process_stock_alert_schedule,
)


class Command(BaseCommand):
    help = 'Envoie les alertes de stock (créneau horaire actuel, 4× par jour)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force la création même si le créneau a déjà été envoyé',
        )

    def handle(self, *args, **options):
        self.stdout.write('Vérification des alertes de stock...')
        try:
            pieces_alerte = detecter_pieces_en_alerte()
            creneau = get_active_creneau()
            if creneau:
                self.stdout.write(f"Créneau actif : {creneau['label']} ({creneau['cle']})")
            else:
                self.stdout.write(
                    self.style.WARNING('Aucun créneau actif (avant la première heure programmée).')
                )

            if not pieces_alerte:
                self.stdout.write(self.style.SUCCESS('Aucune pièce sous le seuil.'))
                return

            result = process_stock_alert_schedule(force=options['force'])
            created = result.get('created', 0)
            if created > 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'{created} notification(s) créée(s) pour {len(pieces_alerte)} pièce(s) en alerte.'
                    )
                )
            elif result.get('skipped'):
                self.stdout.write(
                    self.style.WARNING('Créneau déjà traité récemment. Utilisez --force pour renvoyer.')
                )
            else:
                self.stdout.write(self.style.WARNING('Aucune nouvelle notification (utilisateurs déjà notifiés).'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Erreur : {e}'))

