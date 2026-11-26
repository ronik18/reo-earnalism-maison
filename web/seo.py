"""Per-page title, description and sharing tags, plus /sitemap.xml, /robots.txt and /favicon.ico.

Every absolute URL starts from settings.PUBLIC_BASE_URL (https://theearnalism.com in production).
Sharing tags are left off private pages: staff review, account pages, token links and draft editions.
"""
import xml.etree.ElementTree as ET

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_safe

SITE_NAME = "Earnalism"
SITE_DESCRIPTION = "Read Bengali and English classics, listen as they are told aloud, and learn through short video series on Earnalism."
OG_LOCALES = {"en": "en_US", "bn": "bn_IN"}
# The interface is English; /bn/ paths redirect to /en/ (web.middleware), so English is the one served locale.
SERVED_LOCALES = ("en",)

# Pages with no sharing tags: signed-in, staff and token pages.
PRIVATE_ROUTES = {
    "vault", "personal-list", "downloads", "settings", "checkout", "staff-review", "staff-review-cover",
    "certificate-issue", "certificate-withdraw", "classroom", "password-reset-confirm", "verify-email",
    "welcome", "independent-account", "sign-out", "certificate", "verify-landing", "reset-landing", "email-link-landing",
}

# url name -> (page title, description). Title pages, readers, series and collections are built from data below.
PAGES = {
    "explore": ("Explore the library", "Browse every Bengali and English edition on Earnalism: classic stories to read, hear and learn from."),
    "search": ("Search", "Search Earnalism editions by title, author, topic or format."),
    "learn": ("Learn", "Short Earnalism learning tracks with lessons, notes and quick checks, one idea at a time."),
    "interview": ("Interview practice", "Practise software engineering interview questions on Earnalism, one track at a time."),
    "series": ("Series", "Follow an Earnalism series episode by episode, at your own pace."),
    "pass": ("Reading pass", "What an Earnalism reading pass includes and how free access works."),
    "privacy": ("Privacy notice", "How Earnalism collects, uses and protects your information."),
    "terms": ("Terms of service", "The terms for using Earnalism and the editions in its library."),
    "contact": ("Contact", "How to reach the Earnalism team for help, rights questions or feedback."),
    "sign-in": ("Sign in", "Sign in to Earnalism to keep your place, highlights and notes on every device."),
    "sign-up": ("Create your free account", "Create a free Earnalism account to keep your place, save highlights and read on any device."),
    "email-link": ("Email sign-in link", "Get a one-time sign-in link for your Earnalism account by email."),
    "password-reset": ("Reset your password", "Reset the password for your Earnalism account."),
    "guardian-guidance": ("Children and guardian permissions", "How a parent or guardian can set up and look after a young reader's Earnalism account."),
    "offline-shell": ("Offline", "This Earnalism page needs a connection; your downloaded editions stay available."),
}


def absolute(url):
    """An absolute URL on the public origin; URLs already on another origin (static CDN, covers) stay as they are."""
    if not url:
        return ""
    if url.startswith(("https://", "http://")):
        return url
    return (settings.PUBLIC_BASE_URL or "").rstrip("/") + url


def _shorten(text, limit=300):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rsplit(" ", 1)[0] + "…"


def _public_cover(edition):
    """The published front cover only; staff draft covers never go into sharing tags."""
    cover = edition.get("cover") if isinstance(edition, dict) else None
    if not cover or not edition.get("published_at") or "/api/v1/staff/" in cover.get("url", ""):
        return None
    return cover


def page_meta(request, ctx, template=""):
    """Title, description, canonical and Open Graph values for base.html."""
    match = getattr(request, "resolver_match", None)
    route = match.url_name if match else None
    if route == "search" and request.path.endswith("/explore/"):
        route = "explore"
    edition = ctx.get("edition") if isinstance(ctx.get("edition"), dict) and ctx["edition"].get("title") else None
    status_page = template == "web/status.html"
    title, description = PAGES.get(route, (None, None))
    og_type, locale, cover = "website", "en", None
    if status_page:
        from .i18n import text
        title, description = text(ctx.get("error_key") or "error", "en").split(".")[0], None
    elif route == "title" and edition:
        title, description, og_type = edition["title"], edition.get("description") or f"{edition['title']}, an edition on Earnalism.", "book"
    elif route in ("reader", "reader-start", "classroom") and edition:
        unit_title = ((ctx.get("document") or {}).get("unit") or {}).get("title") or ""
        title = f"{unit_title} · {edition['title']}" if unit_title and unit_title != edition["title"] else f"Read {edition['title']}"
        description = f"Read {unit_title or edition['title']} from {edition['title']} on Earnalism."
    elif route in ("player", "player-unit", "audio-preview", "video") and edition:
        verb = "Watch" if route == "video" else "Listen to"
        title, description = f"{verb} {edition['title']}", f"{verb} {edition['title']} on Earnalism."
    elif route in ("series-detail", "collection") and isinstance(ctx.get("collection"), dict):
        title = ctx["collection"].get("title") or "Collection"
        description = ctx["collection"].get("description") or f"{title} on Earnalism."
    elif route in ("track", "lesson", "question"):
        item = ctx.get("lesson" if route == "lesson" else "track")
        name = item.get("title") if isinstance(item, dict) else None
        title = (f"Question · {name}" if route == "question" else name) if name else "Learn"
        description = (item.get("description") if isinstance(item, dict) else None) or f"{title} on Earnalism."
    elif ctx.get("legal_title"):
        title = ctx["legal_title"]
    if edition and not status_page:
        locale, cover = edition.get("locale") or "en", _public_cover(edition)
    full_title = "Earnalism · Read, listen and learn" if route == "home" and not status_page else (f"{title} · {SITE_NAME}" if title else SITE_NAME)
    private = (status_page or route in PRIVATE_ROUTES or bool(edition and not edition.get("published_at"))
               or not settings.PUBLIC_BASE_URL)
    canonical = absolute(request.path)
    image = absolute(cover["url"]) if cover else absolute(static("maison/logo.png"))
    return {
        "title": full_title, "description": _shorten(description or SITE_DESCRIPTION), "share": not private,
        "canonical": canonical, "type": og_type, "locale": OG_LOCALES.get(locale, "en_US"),
        "image": image, "image_alt": cover.get("alt") if cover else "Earnalism — Where Learning Becomes Earning",
        "image_width": cover.get("width") if cover else 1400, "image_height": cover.get("height") if cover else 500,
        "card": "summary_large_image" if cover else "summary",
        "alternates": [{"hreflang": code, "href": canonical} for code in SERVED_LOCALES] + [{"hreflang": "x-default", "href": canonical}],
    }


@require_safe
def favicon(request):
    # The release-specific static URL changes with each static release, so this is a temporary redirect.
    return HttpResponseRedirect(static("maison/logo.png"))


def _sitemap_territory(request):
    from .views import trusted_territory
    territory = trusted_territory(request)
    allowed = settings.MAISON_PUBLICATION_TERRITORIES
    # A title is published only once it is cleared in every active region, so any active region lists the same titles.
    return territory if territory in allowed else allowed[0]


def sitemap_entries(request):
    from library.catalog_query import catalog_queryset
    titles = []
    for edition in catalog_queryset(None, _sitemap_territory(request)).order_by("id")[:49000]:
        revision = edition.live_revision
        if not revision.published_at:
            continue
        titles.append((absolute(reverse("web:title", args=["en", edition.id])), revision.updated_at or revision.published_at))
    latest = max((stamp for _, stamp in titles), default=None)
    hubs = [(absolute(reverse(name, args=["en"])), latest) for name in ("web:home", "web:explore")]
    hubs.append((absolute(reverse("web:learn", args=["en"])), None))
    return hubs + titles


@require_safe
def sitemap(request):
    ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
    urlset = ET.Element("urlset", {"xmlns": ns})
    for loc, lastmod in sitemap_entries(request):
        url = ET.SubElement(urlset, "url")
        ET.SubElement(url, "loc").text = loc
        if lastmod:
            ET.SubElement(url, "lastmod").text = lastmod.date().isoformat()
    body = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(urlset, encoding="utf-8")
    response = HttpResponse(body, content_type="application/xml; charset=utf-8")
    response["Cache-Control"] = "public,max-age=0,must-revalidate"  # same as the podcast feed
    return response


@require_safe
def robots(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        # Share previews fetch covers from the content API, so only that part of /api/ stays open.
        "Allow: /api/v1/content/covers/",
        "Disallow: /api/",
        "Disallow: /admin/",
        "Disallow: /en/staff/",
        "",
        "Sitemap: " + absolute(reverse("web:sitemap")),
        "",
    ]
    response = HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "public,max-age=0,must-revalidate"
    return response
