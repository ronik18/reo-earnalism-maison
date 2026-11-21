"""Local-first settings. Production requires explicit configuration, never local fallbacks."""
import json
import os
import secrets
import ssl
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
# Opt in so Neon setup never redirects parallel local tests to a cloud database.
if os.getenv('MAISON_ENV_FILE'):
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / os.environ['MAISON_ENV_FILE'], override=False)
PUBLICATION_POLICY = json.loads((BASE_DIR / 'contracts/publication-policy.json').read_text())
MAISON_PUBLICATION_TERRITORIES = tuple(PUBLICATION_POLICY['whitelist'])
if (not MAISON_PUBLICATION_TERRITORIES or len(set(MAISON_PUBLICATION_TERRITORIES)) != len(MAISON_PUBLICATION_TERRITORIES)
    or any(not isinstance(c,str) or len(c)!=2 or not c.isascii() or not c.isupper() or not c.isalpha() for c in MAISON_PUBLICATION_TERRITORIES)
    or set(MAISON_PUBLICATION_TERRITORIES) & set(PUBLICATION_POLICY['out_of_scope'] + PUBLICATION_POLICY['excluded_pending'])):
    raise ImproperlyConfigured('Publication whitelist must contain only explicit passed region codes')

ENVIRONMENT = os.getenv('MAISON_ENV', 'local')
if ENVIRONMENT not in {'local', 'test', 'production'}:
    raise ImproperlyConfigured('MAISON_ENV must be local, test or production')
LOCAL = ENVIRONMENT != 'production'
MAISON_LOCAL_FIXTURES = LOCAL
STAFF_MFA_REQUIRED = not LOCAL
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
    'accounts.apps.PasswordPurposeAdminConfig', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles', 'django.contrib.postgres',
    'allauth', 'allauth.account', 'allauth.socialaccount', 'allauth.socialaccount.providers.google',
    'django_otp', 'django_otp.plugins.otp_totp',
    'core', 'accounts', 'library', 'reader', 'billing', 'learning', 'operations', 'web',
]
MIDDLEWARE = [
    'operations.middleware.RequestContextMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'web.middleware.UnifiedJourneyMiddleware',
    'operations.middleware.OriginMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'accounts.middleware.DeviceSessionMiddleware',
    'accounts.middleware.StaffMFAMiddleware',
    'core.rate_limits.MemberRateLimitMiddleware',
    'operations.middleware.PublicCacheStartMiddleware',
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
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]
# The reviewed DB contract keeps email verification/provider subjects in allauth.
# Maison retains its existing single-use email-action capabilities and API routes.
ACCOUNT_ADAPTER = 'accounts.google.MaisonAccountAdapter'
SOCIALACCOUNT_ADAPTER = 'accounts.google.MaisonSocialAccountAdapter'
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_EMAIL_VERIFICATION = 'mandatory'
ACCOUNT_UNIQUE_EMAIL = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION = False
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = False
SOCIALACCOUNT_STORE_TOKENS = False
SOCIALACCOUNT_LOGIN_ON_GET = True  # Existing GET contract creates only a temporary OAuth challenge.
SOCIALACCOUNT_REQUESTS_TIMEOUT = 3
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

DATABASE_DIRECT_URL = os.getenv('DATABASE_DIRECT_URL') or os.getenv('DATABASE_URL_UNPOOLED', '')
if not LOCAL and not DATABASE_DIRECT_URL:
    raise ImproperlyConfigured('Production requires a direct database URL for streaming exports and migrations')
DATABASE_CONNECTION_ROLE = os.getenv('MAISON_DATABASE_ROLE', 'pooled')
if DATABASE_CONNECTION_ROLE not in {'pooled','direct'}:
    raise ImproperlyConfigured('MAISON_DATABASE_ROLE must be pooled or direct')
selected_database_url = DATABASE_DIRECT_URL if DATABASE_CONNECTION_ROLE=='direct' else os.getenv('DATABASE_URL','')
if DATABASE_CONNECTION_ROLE=='direct' and not selected_database_url:
    raise ImproperlyConfigured('Direct migrations/exports require DATABASE_URL_UNPOOLED or DATABASE_DIRECT_URL')
if selected_database_url:
    db = urlparse(selected_database_url)
    if db.scheme not in {'postgres', 'postgresql'}:
        raise ImproperlyConfigured('PostgreSQL is required')
    options = parse_qs(db.query)
    sslmode = options.get('sslmode', ['disable' if LOCAL else 'verify-full'])[0]
    if db.hostname and db.hostname.endswith('.neon.tech'):
        sslmode = 'verify-full'
    if not LOCAL and sslmode != 'verify-full':
        raise ImproperlyConfigured('Production database requires sslmode=verify-full')
    db_config = {'NAME': unquote(db.path.lstrip('/')), 'USER': unquote(db.username or ''),
                 'PASSWORD': unquote(db.password or ''), 'HOST': db.hostname or '', 'PORT': db.port or 5432}
elif LOCAL and (LOCAL_DIR / 'database.json').exists():
    db_config = json.loads((LOCAL_DIR / 'database.json').read_text())
    sslmode = 'disable'
else:
    raise ImproperlyConfigured('Configure the isolated PostgreSQL database first')
database_options = {
    'sslmode': sslmode, 'connect_timeout': 3, 'prepare_threshold': None,
}
if sslmode == 'verify-full':
    # Use the platform trust store explicitly: bundled libpq may not locate it.
    database_options['sslrootcert'] = os.getenv('DATABASE_SSL_ROOT_CERT') or ssl.get_default_verify_paths().cafile or 'system'
# PgBouncer rejects timeout startup options. Pooled sessions inherit the role's
# database-scoped defaults, provisioned over the direct endpoint.
if DATABASE_CONNECTION_ROLE == 'direct' or '-pooler.' not in db_config['HOST']:
    database_options['options'] = '-c statement_timeout=5000 -c lock_timeout=2000 -c idle_in_transaction_session_timeout=10000'
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql', **db_config,
    'CONN_MAX_AGE': 60, 'CONN_HEALTH_CHECKS': True, 'ATOMIC_REQUESTS': False,
    'DISABLE_SERVER_SIDE_CURSORS': True,
    'TEST': {'NAME': os.getenv('MAISON_TEST_DB_NAME', 'test_maison')},
    'OPTIONS': database_options,
}}

# Streaming privacy exports use a separate direct connection, never PgBouncer.
PRIVACY_EXPORT_DB_ALIAS = 'default'
if DATABASE_DIRECT_URL:
    from copy import deepcopy
    export_url = urlparse(DATABASE_DIRECT_URL)
    if export_url.scheme not in {'postgres', 'postgresql'} or '-pooler.' in (export_url.hostname or ''):
        raise ImproperlyConfigured('The maintenance database URL must use a direct PostgreSQL endpoint')
    normalized_host = lambda host: (host or '').lower().replace('-pooler.', '.')
    if (unquote(export_url.path.lstrip('/')) != db_config['NAME']
        or normalized_host(export_url.hostname) != normalized_host(db_config['HOST'])
        or (export_url.port or 5432) != int(db_config['PORT'])):
        raise ImproperlyConfigured('Pooled and direct URLs must identify the same database endpoint')
    export_sslmode = parse_qs(export_url.query).get('sslmode', ['disable' if LOCAL else 'verify-full'])[0]
    if (export_url.hostname or '').endswith('.neon.tech'):
        export_sslmode = 'verify-full'
    if not LOCAL and export_sslmode != 'verify-full':
        raise ImproperlyConfigured('Production direct database requires sslmode=verify-full')
    DATABASES['maintenance'] = deepcopy(DATABASES['default'])
    DATABASES['maintenance'].update({
        'NAME': unquote(export_url.path.lstrip('/')), 'USER': unquote(export_url.username or ''),
        'PASSWORD': unquote(export_url.password or ''), 'HOST': export_url.hostname or '',
        'PORT': export_url.port or 5432, 'CONN_MAX_AGE': 0,
        'DISABLE_SERVER_SIDE_CURSORS': False, 'TEST': {'MIRROR': 'default'},
    })
    # Retain the same TLS policy and bounded read/lock limits on direct exports.
    DATABASES['maintenance']['OPTIONS'] = dict(database_options)
    DATABASES['maintenance']['OPTIONS']['sslmode'] = export_sslmode
    DATABASES['maintenance']['OPTIONS'].pop('sslrootcert', None)
    if export_sslmode == 'verify-full':
        DATABASES['maintenance']['OPTIONS']['sslrootcert'] = os.getenv('DATABASE_SSL_ROOT_CERT') or ssl.get_default_verify_paths().cafile or 'system'
    DATABASES['maintenance']['OPTIONS']['options'] = '-c statement_timeout=5000 -c lock_timeout=2000 -c idle_in_transaction_session_timeout=10000'
    PRIVACY_EXPORT_DB_ALIAS = 'maintenance'

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
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'operations.static_storage.MaisonStaticFilesStorage'},
}
MEDIA_ROOT = LOCAL_DIR / 'private-media'
BACKUP_ROOT = LOCAL_DIR / 'backups'

def bool_setting(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    if raw.lower() not in {'true', 'false'}:
        raise ImproperlyConfigured(f'{name} must be true or false')
    return raw.lower() == 'true'

EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.filebased.EmailBackend' if LOCAL else '')
EMAIL_FILE_PATH = LOCAL_DIR / 'mail'
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '465'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_SSL = bool_setting('EMAIL_USE_SSL', True)
EMAIL_USE_TLS = bool_setting('EMAIL_USE_TLS', False)
EMAIL_TIMEOUT = float(os.getenv('EMAIL_TIMEOUT', '8'))
if not 0 < EMAIL_TIMEOUT <= 8 or EMAIL_USE_SSL and EMAIL_USE_TLS:
    raise ImproperlyConfigured('Email timeout must be<=8 seconds; choose SSL or STARTTLS, not both')
if EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend':
    if not EMAIL_HOST or (not LOCAL and (not EMAIL_HOST_USER or not EMAIL_HOST_PASSWORD)) or EMAIL_PORT not in {465, 587} or not (EMAIL_USE_SSL or EMAIL_USE_TLS):
        raise ImproperlyConfigured('SMTP requires an authenticated TLS sender on465/587')
if not LOCAL and EMAIL_BACKEND != 'django.core.mail.backends.smtp.EmailBackend':
    raise ImproperlyConfigured('Production email must use the configured SMTP transport')
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', 'http://127.0.0.1:8008' if LOCAL else '')
if not LOCAL and (urlparse(PUBLIC_BASE_URL).scheme != 'https' or not urlparse(PUBLIC_BASE_URL).hostname or urlparse(PUBLIC_BASE_URL).username):
    raise ImproperlyConfigured('A canonical HTTPS PUBLIC_BASE_URL is required')
DEFAULT_FROM_EMAIL = os.getenv('EMAIL_FROM_ADDRESS', 'maison@localhost.test' if LOCAL else '')
SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL', '')
PRIVACY_NOTICE_VERSION = 'earnalism-privacy-2026-11-20-r4'
# Preparation only. Real jurisdiction/method policies require separate legal and
# provider acceptance; an environment toggle must not invent that qualification.
GUARDIAN_AUTHORIZATION_ENABLED = False
GUARDIAN_AUTHORIZATION_POLICIES = {}
EARNALISM_PUBLIC_GRIEVANCE_OFFICER_NAME = os.getenv('EARNALISM_PUBLIC_GRIEVANCE_OFFICER_NAME', '').strip()
if not LOCAL and (not EMAIL_BACKEND or not DEFAULT_FROM_EMAIL):
    raise ImproperlyConfigured('Production email configuration is required')
ORIGIN_SHARED_SECRET = os.getenv('ORIGIN_SHARED_SECRET', '')
HEALTH_PROBE_SECRET = os.getenv('HEALTH_PROBE_SECRET', SECRET_KEY if LOCAL else '')
if not LOCAL and (len(ORIGIN_SHARED_SECRET) < 32 or len(HEALTH_PROBE_SECRET) < 32):
    raise ImproperlyConfigured('Production origin and readiness secrets are required')

MEDIA_STORAGE_BACKEND = os.getenv('MEDIA_STORAGE_BACKEND', 'local' if LOCAL else 'r2')
if MEDIA_STORAGE_BACKEND not in {'local', 'r2'} or not LOCAL and MEDIA_STORAGE_BACKEND != 'r2':
    raise ImproperlyConfigured('Production private media requires R2; local transport is development-only')
R2_ACCOUNT_ID = os.getenv('R2_ACCOUNT_ID', '')
R2_ENDPOINT_URL = os.getenv('R2_ENDPOINT_URL', f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com' if R2_ACCOUNT_ID else '')
R2_PRIVATE_BUCKET = os.getenv('R2_PRIVATE_BUCKET', '')
R2_PUBLIC_BUCKET = os.getenv('R2_PUBLIC_BUCKET', '')
R2_PUBLIC_UPLOAD_KEY_ID = os.getenv('R2_PUBLIC_UPLOAD_KEY_ID', '')
R2_PUBLIC_UPLOAD_SECRET = os.getenv('R2_PUBLIC_UPLOAD_SECRET', '')
R2_PUBLIC_ASSET_HOST = os.getenv('R2_PUBLIC_ASSET_HOST', '')
for _credential_name in ('R2_APPLICATION_KEY_ID','R2_APPLICATION_SECRET','R2_UPLOAD_KEY_ID','R2_UPLOAD_SECRET'):
    globals()[_credential_name] = os.getenv(_credential_name, '')
if MEDIA_STORAGE_BACKEND == 'r2':
    import re
    _endpoint = urlparse(R2_ENDPOINT_URL)
    if (not re.fullmatch(r'[a-f0-9]{32}', R2_ACCOUNT_ID) or _endpoint.scheme != 'https'
        or _endpoint.netloc != f'{R2_ACCOUNT_ID}.r2.cloudflarestorage.com'
        or _endpoint.path not in {'','/'} or _endpoint.query or _endpoint.fragment
        or not R2_PRIVATE_BUCKET or not all(globals()[key] for key in ('R2_APPLICATION_KEY_ID','R2_APPLICATION_SECRET','R2_UPLOAD_KEY_ID','R2_UPLOAD_SECRET'))):
        raise ImproperlyConfigured('R2 requires the exact account endpoint, private bucket and scoped read/upload credentials')
if R2_PUBLIC_ASSET_HOST:
    import re
    _public_host = urlparse(R2_PUBLIC_ASSET_HOST)
    _asset_hostname = _public_host.hostname or ''
    if (_public_host.scheme != 'https' or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', _asset_hostname)
        or _public_host.netloc != _asset_hostname or _public_host.username or _public_host.password
        or _public_host.path not in {'','/'} or _public_host.query or _public_host.fragment
        or _asset_hostname.endswith('.r2.dev') or _asset_hostname.endswith('.r2.cloudflarestorage.com')):
        raise ImproperlyConfigured('Public assets require a dedicated HTTPS CDN hostname; no private S3/r2.dev endpoint')


# Public assets use an immutable release namespace; never serve private storage.
STATIC_RELEASE_ID = os.getenv('STATIC_RELEASE_ID', '')
if STATIC_RELEASE_ID:
    import re
    if not re.fullmatch('[a-f0-9]{64}', STATIC_RELEASE_ID):
        raise ImproperlyConfigured('STATIC_RELEASE_ID must be the prepared public tree SHA256')
if not LOCAL and (not R2_PUBLIC_ASSET_HOST or not STATIC_RELEASE_ID):
    raise ImproperlyConfigured('Production requires the qualified public CDN host and static release ID')
if R2_PUBLIC_ASSET_HOST and STATIC_RELEASE_ID:
    STATIC_URL = R2_PUBLIC_ASSET_HOST.rstrip('/') + '/static/' + STATIC_RELEASE_ID + '/'

# Owner-approved free rollout; authorization still enforces publication and rights.
FREE_ACCESS_ENABLED = bool_setting('MAISON_FREE_ACCESS', False)

FEATURES = {
    'reader': True, 'email_password': True,
    **{name: bool_setting('MAISON_' + name.upper(), False) for name in [
        'audio', 'video', 'offline_text_audio', 'email_link', 'google_oauth', 'phone_otp',
        'recurring_billing', 'international_checkout', 'gift', 'family', 'minor_profiles',
        'timed_recorded_practice', 'clips', 'word_read_along', 'dictionary', 'video_trinity', 'video_download',
    ]},
}
FEATURE_FLAGS = FEATURES
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')
GOOGLE_REDIRECT_URI = PUBLIC_BASE_URL.rstrip('/') + '/api/v1/auth/google/callback'
GOOGLE_CHALLENGE_SECONDS = 600
SOCIALACCOUNT_PROVIDERS = {'google': {
    'SCOPE': ['openid', 'email', 'profile'],
    'AUTH_PARAMS': {'prompt': 'select_account'},
    'OAUTH_PKCE_ENABLED': True,
    'APP': {'client_id': GOOGLE_CLIENT_ID, 'secret': GOOGLE_CLIENT_SECRET, 'key': ''},
}}
if FEATURES['google_oauth'] and (not GOOGLE_CLIENT_ID.endswith('.apps.googleusercontent.com') or not GOOGLE_CLIENT_SECRET):
    raise ImproperlyConfigured('Google sign-in requires its registered client and exact canonical callback')
STREAM_ACCOUNT_ID = os.getenv('STREAM_ACCOUNT_ID', '')
STREAM_API_TOKEN = os.getenv('STREAM_API_TOKEN', '')
STREAM_SIGNING_KEY_ID = os.getenv('STREAM_SIGNING_KEY_ID', '')
STREAM_SIGNING_PRIVATE_KEY = os.getenv('STREAM_SIGNING_PRIVATE_KEY', '')
STREAM_CUSTOMER_HOST = os.getenv('STREAM_CUSTOMER_HOST', '')
if FEATURES['video']:
    import re
    if (not re.fullmatch(r'[a-f0-9]{32}', STREAM_ACCOUNT_ID)
            or not re.fullmatch(r'customer-[a-z0-9]+\.cloudflarestream\.com', STREAM_CUSTOMER_HOST)
            or not all([STREAM_API_TOKEN, STREAM_SIGNING_KEY_ID, STREAM_SIGNING_PRIVATE_KEY])):
        raise ImproperlyConfigured('Video requires its configured signed Stream profile and exact customer host')
if not LOCAL and (FEATURES['audio'] or FEATURES['offline_text_audio']) and MEDIA_STORAGE_BACKEND != 'r2':
    raise ImproperlyConfigured('Production audio/offline delivery requires configured private R2 storage')
# Email links use the same authenticated TLS SMTP profile validated above.
# The remaining providers still need their own qualified adapter/configuration.
if not LOCAL and any(FEATURES[n] for n in ['phone_otp', 'recurring_billing', 'international_checkout']):
    raise ImproperlyConfigured('Enabled provider features require their qualified production adapter/configuration')

SECURITY_EVENT_LOGGING = bool_setting('SECURITY_EVENT_LOGGING', not LOCAL)

LOGGING = {
    'version': 1, 'disable_existing_loggers': False,
    'filters': {'redact_query': {'()': 'operations.logging.RedactQueryFilter'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'filters': ['redact_query']},
                 'security_console': {'class': 'logging.StreamHandler', 'stream': 'ext://sys.stdout', 'filters': ['redact_query']}},
    'loggers': {'django.server': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
                'earnalism.security': {'handlers': ['security_console'], 'level': 'INFO', 'propagate': False}},
}

# Optional, zone-scoped CDN invalidation; unconfigured providers stay disabled.
CLOUDFLARE_ZONE_ID = os.getenv('CLOUDFLARE_ZONE_ID', '')
CLOUDFLARE_CACHE_PURGE_TOKEN = os.getenv('CLOUDFLARE_CACHE_PURGE_TOKEN', '')

RAZORPAY_ENABLED = bool_setting('RAZORPAY_ENABLED', False)
RAZORPAY_MODE = os.getenv('RAZORPAY_MODE', 'test')
RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET', '')
RAZORPAY_WEBHOOK_SECRETS = tuple(v for v in [os.getenv('RAZORPAY_WEBHOOK_SECRET',''),os.getenv('RAZORPAY_PREVIOUS_WEBHOOK_SECRET','')] if v)
MERCHANT_ENTITY_CONFIG_VERSION = os.getenv('MERCHANT_ENTITY_CONFIG_VERSION', '')
RAZORPAY_LIVE_APPROVED = bool_setting('RAZORPAY_LIVE_APPROVED', False)
# No finance terms are inferred from the merchant credential or entity name.
try:
    MERCHANT_FINANCE_POLICY = json.loads(os.getenv('MERCHANT_FINANCE_POLICY', '{}'))
except (TypeError, ValueError) as exc:
    raise ImproperlyConfigured('Merchant finance policy must be a JSON object') from exc
if not isinstance(MERCHANT_FINANCE_POLICY, dict):
    raise ImproperlyConfigured('Merchant finance policy must be a JSON object')
if RAZORPAY_MODE not in {'test','live'}:
    raise ImproperlyConfigured('Razorpay mode must be test/live')
if RAZORPAY_ENABLED:
    if not RAZORPAY_KEY_ID.startswith('rzp_'+RAZORPAY_MODE+'_') or not RAZORPAY_KEY_SECRET or not RAZORPAY_WEBHOOK_SECRETS or not MERCHANT_ENTITY_CONFIG_VERSION:
        raise ImproperlyConfigured('Enabled Razorpay requires matching keys, webhook secret and merchant configuration')
    if RAZORPAY_MODE=='live' and not RAZORPAY_LIVE_APPROVED:
        raise ImproperlyConfigured('Live Razorpay requires explicit merchant qualification and approval')
