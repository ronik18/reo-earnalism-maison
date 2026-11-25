from django import template
from web.i18n import text

register = template.Library()


@register.simple_tag(takes_context=True)
def ui(context, key, **values):
    value = text(key, context.get("ui_locale", "en"))
    return value.format(**values) if values else value


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


@register.simple_tag
def island_script(name):
    """Only named build outputs become executable scripts; book bootstrap stays inert JSON."""
    import json
    from pathlib import Path
    from django.conf import settings
    from django.templatetags.static import static
    from django.utils.html import format_html
    manifest = json.loads((Path(settings.BASE_DIR) / "static/maison/dist/manifest.json").read_text())
    path = manifest.get(name)
    if not isinstance(path,str) or not path.startswith("maison/dist/") or ".." in path:
        raise ValueError("Unknown Maison interactive island")
    return format_html('<script type="module" src="{}"></script>', static(path))
