import re
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


BENGALI = re.compile("[\u0980-\u09ff]")
LATIN = re.compile("[A-Za-z]")


def script_language(value):
    """bn when the text is mainly Bengali script, en when mainly Latin, otherwise None.

    Author names come from Work.creators, which a translated edition shares with its source,
    so the edition's locale does not tell the language of the name.
    """
    text = ", ".join(map(str, value)) if isinstance(value, (list, tuple)) else str(value or "")
    bengali, latin = len(BENGALI.findall(text)), len(LATIN.findall(text))
    if bengali > latin:
        return "bn"
    if latin > bengali:
        return "en"
    return None


@register.simple_tag
def lang_attr(value):
    """A ` lang="…"` attribute from the script of the text itself, or nothing when unclear."""
    from django.utils.html import format_html
    language = script_language(value)
    return format_html(' lang="{}"', language) if language else ""
