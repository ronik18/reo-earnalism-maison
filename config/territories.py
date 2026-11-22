"""Pure helpers for territory configuration, importable before Django settings."""
import re

from django.core.exceptions import ImproperlyConfigured


def parse_service_territories(raw, whitelist):
    """Comma-separated trusted edge territories; defaults to India-only."""
    codes = []
    for part in (raw or 'IN').split(','):
        code = part.strip().upper()
        if not re.fullmatch('[A-Z]{2}', code):
            raise ImproperlyConfigured(f'Invalid service territory {part.strip()!r}')
        if code not in whitelist:
            raise ImproperlyConfigured(f'Service territory {code} is not in the publication whitelist')
        if code not in codes:
            codes.append(code)
    return tuple(codes)


ACCOUNT_MODES = ('open', 'adult_only')


def validate_account_modes(modes, service_territories):
    """Every active territory needs an explicit account mode."""
    for code in service_territories:
        if modes.get(code) not in ACCOUNT_MODES:
            raise ImproperlyConfigured(f'Service territory {code} needs an account mode: open or adult_only')
    return dict(modes)


def validate_territory_notices(rows, service_territories):
    """Every active territory needs a privacy section with a heading and body."""
    for code in service_territories:
        row = rows.get(code) or {}
        sections = row.get('sections') or []
        if not row.get('name') or not sections or any(not s.get('heading') or not s.get('body') for s in sections):
            raise ImproperlyConfigured(f'Service territory {code} needs a privacy notice row')
    return dict(rows)
