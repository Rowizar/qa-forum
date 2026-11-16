"""
Django settings for the QA forum project.

Everything environment-specific (secrets, debug mode, hosts, Redis, e-mail)
is read from environment variables or from a local `.env` file.
See `.env.example` for the full list.
"""
import sys
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / '.env')

# --- Security ---------------------------------------------------------------

# Required: the app refuses to start without it.
SECRET_KEY = env('SECRET_KEY')

DEBUG = env.bool('DEBUG', default=False)

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

# Origins (scheme + host) allowed to send forms, e.g. https://forum.example.com.
# Needed when the site is served over HTTPS behind a proxy.
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])

# HTTPS-only mode. On by default whenever DEBUG is off, so a production
# deployment is safe without extra settings. Set HTTPS_ONLY=False only to try
# DEBUG=False locally over plain HTTP. Tests always use plain HTTP.
TESTING = len(sys.argv) > 1 and sys.argv[1] == 'test'
HTTPS_ONLY = env.bool('HTTPS_ONLY', default=not DEBUG) and not TESTING

if HTTPS_ONLY:
    SECURE_SSL_REDIRECT = True      # http:// requests are redirected to https://
    SESSION_COOKIE_SECURE = True    # login cookie is sent over HTTPS only
    CSRF_COOKIE_SECURE = True
    # Browsers remember to use HTTPS for this long. One hour to start with;
    # raise to 31536000 (a year) once HTTPS is known to work.
    SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=3600)

# Set to True when a reverse proxy (nginx, a hosting platform) terminates HTTPS
# and passes the X-Forwarded-Proto header. Without it Django cannot tell that
# the original request was secure and redirects forever. Never enable it when
# the app is reachable directly: the header could then be forged.
if env.bool('BEHIND_HTTPS_PROXY', default=False):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# --- Applications -----------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'qa_app.apps.QaAppConfig',
    'rest_framework',
    'simple_history',
    'django_celery_beat',
    'drf_yasg',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    # Picks the interface language: the visitor's own choice (a cookie set by
    # the RU/EN switch) or, without one, the language of their browser.
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'qa_app.middleware.LogVisitMiddleware',
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
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'qa_app.context_processors.categories',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# --- Database ---------------------------------------------------------------

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- Auth -------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'feed'
LOGOUT_REDIRECT_URL = 'feed'

# --- Internationalization ---------------------------------------------------

# English is the language the texts are written in and the fallback for
# browsers that ask for anything else. Russian lives in locale/ru/.
LANGUAGE_CODE = 'en'
LANGUAGES = [
    ('en', 'English'),
    ('ru', 'Русский'),
]
LOCALE_PATHS = [BASE_DIR / 'locale']

TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# --- Static and media files -------------------------------------------------

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# --- REST framework ---------------------------------------------------------

REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
}

# --- Redis, cache, Celery ---------------------------------------------------

# Base Redis URL without a database number, e.g. redis://localhost:6379.
# Leave it empty to run without Redis: the cache lives in memory, Celery tasks
# run synchronously, and page visits are written straight to the database.
REDIS_URL = env('REDIS_URL', default='').rstrip('/')

if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': f'{REDIS_URL}/1',
            'OPTIONS': {'CLIENT_CLASS': 'django_redis.client.DefaultClient'},
        }
    }
    CELERY_BROKER_URL = f'{REDIS_URL}/0'
    CELERY_RESULT_BACKEND = f'{REDIS_URL}/0'
else:
    CACHES = {
        'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}
    }
    CELERY_BROKER_URL = 'memory://'
    CELERY_RESULT_BACKEND = 'cache+memory://'
    CELERY_TASK_ALWAYS_EAGER = True

CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'

# --- E-mail -----------------------------------------------------------------

# Console backend by default: e-mails are printed to the terminal.
EMAIL_BACKEND = env(
    'EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend'
)
EMAIL_HOST = env('EMAIL_HOST', default='localhost')
EMAIL_PORT = env.int('EMAIL_PORT', default=25)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=False)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='noreply@localhost')

# --- Logging ----------------------------------------------------------------

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'qa_app': {
            'handlers': ['console'],
            'level': env('LOG_LEVEL', default='INFO'),
        },
    },
}
