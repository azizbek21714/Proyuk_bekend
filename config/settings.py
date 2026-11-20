import environ
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
    ALLOWED_HOSTS=(list, ['localhost', '127.0.0.1']),
    CORS_ALLOWED_ORIGINS=(list, ['http://localhost:3000']),
    CSRF_TRUSTED_ORIGINS=(list, []),
)

environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env('SECRET_KEY', default='django-insecure-change-me-in-production')

DEBUG = env('DEBUG')

# Saqlash joyi: firestore | jsonfile (lokal fayl) | memory (testlar)
STORE_BACKEND = env('STORE_BACKEND', default='jsonfile' if DEBUG else 'firestore')

if not DEBUG:
    if SECRET_KEY == 'django-insecure-change-me-in-production':
        raise ImproperlyConfigured('Production uchun SECRET_KEY majburiy.')
    if STORE_BACKEND == 'firestore' and not os.environ.get('FIREBASE_CREDENTIALS'):
        raise ImproperlyConfigured('Production uchun FIREBASE_CREDENTIALS majburiy.')

def _clean_list(values):
    """Bo'sh qoldirilgan muhit o'zgaruvchisi [''] bo'lib kelmasin."""
    return [v.strip() for v in values if v and v.strip()]


ALLOWED_HOSTS = _clean_list(env('ALLOWED_HOSTS'))
# Render'da xizmatning o'z manzili avtomatik ruxsat etiladi
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# HTTPS orqali formalar uchun (masalan https://proyuk.onrender.com)
CSRF_TRUSTED_ORIGINS = _clean_list(env('CSRF_TRUSTED_ORIGINS'))
if RENDER_EXTERNAL_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(f'https://{RENDER_EXTERNAL_HOSTNAME}')

INSTALLED_APPS = [
    # auth: faqat parol xeshlash/validatsiya va AnonymousUser uchun (bazasiz)
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.staticfiles',

    # Third-party
    'rest_framework',
    'corsheaders',

    # Local apps
    'apps.core',
    'apps.accounts',
    'apps.teachers',
    'apps.departments',
    'apps.academics',
    'apps.workload',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Statik fayllarni (Django admin) gunicorn orqali beradi
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'apps.core.middleware.StoreRequestCacheMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Ma'lumotlar Firestore'da (yoki lokal JSON faylda) — SQL baza ishlatilmaydi
DATABASES = {}

STORE_JSON_PATH = env('STORE_JSON_PATH', default=str(BASE_DIR / '.localstore.json'))
FIREBASE_PROJECT_ID = env('FIREBASE_PROJECT_ID', default='')
FIRESTORE_DATABASE = env('FIRESTORE_DATABASE', default='(default)')

# Ish dalillari (fayllar): supabase (production), local (dev, .local_files/), memory (testlar)
FILE_STORAGE = env('FILE_STORAGE', default='local' if DEBUG else 'supabase')
SUPABASE_URL = env('SUPABASE_URL', default='')
SUPABASE_SERVICE_ROLE_KEY = env('SUPABASE_SERVICE_ROLE_KEY', default='')
SUPABASE_BUCKET = env('SUPABASE_BUCKET', default='ish-dalillari')
# Sessiya ishlatilmaydi (JWT); test klienti uchun bazasiz dvigatel
SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'
        if not DEBUG else 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'apps.accounts.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'config.permissions.RolePermission',
    ),
    'DEFAULT_PAGINATION_CLASS': 'config.pagination.OptionalPageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'authentication': '20/hour',
    },
}

# JWT: apps/accounts/tokens.py (access 1 soat, refresh 30 kun, rotatsiya + blacklist)

# CORS
CORS_ALLOWED_ORIGINS = _clean_list(env('CORS_ALLOWED_ORIGINS'))
CORS_ALLOW_CREDENTIALS = True

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    # Render health check ichki tarmoqdan oddiy HTTP orqali keladi
    SECURE_REDIRECT_EXEMPT = [r'^api/health$']
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    CSRF_COOKIE_SECURE = True

# Logging — lokal app loglari (Excel o'qish va h.k.) konsolga chiqsin
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '[{asctime}] {levelname} {name}: {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
    },
    'loggers': {
        'apps': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}
