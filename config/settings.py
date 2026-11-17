"""Local-first settings. Production requires explicit configuration, never local fallbacks."""
import json
import os
import secrets
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
ENVIRONMENT = os.getenv('MAISON_ENV', 'local')
if ENVIRONMENT not in {'local', 'test', 'production'}:
    raise ImproperlyConfigured('MAISON_ENV must be local, test or production')
LOCAL = ENVIRONMENT != 'production'
MAISON_LOCAL_FIXTURES = LOCAL
DEBUG = LOCAL
LOCAL_DIR = BASE_DIR / '.local'
if LOCAL:
    LOCAL_DIR.mkdir(exist_ok=True)
    secret_path = LOCAL_DIR / 'django.secret'
    if not secret_path.exists():
        secret_path.write_text(secrets.token_urlsafe(64))
        secret_path.chmod(0o600)
    SECRET_KEY = secret_path.read_text().strip()
else:
    SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
    if len(SECRET_KEY) < 40:
        raise ImproperlyConfigured('A production DJANGO_SECRET_KEY is required')

ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver'] if LOCAL else [h.strip() for h in os.getenv('ALLOWED_HOSTS', '').split(',') if h.strip()]
if not ALLOWED_HOSTS or '*' in ALLOWED_HOSTS:
    raise ImproperlyConfigured('Explicit allowed hosts are required')
CSRF_TRUSTED_ORIGINS = [v for v in os.getenv('CSRF_TRUSTED_ORIGINS', 'http://localhost:8008,http://127.0.0.1:8008' if LOCAL else '').split(',') if v]
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'core', 'accounts', 'library', 'reader', 'billing', 'learning', 'operations', 'web',
]
MIDDLEWARE = [
    'operations.middleware.RequestContextMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'operations.middleware.OriginMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'accounts.middleware.DeviceSessionMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request', 'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
AUTH_USER_MODEL = 'accounts.User'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LOGIN_URL = '/sign-in/'
LOGIN_REDIRECT_URL = '/vault/'
LOGOUT_REDIRECT_URL = '/'
LANGUAGE_CODE = 'en'
LANGUAGES = [('en', 'English'), ('bn', 'বাংলা')]
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

if os.getenv('DATABASE_URL'):
    db = urlparse(os.environ['DATABASE_URL'])
    if db.scheme not in {'postgres', 'postgresql'}:
        raise ImproperlyConfigured('PostgreSQL is required')
    options = parse_qs(db.query)
    sslmode = options.get('sslmode', ['disable' if LOCAL else 'verify-full'])[0]
    if not LOCAL and sslmode != 'verify-full':
        raise ImproperlyConfigured('Production database requires sslmode=verify-full')
    db_config = {'NAME': unquote(db.path.lstrip('/')), 'USER': unquote(db.username or ''),
                 'PASSWORD': unquote(db.password or ''), 'HOST': db.hostname or '', 'PORT': db.port or 5432}
elif LOCAL and (LOCAL_DIR / 'database.json').exists():
    db_config = json.loads((LOCAL_DIR / 'database.json').read_text())
    sslmode = 'disable'
else:
    raise ImproperlyConfigured('Configure the isolated PostgreSQL database first')
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql', **db_config,
    'CONN_MAX_AGE': 60, 'CONN_HEALTH_CHECKS': True, 'ATOMIC_REQUESTS': False,
    'DISABLE_SERVER_SIDE_CURSORS': True,
    'TEST': {'NAME': os.getenv('MAISON_TEST_DB_NAME', 'test_maison')},
    'OPTIONS': {'sslmode': sslmode, 'connect_timeout': 3, 'prepare_threshold': None,
                'options': '-c statement_timeout=5000 -c lock_timeout=2000 -c idle_in_transaction_session_timeout=10000'},
}}

SESSION_COOKIE_NAME = 'maison_local_session' if LOCAL else '__Host-earnalism_session'
CSRF_COOKIE_NAME = 'maison_local_csrf' if LOCAL else '__Host-earnalism_csrf'
DEVICE_COOKIE_NAME = 'maison_local_device' if LOCAL else '__Host-earnalism_device'
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = not LOCAL
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 1209600
SESSION_COOKIE_DOMAIN = CSRF_COOKIE_DOMAIN = None
SECURE_SSL_REDIRECT = not LOCAL
SECURE_HSTS_SECONDS = 0 if LOCAL else 31536000
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
CSRF_FAILURE_VIEW = 'operations.views.csrf_failure'
DATA_UPLOAD_MAX_MEMORY_SIZE = 1048576
FILE_UPLOAD_MAX_MEMORY_SIZE = 262144
JSON_BODY_MAX_BYTES = 262144
WEBHOOK_BODY_MAX_BYTES = 1048576
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = LOCAL_DIR / 'static'
MEDIA_ROOT = LOCAL_DIR / 'private-media'
BACKUP_ROOT = LOCAL_DIR / 'backups'

EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend' if LOCAL else os.getenv('EMAIL_BACKEND', '')
EMAIL_FILE_PATH = LOCAL_DIR / 'mail'
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', 'http://127.0.0.1:8008' if LOCAL else '')
if not LOCAL and (urlparse(PUBLIC_BASE_URL).scheme != 'https' or not urlparse(PUBLIC_BASE_URL).hostname or urlparse(PUBLIC_BASE_URL).username):
    raise ImproperlyConfigured('A canonical HTTPS PUBLIC_BASE_URL is required')
DEFAULT_FROM_EMAIL = os.getenv('EMAIL_FROM_ADDRESS', 'maison@localhost.test' if LOCAL else '')
if not LOCAL and (not EMAIL_BACKEND or not DEFAULT_FROM_EMAIL):
    raise ImproperlyConfigured('Production email configuration is required')
ORIGIN_SHARED_SECRET = os.getenv('ORIGIN_SHARED_SECRET', '')
HEALTH_PROBE_SECRET = os.getenv('HEALTH_PROBE_SECRET', SECRET_KEY if LOCAL else '')
if not LOCAL and (len(ORIGIN_SHARED_SECRET) < 32 or len(HEALTH_PROBE_SECRET) < 32):
    raise ImproperlyConfigured('Production origin and readiness secrets are required')

def bool_setting(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    if raw.lower() not in {'true', 'false'}:
        raise ImproperlyConfigured(f'{name} must be true or false')
    return raw.lower() == 'true'

FEATURES = {
    'reader': True, 'email_password': True,
    **{name: bool_setting('MAISON_' + name.upper(), False) for name in [
        'audio', 'video', 'offline_text_audio', 'email_link', 'google_oauth', 'phone_otp',
        'recurring_billing', 'international_checkout', 'gift', 'family', 'minor_profiles',
        'timed_recorded_practice', 'clips', 'word_read_along', 'dictionary', 'video_trinity', 'video_download',
    ]},
}
FEATURE_FLAGS = FEATURES
if not LOCAL and (FEATURES['audio'] or FEATURES['video'] or FEATURES['offline_text_audio']):
    raise ImproperlyConfigured('Provider-backed media requires a separately qualified production settings profile')
if not LOCAL and any(FEATURES[n] for n in ['google_oauth', 'email_link', 'phone_otp', 'recurring_billing', 'international_checkout']):
    raise ImproperlyConfigured('Enabled provider features require their qualified production adapter/configuration')

LOGGING = {
    'version': 1, 'disable_existing_loggers': False,
    'filters': {'redact_query': {'()': 'operations.logging.RedactQueryFilter'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'filters': ['redact_query']}},
    'loggers': {'django.server': {'handlers': ['console'], 'level': 'INFO', 'propagate': False}},
}
