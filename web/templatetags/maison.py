from django import template
from web.i18n import text

register = template.Library()


@register.simple_tag(takes_context=True)
def ui(context, key):
    return text(key, context.get("ui_locale", "en"))


@register.filter
def item(value, key):
    return value.get(key, "") if isinstance(value, dict) else ""


@register.simple_tag
def asset_version(name):
    """Content version prevents a browser from retaining an older UI client."""
    import hashlib
    from pathlib import Path
    from django.conf import settings
    return hashlib.sha256((Path(settings.BASE_DIR)/'static'/name).read_bytes()).hexdigest()[:12]
