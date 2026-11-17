from django import template
from web.i18n import text

register = template.Library()


@register.simple_tag(takes_context=True)
def ui(context, key):
    return text(key, context.get("ui_locale", "en"))


@register.filter
def item(value, key):
    return value.get(key, "") if isinstance(value, dict) else ""
