from decimal import Decimal
import json
from datetime import date

from django.core.paginator import Paginator
from django.db.models import Q, Sum, Min, Max, Count
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import TemplateView

from Userauths.models import CustomUser, LocalEntrepot, ProfilUser, JOURS_SEMAINE
from Userauths.forms import ChangePasswordForm
from stock.models import Categorie, Commande, MoyenPaiement, Panier, PanierItem, Piece
from stock.period_filters import periode_filter_context, build_filtre_resume
from stock.stock_local_service import get_prix_unitaire, total_panier_items

from .models import (
    CommuneLivraison,
    FavoriPiece,
    NewsletterAbonne,
    PaysLivraison,
    VilleLivraison,
    VueRecentePiece,
)
from .forms import EcomAccountAddressForm, EcomAccountProfileForm, NewsletterForm
from .context_processors import ECOM_API_PATH_PREFIXES, get_ecom_cart_context, safe_ecom_next_url

from .services import (
    MAX_VUES_RECENTES_INDEX,
    MAX_VUES_RECENTES_PREVIEW,
    FREE_SHIPPING_THRESHOLD,
    ROLES_LIVREUR,
    ROLES_MAGASIN,
    ROLES_STAFF_CMD,
    ajouter_au_panier_online,
    assigner_livreur,
    categories_pour_localite,
    confirmer_reception_client,
    annuler_commande_client,
    catalogue_groupe_par_localite,
    definir_quantite_panier_piece,
    enrichir_piece_stock,
    enregistrer_recherche,
    enregistrer_vue_recente,
    effacer_recherches_recentes,
    filtrer_localites_catalogue,
    filtrer_pieces_boutique,
    frais_livraison_payload,
    get_frais_livraison,
    get_local_from_session,
    lignes_catalogue_shop,
    lignes_catalogue_toutes_localites,
    lignes_favoris,
    lignes_vues_recentes,
    get_local_from_code,
    liste_communes_actives,
    liste_pays_actifs,
    liste_villes_actives,
    livrer_commande_livreur,
    mettre_a_jour_quantite_panier,
    payer_commande_livreur,
    pieces_pour_catalogue,
    lignes_pieces_plus_commandees,
    quantite_disponible_piece,
    queryset_categories_catalogue,
    queryset_panier_online_actif,
    queryset_piece_fiche,
    queryset_pieces_local,
    queryset_pieces_toutes_localites,
    retirer_du_panier,
    set_local_in_session,
    valider_commande_magasin,
    valider_commande_online,
)


def page_not_found(request, exception=None):
    return render(request, 'e_autopiece/404.html', status=404)


def _require_client(user):
    return user.is_authenticated and user.role in ('client', 'admin')


def _require_staff_cmd(user):
    return user.is_authenticated and user.role in ROLES_STAFF_CMD


def _require_livreur(user):
    return user.is_authenticated and user.role in ROLES_LIVREUR


def _require_magasin(user):
    """Personnel magasin (tous rôles sauf client)."""
    return user.is_authenticated and (
        getattr(user, 'is_superuser', False) or user.role in ROLES_MAGASIN
    )


def _is_client_role(user):
    return getattr(user, 'role', None) == 'client'


def _deny_client_access(request):
    """Bloque le rôle client sur les écrans magasin ; redirige vers la boutique."""
    if _is_client_role(request.user):
        messages.error(request, 'Accès réservé au personnel du magasin.')
        return redirect('ecom_index')
    return None


def _staff_local(user):
    return getattr(user, 'local_entrepot', None)


def _catalogue_context(local, localites, pieces_all, *, index_next_url=None, shop_next_url=None):
    """Contexte partagé pour le catalogue avec carte et onglets localités."""
    if index_next_url is None:
        index_next_url = reverse('ecom_index')
    if shop_next_url is None:
        shop_next_url = reverse('ecom_shop')
    localites_json = [
        {
            'code': str(loc.code),
            'nom': loc.nom,
            'lat': float(loc.latitude) if loc.latitude is not None else None,
            'lng': float(loc.longitude) if loc.longitude is not None else None,
        }
        for loc in localites
    ]
    catalogue_par_localite = catalogue_groupe_par_localite(pieces_all, localites)
    catalogue_local_tabs = [
        {
            'localite': loc,
            'rows': catalogue_par_localite.get(str(loc.code), []),
        }
        for loc in localites
    ]
    catalogue_all_display = lignes_catalogue_toutes_localites(pieces_all, localites)
    return {
        'localites': localites,
        'localites_json': json.dumps(localites_json),
        'local_selectionne': local,
        'catalogue_par_localite': catalogue_par_localite,
        'catalogue_local_tabs': catalogue_local_tabs,
        'catalogue_all_display': catalogue_all_display,
        'index_next_url': index_next_url,
        'shop_next_url': shop_next_url,
    }


def _ecom_context(request, local=None):
    """Contexte commun (localité, panier, vues récentes)."""
    local = local or get_local_from_session(request)
    cart_count = 0
    if request.user.is_authenticated and local:
        panier = queryset_panier_online_actif(request.user, local).first()
        if panier:
            cart_count = PanierItem.objects.filter(panier=panier).aggregate(
                total=Sum('quantite')
            )['total'] or 0
    vues_recentes_rows = []
    if request.user.is_authenticated:
        vues_recentes_rows = lignes_vues_recentes(
            request.user, local, limit=MAX_VUES_RECENTES_PREVIEW,
        )
    return {
        'local_selectionne': local,
        'cart_count': cart_count,
        'vues_recentes_rows': vues_recentes_rows,
    }


def about(request):
    ctx = _ecom_context(request)
    nb_localites = LocalEntrepot.objects.filter(statut=True).count()
    nb_pieces = Piece.objects.filter(active_sortie=True).count()
    ctx.update({
        'about_stats': {
            'nb_localites': nb_localites,
            'nb_pieces': nb_pieces,
        },
    })
    return render(request, 'e_autopiece/about.html', ctx)


def contact(request):
    ctx = _ecom_context(request)
    localites = LocalEntrepot.objects.all().order_by('nom')
    localites_json = [
        {
            'code': str(loc.code),
            'nom': loc.nom,
            'lat': float(loc.latitude) if loc.latitude is not None else None,
            'lng': float(loc.longitude) if loc.longitude is not None else None,
        }
        for loc in localites
    ]
    ctx.update({
        'localites': localites,
        'localites_json': json.dumps(localites_json),
        'form_data': {'services': []},
    })

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        subject = request.POST.get('subject', '').strip()
        message = request.POST.get('message', '').strip()
        services = request.POST.getlist('services')
        ctx['form_data'] = {
            'name': name,
            'email': email,
            'phone': phone,
            'subject': subject,
            'message': message,
            'services': services,
        }
        if not name or not email or not subject or not message:
            messages.error(request, 'Veuillez remplir tous les champs obligatoires.')
        else:
            messages.success(
                request,
                'Merci ! Votre message a bien été envoyé. Nous vous répondrons rapidement.',
            )
            ctx['form_data'] = {'services': []}

    return render(request, 'e_autopiece/contact.html', ctx)


def privacy_policy(request):
    return render(request, 'e_autopiece/privacy-policy.html', _ecom_context(request))


def cookies_policy(request):
    return render(request, 'e_autopiece/cookies-policy.html', _ecom_context(request))


@require_POST
def newsletter_subscribe(request):
    form = NewsletterForm(request.POST)
    next_url = request.POST.get('next') or '/'
    if not next_url.startswith('/') or next_url.startswith('//'):
        next_url = '/'
    if not form.is_valid():
        messages.error(request, 'Veuillez saisir une adresse e-mail valide.')
        return redirect(next_url)

    email = form.cleaned_data['email']
    accepte_offres = form.cleaned_data.get('accepte_offres', True)
    abonne, created = NewsletterAbonne.objects.get_or_create(
        email=email,
        defaults={'accepte_offres': accepte_offres, 'actif': True},
    )
    if created:
        messages.success(request, 'Merci ! Vous êtes abonné à notre newsletter.')
    elif abonne.actif:
        abonne.accepte_offres = accepte_offres
        abonne.save(update_fields=['accepte_offres', 'date_mise_a_jour'])
        messages.info(request, 'Cette adresse est déjà abonnée à la newsletter.')
    else:
        abonne.actif = True
        abonne.accepte_offres = accepte_offres
        abonne.save(update_fields=['actif', 'accepte_offres', 'date_mise_a_jour'])
        messages.success(request, 'Votre abonnement à la newsletter a été réactivé.')
    return redirect(next_url)


@require_POST
def search_clear_recent(request):
    """Efface l'historique de recherches récentes (utilisateur ou session)."""
    deleted = effacer_recherches_recentes(request)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'deleted': deleted})
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or '/'
    if not next_url.startswith('/') or next_url.startswith('//'):
        next_url = '/'
    return redirect(next_url)


def terms_condition(request):
    return render(request, 'e_autopiece/terms-condition.html', _ecom_context(request))


SUPPORT_THEMES = (
    {
        'slug': 'paiements',
        'label': 'Paiements',
        'icon': 'fa-credit-card',
        'faqs': (
            {
                'q': 'Quels modes de paiement sont acceptés sur Auto-Pièce ?',
                'a': (
                    'Vous pouvez payer en espèces à la livraison ou au retrait en agence, '
                    'ou en ligne via GeniusPay (Wave, Orange Money, MTN MoMo, carte bancaire).'
                ),
            },
            {
                'q': 'Mes informations de paiement sont-elles sécurisées ?',
                'a': (
                    'Oui. Le paiement en ligne passe par la page sécurisée GeniusPay : '
                    'nous ne stockons pas de données bancaires ni de codes Mobile Money. '
                    'Le règlement en espèces se fait à la réception ou en agence.'
                ),
            },
            {
                'q': 'Que faire si mon paiement est refusé ?',
                'a': (
                    'Pour un paiement en ligne, réessayez depuis « Mes commandes » ou choisissez un autre moyen '
                    '(Wave, Orange, MTN, carte) sur la page GeniusPay. '
                    'Pour un paiement en espèces, vérifiez le montant sur votre bon de commande puis contactez l’agence.'
                ),
            },
            {
                'q': 'Puis-je payer en plusieurs fois ?',
                'a': (
                    'Le paiement fractionné n’est pas disponible en ligne pour l’instant. '
                    'Pour une commande importante, rapprochez-vous de votre agence Auto-Pièce.'
                ),
            },
        ),
    },
    {
        'slug': 'commandes',
        'label': 'Commandes',
        'icon': 'fa-bag-shopping',
        'faqs': (
            {
                'q': 'Comment passer une commande en ligne ?',
                'a': (
                    'Choisissez d’abord une localité, ajoutez vos pièces au panier, puis validez via Checkout. '
                    'Vous devez être connecté avec un compte client.'
                ),
            },
            {
                'q': 'Comment suivre ma commande ?',
                'a': (
                    'Rendez-vous dans « Mes commandes » ou dans l’onglet Commandes de « Mon compte ». '
                    'Vous y voyez le statut (en attente, validée, en livraison, livrée).'
                ),
            },
            {
                'q': 'Puis-je modifier ou annuler une commande ?',
                'a': (
                    'Tant que la commande n’a pas été validée par le magasin, contactez rapidement le support '
                    'ou l’agence. Après validation, les modifications dépendent du stock et du statut de préparation.'
                ),
            },
            {
                'q': 'Comment confirmer que j’ai bien reçu ma commande ?',
                'a': (
                    'Dans « Mes commandes », utilisez l’action « J’ai reçu » lorsque la livraison est terminée. '
                    'Cela clôture le suivi côté client.'
                ),
            },
        ),
    },
    {
        'slug': 'livraison',
        'label': 'Livraison & retrait',
        'icon': 'fa-truck',
        'faqs': (
            {
                'q': 'Quelles options de réception sont disponibles ?',
                'a': (
                    'Selon votre localité : livraison à domicile ou retrait en agence. '
                    'Le mode est choisi au checkout et confirmé par l’équipe magasin.'
                ),
            },
            {
                'q': 'Quels sont les délais de livraison ?',
                'a': (
                    'Les délais dépendent de la disponibilité en stock local et de la zone de livraison. '
                    'Après validation magasin, un livreur peut être assigné pour finaliser la remise.'
                ),
            },
            {
                'q': 'La livraison est-elle gratuite ?',
                'a': (
                    'Des conditions de livraison gratuite peuvent s’appliquer selon le montant du panier '
                    'et la localité. Le détail est rappelé dans le panier et au checkout.'
                ),
            },
            {
                'q': 'Que faire si je suis absent à la livraison ?',
                'a': (
                    'Le livreur ou l’agence vous recontactera. Vous pouvez aussi choisir le retrait en agence '
                    'pour une récupération à votre convenance pendant les horaires d’ouverture.'
                ),
            },
        ),
    },
    {
        'slug': 'retours',
        'label': 'Retours & garantie',
        'icon': 'fa-rotate-left',
        'faqs': (
            {
                'q': 'Puis-je retourner une pièce ?',
                'a': (
                    'Oui, sous conditions : pièce non montée, emballage d’origine, et délai raisonnable après réception. '
                    'Contactez le support ou l’agence de commande pour ouvrir une demande.'
                ),
            },
            {
                'q': 'Quelles pièces ne sont pas reprises ?',
                'a': (
                    'Les pièces électriques ouvertes, les consommables déjà utilisés, et les articles endommagés '
                    'par une mauvaise installation ne sont généralement pas repris.'
                ),
            },
            {
                'q': 'Comment fonctionne la garantie ?',
                'a': (
                    'La garantie dépend du type de pièce et du fabricant. Conservez votre facture : '
                    'elle est disponible depuis « Mes commandes » / facture.'
                ),
            },
            {
                'q': 'Combien de temps pour un remboursement ou un échange ?',
                'a': (
                    'Après validation du retour par l’agence, l’échange ou le remboursement est traité '
                    'selon le mode de paiement initial et la disponibilité de la pièce de remplacement.'
                ),
            },
        ),
    },
    {
        'slug': 'pieces',
        'label': 'Pièces & compatibilité',
        'icon': 'fa-gears',
        'faqs': (
            {
                'q': 'Comment savoir si une pièce est compatible avec mon véhicule ?',
                'a': (
                    'Vérifiez la désignation, la référence constructeur et les infos véhicule sur la fiche produit. '
                    'En cas de doute, contactez l’agence avec la marque, le modèle et l’année.'
                ),
            },
            {
                'q': 'Les stocks sont-ils les mêmes partout ?',
                'a': (
                    'Non. Chaque localité a son propre stock et ses prix. '
                    'Sélectionnez votre agence pour voir la disponibilité réelle avant d’ajouter au panier.'
                ),
            },
            {
                'q': 'Puis-je réserver une pièce en magasin ?',
                'a': (
                    'La commande en ligne réserve le besoin auprès de l’agence sélectionnée. '
                    'Pour une réservation spécifique, passez aussi par le contact ou l’agence.'
                ),
            },
            {
                'q': 'Que faire si la pièce reçue ne correspond pas ?',
                'a': (
                    'Ne montez pas la pièce. Prenez une photo, conservez l’emballage, puis ouvrez une demande '
                    'via le support ou l’agence avec votre numéro de commande.'
                ),
            },
        ),
    },
    {
        'slug': 'compte',
        'label': 'Compte',
        'icon': 'fa-user',
        'faqs': (
            {
                'q': 'Comment créer un compte client ?',
                'a': (
                    'Utilisez « Inscription », puis activez votre compte via le lien e-mail reçu. '
                    'Sans activation, la connexion et les commandes en ligne peuvent être bloquées.'
                ),
            },
            {
                'q': 'J’ai oublié mon mot de passe, que faire ?',
                'a': (
                    'Sur la page de connexion, cliquez sur « Mot de passe oublié » et suivez la procédure OTP / e-mail '
                    'pour définir un nouveau mot de passe.'
                ),
            },
            {
                'q': 'Comment modifier mon adresse de livraison ?',
                'a': (
                    'Dans « Mon compte », ouvrez l’onglet Adresse pour mettre à jour rue, ville, pays et code postal.'
                ),
            },
            {
                'q': 'Puis-je gérer mes favoris et pièces vues récemment ?',
                'a': (
                    'Oui. Les favoris et l’historique « Vus récemment » sont accessibles depuis le menu '
                    'et facilitent le recommande de pièces.'
                ),
            },
        ),
    },
    {
        'slug': 'agences',
        'label': 'Agences',
        'icon': 'fa-store',
        'faqs': (
            {
                'q': 'Comment choisir ma localité / agence ?',
                'a': (
                    'Depuis l’accueil ou la page Localités, sélectionnez l’agence la plus proche. '
                    'Le catalogue, les stocks et le panier dépendent de cette sélection.'
                ),
            },
            {
                'q': 'Quels sont les horaires des agences ?',
                'a': (
                    'En général : lundi–samedi 8h–18h, dimanche fermé. '
                    'Vérifiez la fiche de votre localité pour les éventuelles particularités.'
                ),
            },
            {
                'q': 'Puis-je changer d’agence après avoir rempli mon panier ?',
                'a': (
                    'Oui, mais les disponibilités et prix peuvent changer. '
                    'Vérifiez toujours le panier après un changement de localité.'
                ),
            },
            {
                'q': 'Comment contacter une agence précise ?',
                'a': (
                    'Consultez la page Localités / détail d’agence, ou utilisez la page Contact. '
                    'Indiquez votre numéro de commande pour un traitement plus rapide.'
                ),
            },
        ),
    },
)
def support(request):
    theme_slug = (request.GET.get('theme') or 'paiements').strip().lower()
    themes = SUPPORT_THEMES
    active_theme = next((t for t in themes if t['slug'] == theme_slug), themes[0])
    ctx = _ecom_context(request)
    ctx.update({
        'support_themes': themes,
        'active_theme': active_theme,
    })
    return render(request, 'e_autopiece/support.html', ctx)


def localites_grid(request):
    """Grille des localités / agences (style vendor-grid)."""
    from django.core.paginator import Paginator

    qs = filtrer_localites_catalogue(request)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    query = request.GET.copy()
    query.pop('page', None)

    ctx = _ecom_context(request)
    ctx.update({
        'localites': page_obj.object_list,
        'localites_page': page_obj,
        'localites_total': paginator.count,
        'localites_query': query.urlencode(),
        'localites_filters': {
            'q': request.GET.get('q', '').strip(),
            'sort': request.GET.get('sort', 'nom'),
            'view': request.GET.get('view', 'grid'),
        },
    })
    return render(request, 'e_autopiece/vendor-grid.html', ctx)


def localite_detail(request, local_code):
    """Détail d'une localité + pièces disponibles (style vendor-details)."""
    from django.core.paginator import Paginator

    localite = get_object_or_404(
        LocalEntrepot.objects.prefetch_related('creneaux'),
        code=local_code,
    )
    categories = categories_pour_localite(localite)

    qs = queryset_pieces_local(localite)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(designation__icontains=q)
            | Q(numero_piece__icontains=q)
            | Q(categorie__categorie__icontains=q)
            | Q(sous_categorie__nom__icontains=q)
        )
    cat_ids = []
    for raw in request.GET.getlist('categorie'):
        raw = str(raw).strip()
        if not raw:
            continue
        try:
            cat_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if cat_ids:
        qs = qs.filter(categorie_id__in=cat_ids)
    sous_ids = []
    for raw in request.GET.getlist('sous_categorie'):
        raw = str(raw).strip()
        if not raw:
            continue
        try:
            sous_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if sous_ids:
        qs = qs.filter(sous_categorie_id__in=sous_ids)

    sort = request.GET.get('sort', 'designation')
    if sort == 'price_asc':
        qs = qs.order_by('prix_unitaire', 'designation')
    elif sort == 'price_desc':
        qs = qs.order_by('-prix_unitaire', 'designation')
    else:
        qs = qs.order_by('designation')

    pieces = list(qs)
    rows = lignes_catalogue_shop(pieces, localite, filter_local=localite)
    paginator = Paginator(rows, 12)
    page_obj = paginator.get_page(request.GET.get('page'))

    query = request.GET.copy()
    query.pop('page', None)

    creneaux_par_jour = {c.jour: c for c in localite.creneaux.all()}
    jours_courts = {
        0: 'Lun', 1: 'Mar', 2: 'Mer', 3: 'Jeu',
        4: 'Ven', 5: 'Sam', 6: 'Dim',
    }
    horaires_semaine = []
    for jour_num, jour_label in JOURS_SEMAINE:
        creneau = creneaux_par_jour.get(jour_num)
        if creneau:
            horaires_semaine.append({
                'jour': jour_num,
                'jour_court': jours_courts[jour_num],
                'jour_label': jour_label,
                'ouvert': True,
                'heure_ouverture': creneau.heure_ouverture,
                'heure_fermeture': creneau.heure_fermeture,
            })
        else:
            horaires_semaine.append({
                'jour': jour_num,
                'jour_court': jours_courts[jour_num],
                'jour_label': jour_label,
                'ouvert': False,
                'heure_ouverture': None,
                'heure_fermeture': None,
            })

    ctx = _ecom_context(request)
    ctx.update({
        'localite': localite,
        'categories': categories,
        'shop_rows': page_obj.object_list,
        'shop_page': page_obj,
        'shop_total': paginator.count,
        'shop_query': query.urlencode(),
        'selected_categories': [str(c) for c in cat_ids],
        'selected_sous_categories': [str(s) for s in sous_ids],
        'localite_filters': {
            'q': q,
            'sort': sort,
        },
        'shop_next_url': request.get_full_path(),
        'horaires_semaine': horaires_semaine,
        'localite_ouverte': localite.est_ouvert_maintenant(),
    })
    return render(request, 'e_autopiece/vendor-details.html', ctx)


def shop(request):
    from django.core.paginator import Paginator
    local = get_local_from_session(request)
    localites = LocalEntrepot.objects.all().order_by('nom')
    categories = queryset_categories_catalogue()

    q = request.GET.get('q', '').strip()
    if q:
        enregistrer_recherche(request, q)

    filter_local = get_local_from_code(request.GET.get('localite', '').strip()) or local
    qs = filtrer_pieces_boutique(request)
    sort = request.GET.get('sort', 'designation')
    if sort == 'price_asc':
        qs = qs.order_by('prix_unitaire', 'designation')
    elif sort == 'price_desc':
        qs = qs.order_by('-prix_unitaire', 'designation')
    else:
        qs = qs.order_by('designation')

    shop_rows_all = lignes_catalogue_shop(list(qs), local, filter_local=filter_local)
    paginator = Paginator(shop_rows_all, 40)
    page_obj = paginator.get_page(request.GET.get('page'))

    query = request.GET.copy()
    query.pop('page', None)
    shop_query = query.urlencode()

    # Fenêtre de numéros de page autour de la page courante
    page_window = 2
    current = page_obj.number
    start_page = max(current - page_window, 1)
    end_page = min(current + page_window, paginator.num_pages)
    shop_page_numbers = list(range(start_page, end_page + 1))

    prix_bounds = queryset_pieces_toutes_localites().aggregate(
        pmin=Min('prix_unitaire'),
        pmax=Max('prix_unitaire'),
    )
    bound_min = int(prix_bounds['pmin'] or 0)
    bound_max = int(prix_bounds['pmax'] or 500000)
    if bound_max <= bound_min:
        bound_max = bound_min + 100000
    # Arrondi supérieur pour une plage confortable
    bound_max = ((bound_max + 9999) // 10000) * 10000

    ctx = _ecom_context(request, local)
    ctx.update({
        'localites': localites,
        'local_selectionne': local,
        'filter_local': filter_local,
        'categories': categories,
        'shop_rows': page_obj.object_list,
        'shop_page': page_obj,
        'shop_total': paginator.count,
        'shop_query': shop_query,
        'shop_page_numbers': shop_page_numbers,
        'selected_categories': [c for c in request.GET.getlist('categorie') if str(c).strip()],
        'selected_sous_categories': [c for c in request.GET.getlist('sous_categorie') if str(c).strip()],
        'shop_price_bound_min': bound_min,
        'shop_price_bound_max': bound_max,
        'shop_filters': {
            'q': request.GET.get('q', '').strip(),
            'prix_min': request.GET.get('prix_min', ''),
            'prix_max': request.GET.get('prix_max', ''),
            'localite': request.GET.get('localite', ''),
            'sort': sort,
        },
        'shop_next_url': request.get_full_path(),
    })
    ctx.update(_geo_livraison_context(request))
    return render(request, 'e_autopiece/shop-grid-sidebar.html', ctx)


def shop_detail(request, piece_id, slug=None):
    local = get_local_from_session(request)
    piece = get_object_or_404(queryset_piece_fiche(), pk=piece_id)
    if slug != piece.slug:
        return redirect(piece.get_absolute_url(), permanent=True)
    enrichir_piece_stock(piece, local)
    if request.user.is_authenticated and _require_client(request.user):
        enregistrer_vue_recente(request.user, piece)
    cart_quantite = 0
    if request.user.is_authenticated and local:
        panier = queryset_panier_online_actif(request.user, local).first()
        if panier:
            cart_item = PanierItem.objects.filter(panier=panier, piece=piece).first()
            if cart_item:
                cart_quantite = cart_item.quantite
    ctx = _ecom_context(request, local)
    ctx.update({
        'piece': piece,
        'prix': get_prix_unitaire(piece, local) if local else piece.prix_unitaire,
        'quantite': piece.quantite_disponible,
        'localite_code': str(local.code) if local else '',
        'localite_nom': local.nom if local else '',
        'cart_quantite': cart_quantite,
    })
    return render(request, 'e_autopiece/shop-details.html', ctx)


@login_required(login_url='connexion')
@require_POST
def piece_cart_quantity(request, piece_id):
    if not _require_client(request.user):
        return JsonResponse(
            {'success': False, 'error': 'Seuls les clients peuvent commander en ligne.'},
            status=403,
        )
    local = get_local_from_session(request)
    local_id = request.POST.get('local_id', '').strip()
    if local_id:
        local = get_object_or_404(LocalEntrepot, code=local_id)
        set_local_in_session(request, local)
    if not local:
        return JsonResponse(
            {'success': False, 'error': 'Choisissez d\'abord une localité.'},
            status=400,
        )
    piece = get_object_or_404(Piece, pk=piece_id)
    try:
        quantite = int(request.POST.get('quantite', 1))
    except (TypeError, ValueError):
        return JsonResponse(
            {'success': False, 'error': 'Quantité invalide.'},
            status=400,
        )
    try:
        panier, cart_qty = definir_quantite_panier_piece(
            request.user, local, piece, quantite,
        )
        stock_max = quantite_disponible_piece(piece, local)
        cart_ctx = get_ecom_cart_context(request, local)
        mini_cart_html = render_to_string(
            'e_autopiece/partials/_header_mini_cart.html',
            cart_ctx,
            request=request,
        )
        return JsonResponse({
            'success': True,
            'quantite': cart_qty,
            'cart_count': cart_ctx['ecom_cart_count'],
            'stock_max': stock_max,
            'in_cart': cart_qty > 0,
            'mini_cart_html': mini_cart_html,
        })
    except ValueError as exc:
        stock_max = quantite_disponible_piece(piece, local)
        return JsonResponse({
            'success': False,
            'error': str(exc),
            'stock_max': stock_max,
        }, status=400)


def _ecom_user_initials(user):
    first = (user.first_name or '').strip()
    last = (user.last_name or '').strip()
    if first and last:
        return f'{first[0]}{last[0]}'.upper()
    if first:
        return first[:2].upper()
    username = (user.username or '').strip()
    return username[:2].upper() if username else 'AP'


def _ecom_has_custom_photo(profil):
    if not profil or not profil.photo:
        return False
    name = (profil.photo.name or '').replace('\\', '/')
    return bool(name) and 'default' not in name


@login_required(login_url='connexion')
def account(request):
    if not _require_client(request.user):
        messages.error(request, 'Accès réservé aux clients.')
        return redirect('connexion')

    profil, _ = ProfilUser.objects.get_or_create(user=request.user)
    active_tab = request.GET.get('tab', 'dashboard')
    if active_tab not in {'dashboard', 'orders', 'address', 'details', 'password'}:
        active_tab = 'dashboard'

    profile_form = EcomAccountProfileForm(instance=profil, user=request.user)
    address_form = EcomAccountAddressForm(instance=profil)
    password_form = ChangePasswordForm(user=request.user)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'photo':
            active_tab = 'details'
            photo_file = request.FILES.get('photo')
            if photo_file:
                profil.photo = photo_file
                profil.save(update_fields=['photo', 'date_modification'])
                messages.success(request, 'Votre photo de profil a été mise à jour.')
                return redirect(f'{request.path}?tab=details')
            messages.error(request, 'Veuillez sélectionner une image.')
        elif action == 'profile':
            active_tab = 'details'
            profile_form = EcomAccountProfileForm(
                request.POST, instance=profil, user=request.user,
            )
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, 'Vos informations ont été mises à jour.')
                return redirect(f'{request.path}?tab=details')
            messages.error(request, 'Corrigez les erreurs du formulaire profil.')
        elif action == 'address':
            active_tab = 'address'
            address_form = EcomAccountAddressForm(request.POST, instance=profil)
            if address_form.is_valid():
                address_form.save()
                messages.success(request, 'Votre adresse a été enregistrée.')
                return redirect(f'{request.path}?tab=address')
            messages.error(request, 'Corrigez les erreurs du formulaire adresse.')
        elif action == 'password':
            active_tab = 'password'
            password_form = ChangePasswordForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                password_form.save()
                messages.success(request, 'Votre mot de passe a été modifié.')
                return redirect(f'{request.path}?tab=password')
            messages.error(request, 'Impossible de modifier le mot de passe. Vérifiez les champs.')

    commandes_qs = Commande.objects.filter(
        commande_en_ligne=True,
        panier__utilisateur=request.user,
    ).select_related('panier', 'panier__local_entrepot', 'livreur', 'moyen_paiement').order_by('-date')

    today = date.today()
    annee_courante = today.year
    mois_courant = today.month
    try:
        annee_achats = int(request.GET.get('annee') or annee_courante)
    except (TypeError, ValueError):
        annee_achats = annee_courante
    try:
        mois_achats = int(request.GET.get('mois') or mois_courant)
    except (TypeError, ValueError):
        mois_achats = mois_courant
    if mois_achats < 1 or mois_achats > 12:
        mois_achats = mois_courant

    # Dix dernières années (année en cours incluse)
    annees_disponibles = [annee_courante - i for i in range(10)]
    if annee_achats not in annees_disponibles:
        annee_achats = annee_courante

    commandes_periode = commandes_qs.filter(
        date__year=annee_achats,
        date__month=mois_achats,
    )
    commandes_payees_periode = commandes_periode.filter(paye=True)
    total_achats_periode = (
        commandes_payees_periode.aggregate(s=Sum('total'))['s'] or Decimal('0')
    )
    nb_commandes_periode = commandes_payees_periode.count()

    mois_labels = [
        (1, 'Janvier'), (2, 'Février'), (3, 'Mars'), (4, 'Avril'),
        (5, 'Mai'), (6, 'Juin'), (7, 'Juillet'), (8, 'Août'),
        (9, 'Septembre'), (10, 'Octobre'), (11, 'Novembre'), (12, 'Décembre'),
    ]
    mois_achats_label = dict(mois_labels).get(mois_achats, '')

    ctx = _ecom_context(request)
    ctx.update({
        'active_tab': active_tab,
        'profil': profil,
        'profile_form': profile_form,
        'address_form': address_form,
        'password_form': password_form,
        'user_initials': _ecom_user_initials(request.user),
        'has_custom_photo': _ecom_has_custom_photo(profil),
        'commandes': list(commandes_periode[:50]),
        'commandes_recentes': commandes_qs[:5],
        'stats_commandes': commandes_qs.count(),
        'stats_favoris': FavoriPiece.objects.filter(utilisateur=request.user).count(),
        'stats_vues': VueRecentePiece.objects.filter(utilisateur=request.user).count(),
        'mois_achats': mois_achats,
        'mois_achats_label': mois_achats_label,
        'mois_labels': mois_labels,
        'annee_achats': annee_achats,
        'annee_courante': annee_courante,
        'annees_disponibles': annees_disponibles,
        'total_achats_periode': total_achats_periode,
        'nb_commandes_periode': nb_commandes_periode,
    })
    return render(request, 'e_autopiece/account.html', ctx)


def _facture_commande_items(request, commande_id):
    """Récupère la commande en ligne du client connecté et ses lignes panier."""
    commande = get_object_or_404(
        Commande.objects.select_related(
            'panier__utilisateur',
            'panier__local_entrepot',
            'panier__livraison_pays',
            'panier__livraison_ville',
            'panier__livraison_commune',
            'livreur',
            'moyen_paiement',
        ),
        pk=commande_id,
        commande_en_ligne=True,
        panier__utilisateur=request.user,
    )
    items = list(
        PanierItem.objects.filter(panier=commande.panier).select_related('piece', 'piece__categorie', 'piece__sous_categorie')
    )
    return commande, items


def _facture_print_meta(commande):
    """Métadonnées d'impression / nom de fichier PDF pour la boîte du navigateur."""
    numero = commande.numero_commande or str(commande.pk)
    safe = str(numero).replace('/', '-').replace('\\', '-').replace(' ', '_')
    return {
        'print_title': f'Facture {numero}',
        'pdf_filename': f'Facture_{safe}.pdf',
    }


def _facture_ecom_context(request, commande, items, *, auto_print=False):
    panier = commande.panier
    frais = getattr(panier, 'frais_livraison', None) or Decimal('0')
    ctx = _ecom_context(request)
    ctx.update({
        'commande': commande,
        'items': items,
        'frais_livraison': frais if frais > 0 else None,
        'auto_print': auto_print,
        **_facture_print_meta(commande),
    })
    return ctx


def _commande_en_ligne_qs():
    return Commande.objects.filter(commande_en_ligne=True).select_related(
        'panier__utilisateur',
        'panier__local_entrepot',
        'panier__livraison_pays',
        'panier__livraison_ville',
        'panier__livraison_commune',
        'livreur',
        'moyen_paiement',
    )


def _commande_en_ligne_items(commande):
    items = list(
        PanierItem.objects.filter(panier=commande.panier).select_related('piece', 'piece__categorie', 'piece__sous_categorie')
    )
    frais = getattr(commande.panier, 'frais_livraison', None) or Decimal('0')
    return items, (frais if frais > 0 else None)


def _staff_can_access_commande_locale(user, commande):
    """Admin : tout. Livreur : ses assignations. Accueil/caissier/chefagence : leur localité."""
    from ecom.services import (
        ROLES_LIVREUR,
        ROLES_VUE_LOCAL_ENTREPOT,
        _is_admin_global,
    )
    if _is_admin_global(user):
        return True
    role = getattr(user, 'role', None)
    if role in ROLES_LIVREUR:
        return commande.livreur_id == user.pk
    if role in ROLES_VUE_LOCAL_ENTREPOT:
        local = _staff_local(user)
        if not local:
            return False
        return (
            commande.panier_id
            and commande.panier.local_entrepot_id == local.pk
        )
    return False


@login_required(login_url='connexion')
def invoice(request, commande_id):
    """Affiche la facture / reçu d'une commande en ligne."""
    commande, items = _facture_commande_items(request, commande_id)
    auto_print = request.GET.get('print') == '1'
    return render(
        request,
        'e_autopiece/invoice.html',
        _facture_ecom_context(request, commande, items, auto_print=auto_print),
    )


@login_required(login_url='connexion')
def imprimer_facture(request, commande_id):
    """
    Ouvre la facture et lance la boîte d'impression du navigateur.
    L'utilisateur peut imprimer le reçu ou choisir « Enregistrer au format PDF ».
    """
    commande, items = _facture_commande_items(request, commande_id)
    return render(
        request,
        'e_autopiece/invoice.html',
        _facture_ecom_context(request, commande, items, auto_print=True),
    )


def index(request):
    localites = LocalEntrepot.objects.all().order_by('nom')
    local = get_local_from_session(request)
    pieces_all = pieces_pour_catalogue(local)
    panier = None
    cart_count = 0
    if request.user.is_authenticated and local:
        panier = queryset_panier_online_actif(request.user, local).first()
        if panier:
            cart_count = PanierItem.objects.filter(panier=panier).aggregate(
                total=Sum('quantite')
            )['total'] or 0
    ctx = _catalogue_context(
        local, localites, pieces_all,
        index_next_url=reverse('ecom_index'),
        shop_next_url=reverse('ecom_shop'),
    )
    vues_recentes_rows = []
    if request.user.is_authenticated:
        vues_recentes_rows = lignes_vues_recentes(
            request.user, local, limit=MAX_VUES_RECENTES_INDEX,
        )
    pieces_plus_commandees_rows = lignes_pieces_plus_commandees(local)
    # Après login client : ouvrir le guide même si le délai 15 min n’est pas écoulé
    force_order_guide = bool(request.session.pop('show_ecom_order_guide', False))
    if request.GET.get('order_guide') == '1':
        force_order_guide = True
    ctx.update({
        'panier': panier,
        'cart_count': cart_count,
        'vues_recentes_rows': vues_recentes_rows,
        'pieces_plus_commandees_rows': pieces_plus_commandees_rows,
        'force_order_guide': force_order_guide,
    })
    return render(request, 'e_autopiece/index.html', ctx)


@require_POST
def select_local(request):
    local_id = request.POST.get('local_id')
    local = get_object_or_404(LocalEntrepot, code=local_id)
    set_local_in_session(request, local)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'local': local.nom})
    return redirect('ecom_index')


@login_required(login_url='connexion')
@require_POST
def add_to_cart(request, piece_id):
    if not _require_client(request.user):
        messages.error(request, 'Seuls les clients peuvent commander en ligne.')
        return redirect('connexion')
    local = get_local_from_session(request)
    local_id = request.POST.get('local_id', '').strip()
    if local_id:
        local = get_object_or_404(LocalEntrepot, code=local_id)
        set_local_in_session(request, local)
    if not local:
        messages.error(request, 'Choisissez d\'abord une localité.')
        return redirect('ecom_index')
    piece = get_object_or_404(Piece, pk=piece_id)
    try:
        quantite = int(request.POST.get('quantite', 1))
        if quantite < 1:
            quantite = 1
        definir_quantite_panier_piece(request.user, local, piece, quantite)
        messages.success(request, f'{piece.designation} ajouté au panier.')
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect(request.POST.get('next') or 'ecom_index')


def _is_ajax(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _cart_ajax_payload(request, local, *, piece_id=None, item_id=None, quantite=None, line_total=None, removed=False):
    cart_ctx = get_ecom_cart_context(request, local)
    mini_cart_html = render_to_string(
        'e_autopiece/partials/_header_mini_cart.html',
        cart_ctx,
        request=request,
    )
    payload = {
        'success': not removed,
        'removed': removed,
        'cart_count': cart_ctx['ecom_cart_count'],
        'mini_cart_html': mini_cart_html,
        'cart_subtotal': float(cart_ctx['ecom_cart_subtotal']),
        'shipping_remaining': float(cart_ctx['ecom_shipping_remaining']),
        'shipping_progress': cart_ctx['ecom_shipping_progress'],
    }
    if piece_id is not None:
        payload['piece_id'] = piece_id
    if item_id is not None:
        payload['item_id'] = item_id
    if quantite is not None:
        payload['quantite'] = quantite
    if line_total is not None:
        payload['line_total'] = float(line_total)
    return payload


@login_required(login_url='connexion')
def _geo_livraison_context(request):
    ville_id = (request.GET.get('livraison_ville') or request.session.get('ecom_livraison_ville') or '').strip()
    commune_id = (request.GET.get('livraison_commune') or request.session.get('ecom_livraison_commune') or '').strip()
    if 'livraison_ville' in request.GET:
        request.session['ecom_livraison_ville'] = ville_id
        request.session['ecom_livraison_commune'] = commune_id
    villes = list(liste_villes_actives())
    communes = list(liste_communes_actives(ville_id)) if ville_id.isdigit() else []
    return {
        'livraison_villes': villes,
        'livraison_communes': communes,
        'livraison_ville_id': ville_id,
        'livraison_commune_id': commune_id,
    }


def cart(request):
    if not _require_client(request.user):
        messages.error(request, 'Connectez-vous avec un compte client.')
        return redirect('connexion')
    local = get_local_from_session(request)
    if not local:
        messages.warning(request, 'Sélectionnez une localité pour voir votre panier.')
        return redirect('ecom_index')
    panier = queryset_panier_online_actif(request.user, local).first()
    items = list(PanierItem.objects.filter(panier=panier).select_related('piece', 'piece__categorie', 'piece__sous_categorie')) if panier else []
    for item in items:
        item.stock_disponible = quantite_disponible_piece(item.piece, local)
        enrichir_piece_stock(item.piece, local)
    total = total_panier_items(items, local, panier=panier) if panier else Decimal('0')
    ctx = _ecom_context(request, local)
    ctx.update({
        'local': local,
        'panier': panier,
        'items': items,
        'total': total,
    })
    ctx.update(_geo_livraison_context(request))
    return render(request, 'e_autopiece/cart.html', ctx)


@login_required(login_url='connexion')
@require_POST
def cart_clear(request):
    local = get_local_from_session(request)
    if local:
        panier = queryset_panier_online_actif(request.user, local).first()
        if panier:
            PanierItem.objects.filter(panier=panier).delete()
        messages.success(request, 'Panier vidé.')
    return redirect('ecom_cart')


@login_required(login_url='connexion')
def vues_recentes(request):
    if not _require_client(request.user):
        messages.error(request, 'Connectez-vous avec un compte client.')
        return redirect('connexion')
    local = get_local_from_session(request)
    ctx = _ecom_context(request, local)
    ctx['vues_recentes_rows'] = lignes_vues_recentes(request.user, local, limit=None)
    return render(request, 'e_autopiece/vues-recentes.html', ctx)


@login_required(login_url='connexion')
@require_POST
def cart_update(request, item_id):
    local = get_local_from_session(request)
    if not local:
        return redirect('ecom_index')
    try:
        quantite = int(request.POST.get('quantite', 1))
    except (TypeError, ValueError):
        quantite = 1
    ajax = _is_ajax(request)
    try:
        mettre_a_jour_quantite_panier(request.user, local, item_id, quantite)
    except PanierItem.DoesNotExist:
        if ajax:
            return JsonResponse(
                _cart_ajax_payload(
                    request, local, item_id=item_id, removed=True,
                ),
                status=404,
            )
        messages.warning(request, 'Cet article n\'est plus dans votre panier.')
        return redirect('ecom_cart')
    except ValueError as exc:
        if ajax:
            return JsonResponse({'success': False, 'error': str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect('ecom_cart')

    if ajax:
        panier = queryset_panier_online_actif(request.user, local).first()
        item = PanierItem.objects.filter(pk=item_id, panier=panier).select_related('piece').first()
        if not item:
            return JsonResponse(
                _cart_ajax_payload(
                    request, local, item_id=item_id, removed=True,
                ),
                status=404,
            )
        return JsonResponse(_cart_ajax_payload(
            request, local,
            piece_id=item.piece_id,
            item_id=item.pk,
            quantite=item.quantite,
            line_total=item.prix_total,
        ))

    messages.success(request, 'Panier mis à jour.')
    return redirect('ecom_cart')


@login_required(login_url='connexion')
@require_POST
def cart_remove(request, item_id):
    local = get_local_from_session(request)
    piece_id = None
    if local:
        panier = queryset_panier_online_actif(request.user, local).first()
        if panier:
            item = PanierItem.objects.filter(
                pk=item_id, panier=panier,
            ).select_related('piece').first()
            if item:
                piece_id = item.piece_id
        retirer_du_panier(request.user, local, item_id)
        messages.success(request, 'Article retiré du panier.')

    if _is_ajax(request):
        return JsonResponse(_cart_ajax_payload(
            request, local,
            piece_id=piece_id,
            item_id=item_id,
            removed=True,
        ))

    next_url = (request.POST.get('next') or '').strip()
    if next_url.startswith('/') and any(
        next_url.startswith(prefix) for prefix in ECOM_API_PATH_PREFIXES
    ):
        next_url = ''
    return redirect(next_url or safe_ecom_next_url(request))


@login_required(login_url='connexion')
def wishlist(request):
    if not _require_client(request.user):
        messages.error(request, 'Connectez-vous avec un compte client.')
        return redirect('connexion')
    local = get_local_from_session(request)
    ctx = _ecom_context(request, local)
    ctx['favoris_rows'] = lignes_favoris(request.user, local)
    ctx['favoris'] = [row['favori'] for row in ctx['favoris_rows']]
    return render(request, 'e_autopiece/wishlist.html', ctx)


@login_required(login_url='connexion')
@require_POST
def favori_add(request, piece_id):
    if not _require_client(request.user):
        return redirect('connexion')
    piece = get_object_or_404(Piece, pk=piece_id)
    _, created = FavoriPiece.objects.get_or_create(utilisateur=request.user, piece=piece)
    if created:
        messages.success(request, f'{piece.designation} ajouté aux favoris.')
    else:
        messages.info(request, 'Cet article est déjà dans vos favoris.')
    return redirect(request.POST.get('next') or 'ecom_wishlist')


@login_required(login_url='connexion')
@require_POST
def favori_remove(request, piece_id):
    if not _require_client(request.user):
        return redirect('connexion')
    piece = get_object_or_404(Piece, pk=piece_id)
    FavoriPiece.objects.filter(utilisateur=request.user, piece=piece).delete()
    messages.success(request, f'{piece.designation} retiré des favoris.')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        favoris_count = FavoriPiece.objects.filter(utilisateur=request.user).count()
        return JsonResponse({
            'success': True,
            'piece_id': piece_id,
            'favoris_count': favoris_count,
        })

    return redirect(request.POST.get('next') or 'ecom_wishlist')


@login_required(login_url='connexion')
@require_POST
def favori_toggle(request, piece_id):
    if not _require_client(request.user):
        messages.error(request, 'Connectez-vous pour gérer vos favoris.')
        return redirect('connexion')
    piece = get_object_or_404(Piece, pk=piece_id)
    fav = FavoriPiece.objects.filter(utilisateur=request.user, piece=piece).first()
    if fav:
        fav.delete()
        messages.success(request, f'{piece.designation} retiré des favoris.')
    else:
        FavoriPiece.objects.create(utilisateur=request.user, piece=piece)
        messages.success(request, f'{piece.designation} ajouté aux favoris.')
    return redirect(request.POST.get('next') or request.META.get('HTTP_REFERER', reverse('ecom_index')))


@login_required(login_url='connexion')
def checkout(request):
    if not _require_client(request.user):
        return redirect('connexion')
    local = get_local_from_session(request)
    if not local:
        messages.warning(request, 'Sélectionnez une localité.')
        return redirect('ecom_index')
    panier = queryset_panier_online_actif(request.user, local).first()
    items = list(PanierItem.objects.filter(panier=panier).select_related('piece', 'piece__categorie', 'piece__sous_categorie')) if panier else []
    if not items:
        messages.warning(request, 'Votre panier est vide.')
        return redirect('ecom_cart')
    for item in items:
        item.stock_disponible = quantite_disponible_piece(item.piece, local)
        enrichir_piece_stock(item.piece, local)
    sous_total = total_panier_items(items, local, panier=panier)

    pays_list = list(liste_pays_actifs())
    pays_defaut = next((p for p in pays_list if p.code == 'CI'), pays_list[0] if pays_list else None)
    villes_list = list(liste_villes_actives(pays_defaut.pk if pays_defaut else None))
    session_ville = (request.session.get('ecom_livraison_ville') or '').strip()
    ville_defaut = None
    if session_ville.isdigit():
        ville_defaut = next((v for v in villes_list if str(v.pk) == session_ville), None)
    if ville_defaut is None:
        ville_defaut = next((v for v in villes_list if v.nom.lower() == 'abidjan'), villes_list[0] if villes_list else None)
    communes_list = list(liste_communes_actives(ville_defaut.pk if ville_defaut else None))
    frais = get_frais_livraison(ville_defaut, sous_total, 'livraison')

    profil = getattr(request.user, 'profil', None)
    return render(request, 'e_autopiece/checkout.html', {
        'local': local,
        'panier': panier,
        'items': items,
        'sous_total': sous_total,
        'total': sous_total + frais,
        'frais_livraison': frais,
        'free_shipping_threshold': FREE_SHIPPING_THRESHOLD,
        'moyens': MoyenPaiement.objects.filter(actif=True),
        'mode_reception_choices': Panier.MODE_RECEPTION_CHOICES,
        'pays_list': pays_list,
        'pays_defaut': pays_defaut,
        'villes_list': villes_list,
        'ville_defaut': ville_defaut,
        'communes_list': communes_list,
        'commune_defaut_id': (request.session.get('ecom_livraison_commune') or '').strip(),
        'telephone_defaut': request.user.contact or '',
        'adresse_defaut': getattr(profil, 'adresse', '') or '',
        'client_email': request.user.email,
        'client_nom': request.user.get_full_name() or request.user.username,
    })


@require_GET
def ajax_villes_livraison(request):
    pays_id = request.GET.get('pays_id')
    villes = liste_villes_actives(pays_id)
    return JsonResponse({
        'results': [
            {
                'id': v.pk,
                'nom': v.nom,
                'frais': float(v.frais_livraison or 0),
            }
            for v in villes
        ],
    })


@require_GET
def ajax_communes_livraison(request):
    ville_id = request.GET.get('ville_id')
    communes = liste_communes_actives(ville_id)
    return JsonResponse({
        'results': [{'id': c.pk, 'nom': c.nom} for c in communes],
    })


@require_POST
def ajax_set_livraison_zone(request):
    request.session['ecom_livraison_ville'] = (request.POST.get('ville_id') or '').strip()
    request.session['ecom_livraison_commune'] = (request.POST.get('commune_id') or '').strip()
    return JsonResponse({'ok': True})


@login_required(login_url='connexion')
@require_GET
def ajax_frais_livraison(request):
    ville_id = request.GET.get('ville_id')
    sous_total = Decimal(request.GET.get('sous_total') or '0')
    mode = request.GET.get('mode_reception') or 'livraison'
    ville = VilleLivraison.objects.filter(pk=ville_id, actif=True).select_related('pays').first()
    return JsonResponse(frais_livraison_payload(ville, sous_total, mode))


@login_required(login_url='connexion')
@require_POST
def confirm_order(request):
    if not _require_client(request.user):
        return redirect('connexion')
    local = get_local_from_session(request)
    if not local:
        return redirect('ecom_index')
    if request.POST.get('accepte_cgv') != '1':
        messages.error(request, 'Veuillez accepter les conditions générales.')
        return redirect('ecom_checkout')

    mode_reception = request.POST.get('mode_reception', 'livraison')
    pays = None
    ville = None
    commune = None

    def _pk_or_none(raw):
        value = (raw or '').strip()
        return int(value) if value.isdigit() else None

    if mode_reception == 'livraison':
        pays_id = _pk_or_none(request.POST.get('livraison_pays'))
        ville_id = _pk_or_none(request.POST.get('livraison_ville'))
        commune_id = _pk_or_none(request.POST.get('livraison_commune'))

        if not pays_id:
            messages.error(request, 'Veuillez sélectionner un pays de livraison.')
            return redirect('ecom_checkout')
        if not ville_id:
            messages.error(request, 'Veuillez sélectionner une ville de livraison.')
            return redirect('ecom_checkout')
        if not commune_id:
            messages.error(request, 'Veuillez sélectionner une commune.')
            return redirect('ecom_checkout')

        pays = PaysLivraison.objects.filter(pk=pays_id, actif=True).first()
        ville = VilleLivraison.objects.filter(
            pk=ville_id, actif=True,
        ).select_related('pays').first()
        commune = CommuneLivraison.objects.filter(
            pk=commune_id, actif=True,
        ).select_related('ville').first()

        if not pays:
            messages.error(request, 'Pays de livraison invalide. Veuillez en choisir un autre.')
            return redirect('ecom_checkout')
        if not ville:
            messages.error(request, 'Ville de livraison invalide. Veuillez en choisir une autre.')
            return redirect('ecom_checkout')
        if not commune:
            messages.error(request, 'Commune invalide. Veuillez en choisir une autre.')
            return redirect('ecom_checkout')

        if not (request.POST.get('adresse_domicile') or '').strip():
            messages.error(request, 'Veuillez préciser votre adresse de domicile.')
            return redirect('ecom_checkout')
        if not (request.POST.get('telephone_livraison') or '').strip() and not (request.user.contact or '').strip():
            messages.error(request, 'Veuillez indiquer un téléphone de livraison.')
            return redirect('ecom_checkout')

    try:
        moyen_code = (request.POST.get('moyen_paiement') or 'espece').strip().lower()
        if moyen_code not in ('espece', 'geniuspay'):
            moyen_code = 'espece'
        commande, ticket = valider_commande_online(
            request.user,
            local,
            mode_reception=mode_reception,
            pays=pays,
            ville=ville,
            commune=commune,
            adresse_domicile=request.POST.get('adresse_domicile', ''),
            telephone_livraison=request.POST.get('telephone_livraison', ''),
            instruction_livraison=request.POST.get('instruction_livraison', ''),
            moyen_paiement=moyen_code,
        )
        if moyen_code == 'geniuspay':
            from django.conf import settings as dj_settings
            from stock.geniuspay import GeniusPayError, montant_xof
            from stock.paiement_service import initier_paiement_commande
            min_amount = int(getattr(dj_settings, 'GENIUSPAY_MIN_AMOUNT', 200) or 200)
            if montant_xof(commande.total) < min_amount:
                from ecom.services import get_moyen_espece
                commande.moyen_paiement = get_moyen_espece()
                commande.save(update_fields=['moyen_paiement'])
                messages.warning(
                    request,
                    f'Commande enregistrée. Le paiement en ligne est disponible à partir de {min_amount} FCFA : '
                    'le règlement se fera en espèces à la livraison ou au retrait.',
                )
                return redirect('ecom_checkout')
            try:
                gp = initier_paiement_commande(
                    commande,
                    source='ecom',
                    request=request,
                )
            except GeniusPayError as exc:
                messages.error(
                    request,
                    f'La commande est enregistrée, mais GeniusPay n’a pas démarré : {exc}',
                )
                return redirect('ecom_checkout_pay', commande_id=commande.pk)
            if not gp.checkout_url:
                messages.error(request, 'URL de paiement GeniusPay manquante. Réessayez depuis cette page.')
                return redirect('ecom_checkout_pay', commande_id=commande.pk)
            return redirect(gp.checkout_url)
        messages.success(
            request,
            f'Commande {commande.numero_commande} enregistrée. Ticket {ticket.numero}.',
        )
        return redirect('ecom_mes_commandes')
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('ecom_checkout')


def checkout_pay(request, commande_id):
    """Paiement GeniusPay intégré à la page commande (pas depuis Mes commandes)."""
    from stock.geniuspay import GeniusPayError
    from stock.models import GeniusPayPaiement, PanierItem
    from stock.paiement_service import synchroniser_paiement
    from ecom.services import get_moyen_geniuspay

    if not _require_client(request.user):
        return redirect('connexion')
    commande = get_object_or_404(
        Commande,
        pk=commande_id,
        commande_en_ligne=True,
        panier__utilisateur=request.user,
    )
    retour = (request.GET.get('retour') or '').strip().lower()
    gp = (
        GeniusPayPaiement.objects.filter(commande=commande)
        .order_by('-date_creation')
        .first()
    )
    if retour == 'ok' and gp:
        try:
            gp, _confirmed = synchroniser_paiement(gp, request=request)
            commande.refresh_from_db()
        except GeniusPayError as exc:
            messages.error(request, str(exc))
    elif retour == 'erreur' and gp and gp.statut in ('pending', 'processing'):
        gp.statut = 'failed'
        gp.save(update_fields=['statut'])
        messages.error(request, 'Le paiement a été annulé ou a échoué. Vous pouvez réessayer ci-dessous.')

    if commande.paye:
        return render(request, 'e_autopiece/checkout.html', {
            'geniuspay_paye': True,
            'commande_paiement': commande,
            'geniuspay_embed_url': '',
            'items': list(
                PanierItem.objects.filter(panier=commande.panier).select_related(
                    'piece', 'piece__categorie',
                )
            ),
            'sous_total': commande.total,
            'frais_livraison': 0,
            'total': commande.total,
            'local': commande.panier.local_entrepot,
            'client_email': request.user.email,
            'client_nom': request.user.get_full_name() or request.user.username,
        })

    if commande.statut_commande == 'annuler':
        messages.error(request, 'Cette commande est annulée.')
        return redirect('ecom_checkout')

    commande.moyen_paiement = get_moyen_geniuspay()
    commande.save(update_fields=['moyen_paiement'])

    embed_url = ''
    try:
        embed_url = _paiement_geniuspay_ecom(request, commande) or ''
    except GeniusPayError as exc:
        messages.error(request, str(exc))

    if embed_url:
        return redirect(embed_url)

    items = list(
        PanierItem.objects.filter(panier=commande.panier).select_related(
            'piece', 'piece__categorie',
        )
    )
    return render(request, 'e_autopiece/checkout.html', {
        'geniuspay_embed_url': embed_url,
        'commande_paiement': commande,
        'geniuspay_paye': False,
        'items': items,
        'sous_total': commande.total,
        'frais_livraison': 0,
        'total': commande.total,
        'local': commande.panier.local_entrepot,
        'client_email': request.user.email,
        'client_nom': request.user.get_full_name() or request.user.username,
    })


def _paiement_geniuspay_ecom(request, commande):
    from stock.geniuspay import GeniusPayError
    from stock.models import GeniusPayPaiement
    from stock.paiement_service import initier_paiement_commande, synchroniser_paiement

    gp = (
        GeniusPayPaiement.objects.filter(commande=commande)
        .order_by('-date_creation')
        .first()
    )
    if gp and gp.statut in ('pending', 'processing') and gp.checkout_url:
        try:
            gp, confirmed = synchroniser_paiement(gp, request=request)
            if confirmed or commande.paye:
                commande.refresh_from_db()
                return None
            if gp.checkout_url:
                return gp.checkout_url
        except GeniusPayError as exc:
            if getattr(exc, 'code', None) not in ('INVALID_API_KEY', 'MISSING_API_KEY'):
                if gp.checkout_url:
                    return gp.checkout_url
    gp = initier_paiement_commande(commande, source='ecom', request=request)
    return gp.checkout_url


@login_required(login_url='connexion')
def paiement_succes(request):
    from stock.geniuspay import GeniusPayError
    from stock.models import GeniusPayPaiement
    from stock.paiement_service import synchroniser_paiement

    commande_id = (request.GET.get('commande') or '').strip()
    reference = (request.GET.get('reference') or request.GET.get('ref') or '').strip()
    commande = None
    gp = None
    if reference:
        gp = GeniusPayPaiement.objects.filter(reference=reference).select_related(
            'commande', 'commande__panier',
        ).first()
        if gp:
            commande = gp.commande
    if commande is None and commande_id:
        commande = Commande.objects.filter(
            pk=commande_id,
            commande_en_ligne=True,
        ).select_related('panier').first()
        if commande and gp is None:
            gp = (
                GeniusPayPaiement.objects.filter(commande=commande)
                .order_by('-date_creation')
                .first()
            )
    if commande is None:
        messages.error(request, 'Paiement introuvable.')
        return redirect('ecom_mes_commandes')
    if commande.panier.utilisateur_id != request.user.pk and not _require_staff_cmd(request.user):
        messages.error(request, 'Accès refusé.')
        return redirect('ecom_mes_commandes')

    confirmed = commande.paye
    if gp and not confirmed:
        try:
            gp, confirmed = synchroniser_paiement(gp, request=request)
            commande.refresh_from_db()
            confirmed = commande.paye
        except GeniusPayError as exc:
            messages.error(request, str(exc))
            return redirect('ecom_paiement_echec')

    return render(request, 'e_autopiece/paiement_succes.html', {
        'commande': commande,
        'paye': commande.paye,
        'reference': gp.reference if gp else '',
    })


@login_required(login_url='connexion')
def paiement_echec(request):
    from stock.models import GeniusPayPaiement

    commande_id = (request.GET.get('commande') or '').strip()
    commande = None
    if commande_id:
        commande = Commande.objects.filter(
            pk=commande_id,
            commande_en_ligne=True,
            panier__utilisateur=request.user,
        ).first()
    if commande and not commande.paye:
        gp = (
            GeniusPayPaiement.objects.filter(commande=commande)
            .order_by('-date_creation')
            .first()
        )
        if gp and gp.statut in ('pending', 'processing'):
            gp.statut = 'failed'
            gp.save(update_fields=['statut'])
    return render(request, 'e_autopiece/paiement_echec.html', {
        'commande': commande,
    })


@login_required(login_url='connexion')
@require_POST
def relancer_paiement_en_ligne(request, commande_id):
    if not _require_client(request.user):
        return redirect('connexion')
    commande = get_object_or_404(
        Commande,
        pk=commande_id,
        commande_en_ligne=True,
        panier__utilisateur=request.user,
    )
    if commande.statut_commande == 'annuler':
        messages.error(request, 'Cette commande est annulée.')
        return redirect('ecom_checkout')
    return redirect('ecom_checkout_pay', commande_id=commande.pk)


@login_required(login_url='connexion')
def mes_commandes(request):
    if not _require_client(request.user):
        return redirect('connexion')
    commandes = (
        Commande.objects.filter(
            commande_en_ligne=True,
            panier__utilisateur=request.user,
        )
        .select_related('panier', 'panier__local_entrepot', 'livreur', 'moyen_paiement')
        .order_by('-date')
    )
    return render(request, 'e_autopiece/trackorder.html', {
        'commandes': commandes,
    })


@login_required(login_url='connexion')
@require_POST
def confirmer_reception(request, commande_id):
    commande = get_object_or_404(Commande, pk=commande_id, commande_en_ligne=True)
    try:
        confirmer_reception_client(commande, request.user)
        messages.success(request, 'Réception confirmée. Merci !')
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect('ecom_mes_commandes')


@login_required(login_url='connexion')
@require_POST
def annuler_commande(request, commande_id):
    commande = get_object_or_404(Commande, pk=commande_id, commande_en_ligne=True)
    try:
        annuler_commande_client(commande, request.user)
        messages.success(request, f'Commande {commande.numero_commande} annulée.')
    except ValueError as exc:
        messages.error(request, str(exc))
    next_url = request.POST.get('next') or request.GET.get('next') or ''
    if not next_url.startswith('/') or next_url.startswith('//'):
        next_url = f"{reverse('ecom_account')}?tab=orders"
    return redirect(next_url)


def _redirect_cmd_line(request):
    """Retour à la liste commandes en ligne en conservant le filtre si possible."""
    from urllib.parse import urlparse
    ref = request.META.get('HTTP_REFERER', '')
    if ref:
        path = urlparse(ref).path or ''
        if 'commandes-en-ligne' in path or 'commandes-ligne' in path:
            return redirect(ref)
    return redirect('cmd_line')


# ── Magasin : commandes en ligne ─────────────────────────────────────────
@login_required(login_url='connexion')
def cmd_line(request):
    if not _require_staff_cmd(request.user):
        messages.error(request, 'Accès réservé au personnel du magasin.')
        return redirect('tbord')

    user = request.user
    filt = periode_filter_context(
        request,
        user,
        reset_url_name='cmd_line',
        default='mois',
    )

    # Seul l'administrateur peut filtrer par localité
    can_choose_localite = bool(
        user.is_superuser or getattr(user, 'role', None) == 'admin'
    )
    if can_choose_localite:
        localite = filt.get('localite_active')
    else:
        localite = _staff_local(user)
        filt['localite_active'] = localite
        filt['localites'] = None
    filt['can_choose_localite'] = can_choose_localite
    filt['filtre_resume'] = build_filtre_resume(
        filt['date_debut'], filt['date_fin'], filt['periode_active'], localite,
    )

    date_debut = filt['date_debut']
    date_fin = filt['date_fin']

    qs = Commande.objects.filter(
        commande_en_ligne=True,
        date_creation__range=[date_debut, date_fin],
    ).select_related(
        'panier', 'panier__utilisateur', 'panier__local_entrepot', 'livreur',
        'panier__livraison_pays', 'panier__livraison_ville', 'panier__livraison_commune',
    ).order_by('-date')
    if localite:
        qs = qs.filter(panier__local_entrepot=localite)

    # Statistiques sur le même périmètre (période + localité)
    stats_base = qs
    nb_total = stats_base.count()
    nb_en_attente = stats_base.filter(statut_commande='en_attente').count()
    nb_validees = stats_base.filter(statut_commande='valider').count()
    nb_annulees = stats_base.filter(statut_commande='annuler').count()
    nb_livrees = stats_base.filter(statut_commande='livrer').count()
    # Assignées à un livreur, pas encore livrées ni annulées
    nb_a_livrer = stats_base.filter(
        livreur__isnull=False,
    ).exclude(statut_commande__in=['livrer', 'annuler']).count()
    payees_qs = stats_base.filter(paye=True)
    nb_payees = payees_qs.count()
    montant_paye = payees_qs.aggregate(s=Sum('total'))['s'] or Decimal('0')

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    query_params = request.GET.copy()
    query_params.pop('page', None)
    extra_query = query_params.urlencode()

    livreurs = CustomUser.objects.filter(role='livreur', is_active=True)
    if localite:
        livreurs = livreurs.filter(local_entrepot=localite)

    ctx = {
        'commandes': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'cmd_line_extra_query': extra_query,
        'livreurs': livreurs,
        'local': localite,
        'filter_modal_id': 'cmdLineFilterModal',
        'stats_cmd_line': {
            'nb_total': nb_total,
            'nb_en_attente': nb_en_attente,
            'nb_validees': nb_validees,
            'nb_a_livrer': nb_a_livrer,
            'nb_livrees': nb_livrees,
            'nb_annulees': nb_annulees,
            'nb_payees': nb_payees,
            'montant_paye': montant_paye,
        },
    }
    ctx.update(filt)
    from stock.export_service import export_urls
    ctx.update(export_urls(request, 'export_cmd_line_excel', 'export_cmd_line_pdf'))
    return render(request, 'mag/cmd_line.html', ctx)


@login_required(login_url='connexion')
@require_GET
def ajax_cmd_line_detail(request, commande_id):
    """Détails commande en ligne pour le modal magasin."""
    if not _require_staff_cmd(request.user):
        return JsonResponse({'error': 'Accès refusé.'}, status=403)
    commande = get_object_or_404(_commande_en_ligne_qs(), pk=commande_id)
    if not _staff_can_access_commande_locale(request.user, commande):
        return JsonResponse({'error': 'Accès refusé.'}, status=403)
    items, frais_livraison = _commande_en_ligne_items(commande)
    html = render_to_string(
        'mag/partials/_modal_cmd_online_invoice.html',
        {
            'commande': commande,
            'items': items,
            'frais_livraison': frais_livraison,
        },
        request=request,
    )
    return JsonResponse({
        'html': html,
        'title': f'Détails commande {commande.numero_commande}',
    })


@login_required(login_url='connexion')
@require_POST
def cmd_line_valider(request, commande_id):
    if not _require_staff_cmd(request.user):
        return redirect('tbord')
    commande = get_object_or_404(Commande, pk=commande_id, commande_en_ligne=True)
    try:
        valider_commande_magasin(commande, request.user)
        messages.success(request, f'Commande {commande.numero_commande} validée.')
    except ValueError as exc:
        messages.error(request, str(exc))
    return _redirect_cmd_line(request)


@login_required(login_url='connexion')
@require_POST
def cmd_line_assigner_livreur(request, commande_id):
    if not _require_staff_cmd(request.user):
        return redirect('tbord')
    commande = get_object_or_404(Commande, pk=commande_id, commande_en_ligne=True)
    livreur_id = request.POST.get('livreur_id')
    livreur = get_object_or_404(CustomUser, pk=livreur_id, role='livreur')
    try:
        assigner_livreur(commande, livreur)
        messages.success(request, f'Livreur {livreur.username} assigné.')
    except ValueError as exc:
        messages.error(request, str(exc))
    return _redirect_cmd_line(request)


# ── Livreur : livraison commandes en ligne ─────────────────────────────────

class LivraisonCmdOnlineView(LoginRequiredMixin, TemplateView):
    login_url = 'connexion'
    template_name = 'mag/livraison_cmd_online.html'

    def dispatch(self, request, *args, **kwargs):
        denied = _deny_client_access(request)
        if denied:
            return denied
        if not _require_magasin(request.user):
            messages.error(request, 'Accès réservé au personnel du magasin.')
            return redirect('tbord')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        filt = periode_filter_context(
            self.request,
            user,
            reset_url_name='livraison_cmd_online',
            default='semaine',
        )

        is_livreur = _require_livreur(user)
        # Seul l'administrateur peut filtrer par localité (pas les livreurs ni le staff local)
        can_choose_localite = (
            not is_livreur
            and bool(user.is_superuser or getattr(user, 'role', None) == 'admin')
        )
        if can_choose_localite:
            localite = filt.get('localite_active')
        elif is_livreur:
            localite = None  # le livreur voit toutes ses assignations, sans filtre localité UI
        else:
            localite = _staff_local(user)
            filt['localite_active'] = localite
            filt['localites'] = None
        filt['can_choose_localite'] = can_choose_localite
        filt['filtre_resume'] = build_filtre_resume(
            filt['date_debut'], filt['date_fin'], filt['periode_active'], localite,
        )

        date_debut = filt['date_debut']
        date_fin = filt['date_fin']

        qs = Commande.objects.filter(
            commande_en_ligne=True,
            date_creation__range=[date_debut, date_fin],
            livreur__isnull=False,
        ).select_related(
            'panier', 'panier__utilisateur', 'panier__local_entrepot', 'livreur',
            'panier__livraison_pays', 'panier__livraison_ville', 'panier__livraison_commune',
        ).order_by('-date')

        # livreur → ses assignations ; accueil/caissier/chefagence → LocalEntrepot ; admin → tout
        from ecom.services import filter_commandes_livraison_online_for_user
        qs = filter_commandes_livraison_online_for_user(
            user, qs, localite=localite if can_choose_localite else None,
        )

        payees_qs = qs.filter(paye=True)
        stats_livraison = {
            'nb_total': qs.count(),
            'nb_impayees': qs.filter(paye=False).exclude(statut_commande='annuler').count(),
            'nb_payees': payees_qs.count(),
            'montant_paye': payees_qs.aggregate(s=Sum('total'))['s'] or Decimal('0'),
            'nb_a_livrer': qs.filter(paye=True).exclude(
                statut_commande__in=['livrer', 'annuler'],
            ).count(),
            'nb_livrees': qs.filter(statut_commande='livrer').count(),
            'nb_annulees': qs.filter(statut_commande='annuler').count(),
            'nb_en_cours': qs.filter(
                statut_commande='valider',
            ).exclude(statut_commande='annuler').count(),
        }

        context.update(filt)
        context['filter_modal_id'] = 'livraisonCmdOnlineFilterModal'
        context['commandes'] = qs
        context['local'] = localite
        context['peut_agir_livreur'] = is_livreur
        context['stats_livraison'] = stats_livraison
        context['stats_scope_label'] = (
            'Mes livraisons' if is_livreur else 'Livraisons assignées'
        )
        from stock.export_service import export_urls
        context.update(export_urls(
            self.request,
            'export_livraison_cmd_online_excel',
            'export_livraison_cmd_online_pdf',
        ))
        return context


@login_required(login_url='connexion')
@require_GET
def ajax_livraison_cmd_detail(request, commande_id):
    """Détails livraison (mise en page facture) pour le modal livreur / magasin."""
    denied = _deny_client_access(request)
    if denied:
        return JsonResponse({'error': 'Accès refusé.'}, status=403)
    if not _require_magasin(request.user):
        return JsonResponse({'error': 'Accès refusé.'}, status=403)

    commande = get_object_or_404(
        _commande_en_ligne_qs(),
        pk=commande_id,
    )
    user = request.user
    if _require_livreur(user):
        if commande.livreur_id != user.pk:
            return JsonResponse({'error': 'Accès refusé.'}, status=403)
    else:
        if not commande.livreur_id:
            return JsonResponse({'error': 'Accès refusé.'}, status=403)
        if not _staff_can_access_commande_locale(user, commande):
            return JsonResponse({'error': 'Accès refusé.'}, status=403)

    items, frais_livraison = _commande_en_ligne_items(commande)
    html = render_to_string(
        'mag/partials/_modal_cmd_online_invoice.html',
        {
            'commande': commande,
            'items': items,
            'frais_livraison': frais_livraison,
        },
        request=request,
    )
    return JsonResponse({
        'html': html,
        'title': f'Détails livraison {commande.numero_commande}',
    })


@login_required(login_url='connexion')
@require_POST
def livraison_cmd_payer(request, commande_id):
    denied = _deny_client_access(request)
    if denied:
        return denied
    if not _require_livreur(request.user):
        return redirect('tbord')
    commande = get_object_or_404(
        Commande, pk=commande_id, commande_en_ligne=True, livreur=request.user,
    )
    try:
        payer_commande_livreur(commande, request.user)
        messages.success(request, 'Paiement enregistré. Stock mis à jour.')
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect('livraison_cmd_online')


@login_required(login_url='connexion')
@require_POST
def livraison_cmd_livrer(request, commande_id):
    denied = _deny_client_access(request)
    if denied:
        return denied
    if not _require_livreur(request.user):
        return redirect('tbord')
    commande = get_object_or_404(
        Commande, pk=commande_id, commande_en_ligne=True, livreur=request.user,
    )
    try:
        livrer_commande_livreur(commande, request.user)
        messages.success(request, 'Commande marquée comme livrée.')
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect('livraison_cmd_online')


# ── Magasin : zones de livraison ───────────────────────────────────────────

class ZonesLivraisonView(LoginRequiredMixin, TemplateView):
    login_url = 'connexion'
    template_name = 'mag/zones_livraison.html'

    def dispatch(self, request, *args, **kwargs):
        denied = _deny_client_access(request)
        if denied:
            return denied
        if not _require_staff_cmd(request.user):
            messages.error(request, 'Accès réservé au personnel du magasin.')
            return redirect('tbord')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        filt = periode_filter_context(
            self.request,
            user,
            reset_url_name='zones_livraison',
            default='semaine',
        )
        date_debut = filt['date_debut']
        date_fin = filt['date_fin']
        localite = filt['localite_active']
        tab = self.request.GET.get('tab', 'pays')
        if tab not in ('pays', 'ville', 'commune'):
            tab = 'pays'

        cmd_q = Q(
            paniers__commands__commande_en_ligne=True,
            paniers__commands__date_creation__range=[date_debut, date_fin],
        )
        if localite:
            cmd_q &= Q(paniers__local_entrepot=localite)

        pays_list = PaysLivraison.objects.annotate(
            nb_cmd_periode=Count('paniers__commands', filter=cmd_q, distinct=True),
        ).order_by('nom')
        villes_list = VilleLivraison.objects.select_related('pays').annotate(
            nb_cmd_periode=Count('paniers__commands', filter=cmd_q, distinct=True),
        ).order_by('pays__nom', 'nom')
        communes_list = CommuneLivraison.objects.select_related('ville', 'ville__pays').annotate(
            nb_cmd_periode=Count('paniers__commands', filter=cmd_q, distinct=True),
        ).order_by('ville__pays__nom', 'ville__nom', 'nom')

        context.update(filt)
        context.update({
            'filter_modal_id': 'zonesLivraisonFilterModal',
            'filter_hidden_fields': {'tab': tab},
            'pays_list': pays_list,
            'villes_list': villes_list,
            'communes_list': communes_list,
            'cmd_periode_total': sum(p.nb_cmd_periode for p in pays_list),
        })
        return context


@login_required(login_url='connexion')
@require_POST
def zones_livraison_save(request):
    denied = _deny_client_access(request)
    if denied:
        return denied
    if not _require_staff_cmd(request.user):
        return redirect('tbord')
    kind = request.POST.get('kind')
    try:
        if kind == 'pays':
            pk = request.POST.get('pk')
            nom = (request.POST.get('nom') or '').strip()
            code = (request.POST.get('code') or '').strip().upper()
            if not nom or not code:
                raise ValueError('Nom et code du pays obligatoires.')
            if pk:
                obj = get_object_or_404(PaysLivraison, pk=pk)
                obj.nom = nom
                obj.code = code
                obj.save()
                messages.success(request, f'Pays « {obj.nom} » mis à jour.')
            else:
                obj = PaysLivraison.objects.create(nom=nom, code=code, actif=True)
                messages.success(request, f'Pays « {obj.nom} » créé.')
        elif kind == 'ville':
            pk = request.POST.get('pk')
            nom = (request.POST.get('nom') or '').strip()
            pays_id = request.POST.get('pays_id')
            frais = Decimal(request.POST.get('frais_livraison') or '0')
            pays = get_object_or_404(PaysLivraison, pk=pays_id)
            if not nom:
                raise ValueError('Nom de la ville obligatoire.')
            if pk:
                obj = get_object_or_404(VilleLivraison, pk=pk)
                obj.nom = nom
                obj.pays = pays
                obj.frais_livraison = frais
                obj.save()
                messages.success(request, f'Ville « {obj.nom} » mise à jour.')
            else:
                obj = VilleLivraison.objects.create(
                    pays=pays, nom=nom, frais_livraison=frais, actif=True,
                )
                messages.success(request, f'Ville « {obj.nom} » créée.')
        elif kind == 'commune':
            pk = request.POST.get('pk')
            nom = (request.POST.get('nom') or '').strip()
            ville_id = request.POST.get('ville_id')
            ville = get_object_or_404(VilleLivraison, pk=ville_id)
            if not nom:
                raise ValueError('Nom de la commune obligatoire.')
            if pk:
                obj = get_object_or_404(CommuneLivraison, pk=pk)
                obj.nom = nom
                obj.ville = ville
                obj.save()
                messages.success(request, f'Commune « {obj.nom} » mise à jour.')
            else:
                obj = CommuneLivraison.objects.create(ville=ville, nom=nom, actif=True)
                messages.success(request, f'Commune « {obj.nom} » créée.')
        else:
            raise ValueError('Action inconnue.')
    except ValueError as exc:
        messages.error(request, str(exc))
    except Exception as exc:
        messages.error(request, f'Erreur : {exc}')
    return redirect(f"{reverse('zones_livraison')}?tab={kind or 'pays'}")


@login_required(login_url='connexion')
@require_POST
def zones_livraison_toggle(request):
    denied = _deny_client_access(request)
    if denied:
        return denied
    if not _require_staff_cmd(request.user):
        return redirect('tbord')
    kind = request.POST.get('kind')
    pk = request.POST.get('pk')
    model = {
        'pays': PaysLivraison,
        'ville': VilleLivraison,
        'commune': CommuneLivraison,
    }.get(kind)
    if not model:
        messages.error(request, 'Type inconnu.')
        return redirect('zones_livraison')
    obj = get_object_or_404(model, pk=pk)
    obj.actif = not obj.actif
    obj.save(update_fields=['actif'])
    etat = 'activé' if obj.actif else 'désactivé'
    messages.success(request, f'{obj} {etat}.')
    return redirect(f"{reverse('zones_livraison')}?tab={kind}")


@login_required(login_url='connexion')
@require_POST
def zones_livraison_delete(request):
    denied = _deny_client_access(request)
    if denied:
        return denied
    if not _require_staff_cmd(request.user):
        return redirect('tbord')
    kind = request.POST.get('kind')
    pk = request.POST.get('pk')
    model = {
        'pays': PaysLivraison,
        'ville': VilleLivraison,
        'commune': CommuneLivraison,
    }.get(kind)
    if not model:
        messages.error(request, 'Type inconnu.')
        return redirect('zones_livraison')
    obj = get_object_or_404(model, pk=pk)
    nom = str(obj)
    obj.delete()
    messages.success(request, f'{nom} supprimé.')
    return redirect(f"{reverse('zones_livraison')}?tab={kind}")
