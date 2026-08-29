"""
Régénère les PDF des bons de commande caisse (palette orange Auto-Pièce).
Usage: python manage.py regenerate_bons_pdf
"""
from django.core.management.base import BaseCommand

from stock.bon_commande_vente import generate_bon_commande_vente_pdf, sauvegarder_pdf_bon
from stock.models import BonCommandePaiement, PanierItem


class Command(BaseCommand):
    help = 'Régénère les fichiers PDF des bons de commande vente (sans vert)'

    def handle(self, *args, **options):
        bons = (
            BonCommandePaiement.objects.select_related(
                'commande',
                'commande__panier',
                'local_entrepot',
                'caissier',
                'hote_accueil',
            )
            .order_by('id')
        )
        ok = 0
        errors = 0
        for bon in bons:
            try:
                commande = bon.commande
                panier = commande.panier
                items = list(
                    PanierItem.objects.filter(panier=panier).select_related('piece')
                )
                pdf_bytes = generate_bon_commande_vente_pdf(
                    bon, commande, panier, items
                )
                bon.fichier_pdf = sauvegarder_pdf_bon(bon, pdf_bytes)
                bon.save(update_fields=['fichier_pdf'])
                ok += 1
                self.stdout.write(self.style.SUCCESS(f'OK {bon.numero_bon}'))
            except Exception as exc:
                errors += 1
                self.stderr.write(self.style.ERROR(f'ERR {bon.numero_bon}: {exc}'))
        self.stdout.write(
            self.style.NOTICE(f'Terminé : {ok} régénéré(s), {errors} erreur(s).')
        )
