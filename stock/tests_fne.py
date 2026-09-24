"""Tests de la certification FNE (facture normalisée électronique DGI) en caisse.

`requests.post` vers la plateforme FNE est la seule frontière remplacée : la
construction de la facture, l'idempotence, la consignation des échecs,
l'encaissement et la composition des reçus sont exercés réellement.
La configuration est injectée à la place du .env, pour ne jamais appeler la
vraie plateforme depuis les tests.
"""
import shutil
import tempfile
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from Userauths.models import LocalEntrepot
from ecom.services import get_moyen_espece, get_moyen_geniuspay
from stock import printer_service
from stock.fne_service import certifier_commande, construire_facture, pourcentage_remise
from stock.models import (
    Categorie, Commande, FactureFNE, Panier, PanierItem, Piece, StockLocal, Ticket,
)

User = get_user_model()

CONFIG = {
    'FNE_ENABLED': 'True',
    'FNE_API_KEY': 'cle-de-test',
    'FNE_BASE_URL': 'http://fne.invalid/ws',
    'FNE_ETABLISSEMENT': 'P&B Koumassi',
    'FNE_CLIENT_TELEPHONE': '+225 07 09 03 71 20',
    'FNE_CLIENT_EMAIL': 'contact@example.com',
    'FNE_TAXE_HORS_TVA': 'TVAD',
}

URL_VERIF = 'http://fne.invalid/fr/verification/019465c1-3f61-766c-9652-706e32dfb436'


def reponse_fne(status=200, payload=None):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload if payload is not None else {
        'ncc': '9606123E',
        'reference': '9606123E26000000019',
        'token': URL_VERIF,
        'warning': False,
        'balance_sticker': 179,
        'invoice': {
            'id': 'e2b2d8da-a532-4c08-9182-f5b428ca468d',
            'reference': '9606123E26000000019',
            'date': '2026-09-23T10:15:00.000Z',
            'amount': 45000,
            'vatAmount': 0,
            'fiscalStamp': 100,
            'items': [],
        },
    }
    response.text = ''
    return response


class FNEBase(TestCase):
    def setUp(self):
        env = lambda name, default='': CONFIG.get(name, default)  # noqa: E731
        for cible in ('stock.fne._env', 'stock.fne_service._env'):
            patcher = patch(cible, side_effect=env)
            patcher.start()
            self.addCleanup(patcher.stop)
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        media_override = override_settings(MEDIA_ROOT=media)
        media_override.enable()
        self.addCleanup(media_override.disable)

        self.localite = LocalEntrepot.objects.create(
            nom='Koumassi', fne_point_de_vente='Caisse 1',
        )
        self.caissier = User.objects.create_superuser(
            username='caissiere', email='caissiere@example.com', password='x',
        )
        categorie = Categorie.objects.create(categorie='Freinage')
        self.plaquette = Piece.objects.create(
            categorie=categorie, numero_piece='PLQ-01', designation='Plaquettes de frein avant',
            prix_achat=Decimal('8000'), prix_unitaire=Decimal('15000'),
        )
        self.filtre = Piece.objects.create(
            categorie=categorie, numero_piece='FLT-02', designation='Filtre à huile',
            prix_achat=Decimal('2000'), prix_unitaire=Decimal('5000'),
        )
        for piece in (self.plaquette, self.filtre):
            StockLocal.objects.create(piece=piece, local_entrepot=self.localite, quantite_disponible=10)

    def creer_vente(self, remise=Decimal('0')):
        panier = Panier.objects.create(
            local_entrepot=self.localite, valide=True, nom_client='Kouassi Jean',
        )
        PanierItem.objects.create(panier=panier, piece=self.plaquette, quantite=2)
        PanierItem.objects.create(panier=panier, piece=self.filtre, quantite=3)
        brut = Decimal('45000')
        commande = Commande.objects.create(
            panier=panier, numero_commande=f'N°{panier.id}-1',
            total_sans_remise=brut, total=brut - remise, remise=remise,
            utilisateur=self.caissier,
        )
        ticket = Ticket.objects.create(numero=f'TKT{commande.id}', commande=commande)
        panier.ticket = ticket.numero
        panier.save()
        return commande, ticket

    def payer_en_especes(self, commande):
        commande.paye = True
        commande.moyen_paiement = get_moyen_espece()
        commande.save()
        return commande


class ConstructionFacture(FNEBase):
    def test_facture_de_vente_especes_b2c(self):
        commande = self.payer_en_especes(self.creer_vente()[0])
        body = construire_facture(commande, caissier=self.caissier)

        self.assertEqual(body['invoiceType'], 'sale')
        self.assertEqual(body['paymentMethod'], 'cash')
        self.assertEqual(body['template'], 'B2C')
        self.assertFalse(body['isRne'])
        self.assertEqual(body['establishment'], 'P&B Koumassi')
        self.assertEqual(body['pointOfSale'], 'Caisse 1')
        self.assertEqual(body['clientCompanyName'], 'Kouassi Jean')
        self.assertEqual(body['clientPhone'], '0709037120')
        self.assertEqual(body['clientSellerName'], 'caissiere')
        self.assertNotIn('discount', body)
        self.assertEqual(
            sorted((i['reference'], i['quantity'], i['amount'], i['taxes'][0]) for i in body['items']),
            [('FLT-02', 3, 5000, 'TVAD'), ('PLQ-01', 2, 15000, 'TVAD')],
        )

    def test_point_de_vente_vient_de_la_localite(self):
        """Chaque localité envoie son propre PDV FNE, pas une valeur .env fixe."""
        autre = LocalEntrepot.objects.create(
            nom='Yopougon', fne_point_de_vente='Caisse Yopougon',
        )
        commande = self.payer_en_especes(self.creer_vente()[0])
        commande.panier.local_entrepot = autre
        commande.panier.save(update_fields=['local_entrepot'])
        body = construire_facture(commande)
        self.assertEqual(body['pointOfSale'], 'Caisse Yopougon')
        self.assertEqual(body['establishment'], 'P&B Koumassi')

    def test_localite_sans_pdv_refuse_la_certification(self):
        self.localite.fne_point_de_vente = ''
        self.localite.save(update_fields=['fne_point_de_vente'])
        commande = self.payer_en_especes(self.creer_vente()[0])
        with self.assertRaises(Exception) as ctx:
            construire_facture(commande)
        self.assertIn('Point de vente FNE non configuré', str(ctx.exception))

    def test_remise_envoyee_en_pourcentage_du_ht(self):
        commande = self.payer_en_especes(self.creer_vente(remise=Decimal('4500'))[0])
        self.assertEqual(pourcentage_remise(commande), Decimal('10'))
        self.assertEqual(construire_facture(commande)['discount'], 10.0)

    def test_tva_cochee_en_caisse(self):
        from stock.models import ParametreTVA
        ParametreTVA.objects.create(active=True, taux=Decimal('18'))
        commande = self.payer_en_especes(self.creer_vente()[0])
        commande.tva_appliquee = True
        commande.montant_tva = Decimal('8100')
        commande.save()
        self.assertEqual({i['taxes'][0] for i in construire_facture(commande)['items']}, {'TVA'})


@patch('stock.fne.requests.post')
class Certification(FNEBase):
    def test_certifie_et_conserve_la_facture(self, post):
        post.return_value = reponse_fne()
        commande = self.payer_en_especes(self.creer_vente()[0])

        facture = certifier_commande(commande, caissier=self.caissier)

        self.assertEqual(facture.statut, FactureFNE.STATUT_CERTIFIEE)
        self.assertEqual(facture.reference, '9606123E26000000019')
        self.assertEqual(facture.url_verification, URL_VERIF)
        self.assertEqual(facture.montant_ttc, Decimal('45000'))
        self.assertEqual(facture.timbre, Decimal('100'))
        self.assertEqual(facture.fne_invoice_id, 'e2b2d8da-a532-4c08-9182-f5b428ca468d')
        url, = post.call_args.args
        self.assertEqual(url, 'http://fne.invalid/ws/external/invoices/sign')
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer cle-de-test')

    def test_jamais_certifiee_deux_fois(self, post):
        post.return_value = reponse_fne()
        commande = self.payer_en_especes(self.creer_vente()[0])
        certifier_commande(commande)
        certifier_commande(commande)
        self.assertEqual(post.call_count, 1)

    def test_refus_consigne_puis_relance(self, post):
        post.return_value = reponse_fne(400, {
            'message': 'Bad Request Exception', 'statusCode': 400,
            'errors': {'establishment': {'invalid': 'Establishment is invalid'}},
        })
        commande = self.payer_en_especes(self.creer_vente()[0])

        facture = certifier_commande(commande)
        self.assertEqual(facture.statut, FactureFNE.STATUT_ECHEC)
        self.assertIn('FNE_ETABLISSEMENT', facture.erreur)

        post.return_value = reponse_fne()
        facture = certifier_commande(commande)
        self.assertEqual(facture.statut, FactureFNE.STATUT_CERTIFIEE)
        self.assertEqual(facture.tentatives, 2)

    def test_delai_depasse_signale_un_risque_de_doublon(self, post):
        post.side_effect = requests.Timeout()
        commande = self.payer_en_especes(self.creer_vente()[0])
        facture = certifier_commande(commande)
        self.assertEqual(facture.statut, FactureFNE.STATUT_ECHEC)
        self.assertIn("espace FNE", facture.erreur)

    def test_paiement_numerique_non_certifie(self, post):
        commande = self.creer_vente()[0]
        commande.paye = True
        commande.moyen_paiement = get_moyen_geniuspay()
        commande.save()
        self.assertIsNone(certifier_commande(commande))
        post.assert_not_called()

    def test_fne_desactivee(self, post):
        commande = self.payer_en_especes(self.creer_vente()[0])
        with patch.dict(CONFIG, {'FNE_ENABLED': 'False'}):
            self.assertIsNone(certifier_commande(commande))
        post.assert_not_called()


@patch('stock.fne.requests.post')
@patch.object(printer_service, 'HAS_USB', False)
@patch('stock.paiement_service.publish_paiement_valide')
class EncaissementEspeces(FNEBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.caissier)

    def encaisser(self, ticket):
        return self.client.post(
            reverse('valid_pay_article', args=[ticket.numero]),
            {'montant': '50000', 'moyen_paiement': get_moyen_espece().pk},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

    def test_paiement_especes_renvoie_la_fne_certifiee(self, _mqtt, post):
        post.return_value = reponse_fne()
        commande, ticket = self.creer_vente()

        reponse = self.encaisser(ticket)

        self.assertEqual(reponse.status_code, 200)
        donnees = reponse.json()
        self.assertTrue(donnees['success'])
        self.assertEqual(donnees['ticket_numero'], ticket.numero)
        self.assertTrue(donnees['fne']['certifiee'])
        self.assertEqual(donnees['fne']['reference'], '9606123E26000000019')

        recu_fne = self.client.get(reverse('printer_escpos_fne', args=[ticket.numero]))
        self.assertEqual(recu_fne.status_code, 200)
        octets = recu_fne.content
        self.assertIn(b'9606123E26000000019', octets)
        self.assertIn(b'\x1d\x28\x6b', octets)  # QR code ESC/POS
        self.assertIn(URL_VERIF.encode(), octets)

        pdf = self.client.get(reverse('caisse_fne_pdf', args=[ticket.numero]))
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF'))

    def test_panne_fne_n_annule_pas_le_paiement(self, _mqtt, post):
        post.side_effect = requests.ConnectionError()
        commande, ticket = self.creer_vente()

        donnees = self.encaisser(ticket).json()

        self.assertTrue(donnees['success'])
        self.assertFalse(donnees['fne']['certifiee'])
        commande.refresh_from_db()
        self.assertTrue(commande.paye)
        self.assertEqual(
            self.client.get(reverse('printer_escpos_fne', args=[ticket.numero])).status_code, 404,
        )

        post.side_effect = None
        post.return_value = reponse_fne()
        relance = self.client.post(
            reverse('caisse_fne_certifier', args=[ticket.numero]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(relance.status_code, 200)
        self.assertTrue(relance.json()['fne']['certifiee'])

    def test_liste_des_ventes_propose_reimpression_ou_relance(self, _mqtt, post):
        post.return_value = reponse_fne()
        _, certifiee = self.creer_vente()
        self.encaisser(certifiee)
        post.return_value = reponse_fne(500, {'message': 'Internal Server Error', 'statusCode': 500})
        _, en_echec = self.creer_vente()
        self.encaisser(en_echec)

        page = self.client.get(reverse('caissiere')).content.decode()

        self.assertIn('reprint-fne', page)
        self.assertIn(f'data-ticket="{certifiee.numero}"', page)
        self.assertIn('certifier-fne', page)
        self.assertIn('stickers', page)

    def test_liste_des_ventes_accueil_peut_relancer_la_fne(self, _mqtt, post):
        from Userauths.models import CustomPermission, TypeCustomPermission

        post.return_value = reponse_fne(400, {
            'statusCode': 400, 'errors': {'pointOfSale': {'invalid': 'Point of sale is invalid'}},
        })
        _, ticket = self.creer_vente()
        self.encaisser(ticket)

        accueil = User.objects.create_user(
            username='accueil', email='accueil@example.com', password='x',
            role='accueil', local_entrepot=self.localite,
        )
        categorie = TypeCustomPermission.objects.create(categorie='Liste')
        CustomPermission.objects.create(
            name='Liste des ventes', url='liste_ventes', categorie=categorie,
        ).users.add(accueil)
        self.client.force_login(accueil)

        page = self.client.get(reverse('liste_ventes')).content.decode()
        self.assertIn('certifier-fne', page)
        self.assertIn('Point de vente FNE inconnu', page)

        post.return_value = reponse_fne()
        relance = self.client.post(
            reverse('caisse_fne_certifier', args=[ticket.numero]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(relance.status_code, 200)
        self.assertTrue(relance.json()['fne']['certifiee'])
        page = self.client.get(reverse('liste_ventes')).content.decode()
        self.assertIn('reprint-fne', page)
        self.assertEqual(
            self.client.get(reverse('printer_escpos_fne', args=[ticket.numero])).status_code, 200,
        )


@patch('stock.fne.requests.post')
@patch('stock.paiement_service.publish_paiement_valide')
class ImpressionUnique(FNEBase):
    """Poste qui imprime via WebUSB : le serveur ne doit rien imprimer en plus."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.caissier)

    def encaisser(self, ticket, impression_poste):
        return self.client.post(
            reverse('valid_pay_article', args=[ticket.numero]),
            {'montant': '50000', 'moyen_paiement': get_moyen_espece().pk},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            HTTP_X_IMPRESSION_POSTE=impression_poste,
        )

    @patch.object(printer_service, 'HAS_USB', True)
    @patch.object(printer_service, 'print_fne_receipt_for_request')
    @patch.object(printer_service, 'print_receipt_for_request')
    def test_poste_webusb_pas_de_seconde_impression_serveur(self, recu, recu_fne, _mqtt, post):
        post.return_value = reponse_fne()
        self.assertTrue(self.encaisser(self.creer_vente()[1], '1').json()['success'])
        recu.assert_not_called()
        recu_fne.assert_not_called()

    @patch.object(printer_service, 'HAS_USB', True)
    @patch.object(printer_service, 'print_fne_receipt_for_request')
    @patch.object(printer_service, 'print_receipt_for_request')
    def test_sans_webusb_le_serveur_imprime_recu_puis_fne(self, recu, recu_fne, _mqtt, post):
        post.return_value = reponse_fne()
        self.encaisser(self.creer_vente()[1], '0')
        recu.assert_called_once()
        recu_fne.assert_called_once()
