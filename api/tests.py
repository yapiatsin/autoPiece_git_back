"""Tests API v1 client mobile."""
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from Userauths.models import CustomUser, LocalEntrepot, ProfilUser
from stock.models import Categorie, Piece, StockLocal


class APIV1PublicTests(APITestCase):
    def test_home(self):
        response = self.client.get('/api/v1/home/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('categories', response.data)
        self.assertIn('top_products', response.data)

    def test_categories(self):
        response = self.client.get('/api/v1/catalog/categories/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)

    def test_search_popular(self):
        response = self.client.get('/api/v1/search/popular/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_localites(self):
        response = self.client.get('/api/v1/localites/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_legacy_api_deprecated(self):
        response = self.client.get('/api/')
        self.assertEqual(response.status_code, 410)


class APIV1CategorieActifTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.local = LocalEntrepot.objects.create(nom='Cat Actif Local')
        cls.cat_active = Categorie.objects.create(categorie='Active Cat', actif=True)
        cls.cat_inactive = Categorie.objects.create(categorie='Inactive Cat', actif=False)
        cls.piece_active = Piece.objects.create(
            categorie=cls.cat_active,
            numero_piece='ACT-001',
            designation='Piece active',
            prix_achat=100,
            prix_unitaire=500,
            active_sortie=True,
        )
        cls.piece_inactive = Piece.objects.create(
            categorie=cls.cat_inactive,
            numero_piece='INA-001',
            designation='Piece inactive cat',
            prix_achat=100,
            prix_unitaire=500,
            active_sortie=True,
        )
        for piece in (cls.piece_active, cls.piece_inactive):
            StockLocal.objects.create(
                piece=piece,
                local_entrepot=cls.local,
                quantite_disponible=5,
                active_sortie=True,
            )

    def test_inactive_category_excluded_from_catalog(self):
        response = self.client.get('/api/v1/catalog/categories/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row['categorie'] for row in response.data['results']]
        self.assertIn('Active Cat', names)
        self.assertNotIn('Inactive Cat', names)

    def test_inactive_category_products_excluded_from_listing(self):
        response = self.client.get('/api/v1/catalog/products/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [row['id'] for row in response.data['results']]
        self.assertIn(self.piece_active.pk, ids)
        self.assertNotIn(self.piece_inactive.pk, ids)

    def test_inactive_category_product_detail_not_found(self):
        response = self.client.get(f'/api/v1/catalog/products/{self.piece_inactive.pk}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class APIV1AuthTests(APITestCase):
    def test_register_and_login(self):
        payload = {
            'username': 'client_mobile',
            'email': 'mobile@test.com',
            'password': 'TestPass123!',
            'password2': 'TestPass123!',
            'first_name': 'Mobile',
            'last_name': 'Client',
            'contact': '0700000000',
        }
        reg = self.client.post('/api/v1/auth/register/', payload, format='json')
        self.assertEqual(reg.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', reg.data)
        user = CustomUser.objects.get(username='client_mobile')
        self.assertEqual(user.role, 'client')

        login = self.client.post('/api/v1/auth/login/', {
            'email': 'mobile@test.com',
            'password': 'TestPass123!',
        }, format='json')
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertIn('access', login.data)

    def test_me_requires_auth(self):
        response = self.client.get('/api/v1/auth/me/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class APIV1ClientFlowTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.local = LocalEntrepot.objects.create(nom='Test Local')
        cls.user = CustomUser.objects.create_user(
            username='flowclient',
            email='flow@test.com',
            password='TestPass123!',
            role='client',
            local_entrepot=cls.local,
        )
        ProfilUser.objects.get_or_create(user=cls.user)
        cat = Categorie.objects.create(categorie='Freinage')
        cls.piece = Piece.objects.create(
            categorie=cat,
            numero_piece='TEST-001',
            designation='Plaquette test',
            prix_achat=1000,
            prix_unitaire=5000,
            active_sortie=True,
        )
        from stock.models import StockLocal
        StockLocal.objects.create(
            piece=cls.piece,
            local_entrepot=cls.local,
            quantite_disponible=10,
            active_sortie=True,
        )

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def test_product_detail(self):
        response = self.client.get(f'/api/v1/catalog/products/{self.piece.pk}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['designation'], 'Plaquette test')

    def test_cart_add_and_list(self):
        add = self.client.post('/api/v1/cart/items/', {
            'piece_id': self.piece.pk,
            'quantite': 2,
        }, format='json', HTTP_X_ECOM_LOCAL=str(self.local.code))
        self.assertEqual(add.status_code, status.HTTP_201_CREATED)
        self.assertEqual(add.data['total_quantite'], 2)

        cart = self.client.get('/api/v1/cart/', HTTP_X_ECOM_LOCAL=str(self.local.code))
        self.assertEqual(cart.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(cart.data['panier'])

    def test_favorites_toggle(self):
        toggle = self.client.post(f'/api/v1/favorites/{self.piece.pk}/toggle/')
        self.assertEqual(toggle.status_code, status.HTTP_200_OK)
        self.assertTrue(toggle.data['est_favori'])

        favs = self.client.get('/api/v1/favorites/')
        self.assertEqual(favs.status_code, status.HTTP_200_OK)
        self.assertEqual(favs.data['count'], 1)

    def test_account(self):
        response = self.client.get('/api/v1/account/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('stats', response.data)
        stats = response.data['stats']
        self.assertIn('total_achats_periode', stats)
        self.assertIn('nb_commandes_periode', stats)
        self.assertIn('mois', stats)
        self.assertIn('annee', stats)
        self.assertIn('annees_disponibles', stats)

        filtered = self.client.get('/api/v1/account/', {'mois': 1, 'annee': 2020})
        self.assertEqual(filtered.status_code, status.HTTP_200_OK)
        self.assertEqual(filtered.data['stats']['mois'], 1)
        self.assertEqual(filtered.data['stats']['annee'], 2020)

    def test_local_select(self):
        other = LocalEntrepot.objects.create(nom='Autre Local')
        response = self.client.post('/api/v1/localites/select/', {'code': str(other.code)}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.local_entrepot_id, other.pk)
