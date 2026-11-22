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
