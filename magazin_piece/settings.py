import os
from pathlib import Path
from datetime import timedelta
from decouple import config
#import dj_database_url
# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

SECRET_KEY = config('SECRET_KEY')

# En production le .env doit contenir DEBUG=False (valeur par defaut ici).
DEBUG = config('DEBUG', default=False, cast=bool)


def _csv(value):
    """'a, b ,c' -> ['a', 'b', 'c'] (entrees vides ignorees)."""
    return [item.strip() for item in value.split(',') if item.strip()]


# Ex. DJANGO_ALLOWED_HOSTS=autopiece.ci,www.autopiece.ci
ALLOWED_HOSTS = _csv(config('DJANGO_ALLOWED_HOSTS', default='*'))

# Ex. CSRF_TRUSTED_ORIGINS=https://autopiece.ci,https://www.autopiece.ci
CSRF_TRUSTED_ORIGINS = _csv(config('CSRF_TRUSTED_ORIGINS', default=''))

# Application definition
INSTALLED_APPS = [
    'jazzmin',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'stock',
    'Userauths',
    'simple_history',
    'api',
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'ecom',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'simple_history.middleware.HistoryRequestMiddleware',
    # Middleware pour vérifier automatiquement les permissions personnalisées
    'Userauths.middleware.CustomPermissionMiddleware',
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',  # ← ajouter
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS':
        'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
}

CORS_ALLOW_ALL_ORIGINS = True

SIMPLE_JWT = {

    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),

    'AUTH_HEADER_TYPES': ('Bearer',),

    "ROTATE_REFRESH_TOKENS": True,   # ← optionnel mais recommandé
    "BLACKLIST_AFTER_ROTATION": True, # ← nécessaire pour que blacklist() fonctionne

}

ROOT_URLCONF = 'magazin_piece.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [TEMPLATES_DIR, 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.i18n',
                'ecom.context_processors.ecom_cart',
                'Userauths.context_processors.user_permissions_menu',
                'stock.context_processors.pusher_config',
            ],
        },
    },
]

WSGI_APPLICATION = 'magazin_piece.wsgi.application'


# # Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases

# Bascule sqlite (dev) <-> postgresql (production) via DB_ENGINE dans le .env.
if config('DB_ENGINE', default='sqlite') == 'postgresql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DB_NAME'),
            'USER': config('DB_USER'),
            'PASSWORD': config('DB_PASSWORD'),
            'HOST': config('DB_HOST'),
            'PORT': config('DB_PORT', default='5432'),
            'CONN_MAX_AGE': config('DB_CONN_MAX_AGE', default=60, cast=int),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'fr'

LANGUAGES = [
    ('fr', 'Français'),
    ('en', 'English'),
]

LOCALE_PATHS = [os.path.join(BASE_DIR, 'locale')]

TIME_ZONE = 'Africa/Abidjan'
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Alertes stock in-app : 4 envois par jour (heure locale Abidjan)
STOCK_ALERT_TIMEZONE = 'Africa/Abidjan'
STOCK_ALERT_HOURS = (
    (8, 0),   # matin
    (10, 0),  # midi
    (13, 0),  # après-midi
    (15, 0),  # soir
)


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, "static")]
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
 #STATICFILES_STORAGE="whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = '/media/'
MEDIA_ROOT = config('MEDIA_ROOT', default=os.path.join(BASE_DIR, 'media'))

# WhiteNoise sert les fichiers statiques depuis le conteneur (compresses, sans
# manifeste : un asset reference mais absent ne fait pas echouer collectstatic).
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
    },
}

# --- Securite / reverse proxy -------------------------------------------------
# Caddy termine le TLS et transmet X-Forwarded-Proto : sans cela Django croit
# que la requete est en clair et casse les redirections + cookies secure.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# Mettre SECURE_COOKIES=False tant que le site est expose en HTTP simple (IP nue),
# sinon la session et le jeton CSRF ne sont jamais renvoyes par le navigateur.
_secure_cookies = config('SECURE_COOKIES', default=not DEBUG, cast=bool)
SESSION_COOKIE_SECURE = _secure_cookies
CSRF_COOKIE_SECURE = _secure_cookies
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
# Redirection HTTP -> HTTPS assuree par Caddy, pas par Django (evite les boucles).
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=0, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# --- Journalisation : tout sur stdout, recupere par `docker compose logs` ------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '[{asctime}] {levelname} {name} {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
    },
    'root': {'handlers': ['console'], 'level': config('LOG_LEVEL', default='INFO')},
    'loggers': {
        'django.request': {'handlers': ['console'], 'level': 'ERROR', 'propagate': False},
    },
}
# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'Userauths.CustomUser'

EMAIL_HOST = config('EMAIL_HOST')
EMAIL_PORT = config('EMAIL_PORT', cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER')
# Mot de passe d'application Gmail : retirer les espaces éventuels
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD').replace(' ', '')

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_TIMEOUT = config('EMAIL_TIMEOUT', default=30, cast=int)

EMAIL_USE_SSL = config('EMAIL_USE_SSL', default=False, cast=bool)
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER)
FRONTEND_URL = config('FRONTEND_URL', default='http://127.0.0.1:8000')
PUBLIC_BASE_URL = config('PUBLIC_BASE_URL', default='http://127.0.0.1:8000')

# GeniusPay (paiements numériques e-com + caisse) — clés uniquement serveur
GENIUSPAY_API_KEY = config('GENIUSPAY_API_KEY', default='').strip()
GENIUSPAY_API_SECRET = config('GENIUSPAY_API_SECRET', default='').strip()
GENIUSPAY_BASE_URL = config(
    'GENIUSPAY_BASE_URL',
    default='https://geniuspay.ci/api/v1/merchant',
).strip().rstrip('/')
GENIUSPAY_WEBHOOK_SECRET = config('GENIUSPAY_WEBHOOK_SECRET', default='').strip()
GENIUSPAY_MIN_AMOUNT = 200

# Chatbot e-com — clé IA (non utilisée pour l’instant)
CHATBOT_AI_API_KEY = config('CHATBOT_AI_API_KEY', default='').strip()

# Pusher (temps réel magasin — remplace MQTT local)
PUSHER_APP_ID = config('PUSHER_APP_ID', default='')
PUSHER_KEY = config('PUSHER_KEY', default='')
PUSHER_SECRET = config('PUSHER_SECRET', default='')
PUSHER_CLUSTER = config('PUSHER_CLUSTER', default='eu')

JAZZMIN_SETTINGS = {
    "site_title": "AUTO-PIECE",
    "site_header": "AUTO-PIECE",
    "site_brand": "AUTO-PIECE",
    "login_logo": "a.png",
    "site_logo_classes": "img-circle",
    "site_icon": "icn.png",
    "welcome_sign": "Bienvenue à P&B AUTO-PIECE",
    # Copyright on the footer
    "copyright": "AUTO-PIECE",
    "search_model": ["auth.User", "auth.Group"],
    # Field name on user model that contains avatar ImageField/URLField/Charfield or a callable that receives the user
    "user_avatar": None,
    # Links to put along the top menu
    "topmenu_links": [
        # Url that gets reversed (Permissions can be added)
        {"name": "Home",  "url": "admin:index", "permissions": ["auth.view_user"]},
        {"model": "auth.User"},
        {"app": "books"},
    ],
    #############
    # User Menu #
    #############
    "usermenu_links": [
        {"model": "auth.user"}
    ],
    # Whether to display the side menu
    "show_sidebar": True,
    # Whether to aut expand the menu
    "navigation_expanded": True,
    # Hide these apps when generating side menu e.g (auth)
    "hide_apps": ["auth.user"],
    # Hide these models when generating side menu (e.g auth.user)
    "hide_models": ["auth.user"],
    # List of apps (and/or models) to base side menu ordering off of (does not need to contain all apps/models)
    "order_with_respect_to": ["auth", "books", "books.author", "books.book"],
    # Custom links to append to app groups, keyed on app name
    "custom_links": {
        "books": [{
            "name": "Make Messages", 
            "url": "make_messages", 
            "icon": "fas fa-comments",
            "permissions": ["books.view_book"]
        }]
    },
    "icons": {
        "auth": "fas fa-users-cog",
        "auth.user": "fas fa-user",
        "auth.Group": "fas fa-users",
    },
    # Icons that are used when one is not manually specified
    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",
    "related_modal_active": False,
    # #############
    # # UI Tweaks #
    # #############
    # Relative paths to custom CSS/JS scripts (must be present in static files)
    "custom_css": None,
    "custom_js": None,
    # Whether to link font from fonts.googleapis.com (use custom_css to supply font otherwise)
    "use_google_fonts_cdn": True,
    # Whether to show the UI customizer on the sidebar
    "show_ui_builder": False,
    # ###############
    "changeform_format_overrides": {"auth.user": "collapsible", "auth.group": "vertical_tabs"},
    # Add a language dropdown into the admin
    # "language_chooser": True,
}



