"""Live-site audit 2026-11-26 (task W1): per-page titles and sharing tags, favicon, sitemap and robots,
content-language marks, the hidden local-build notice, tap targets and the reader header logo."""
import io
import re
import tempfile
import xml.etree.ElementTree as ET
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.templatetags.static import static
from django.test import TestCase, override_settings

from library.models import Edition, Revision

ORIGIN = "https://theearnalism.com"
EN = "20000000-0000-4000-8000-000000000001"
BN = "20000000-0000-4000-8000-000000000002"


def head(html):
    return html.split("</head>", 1)[0]


def meta(html, attr, name):
    found = re.findall(r'<meta %s="%s" content="([^"]*)"' % (attr, re.escape(name)), head(html))
    return unescape(found[0]) if len(found) == 1 else found


def title(html):
    return unescape(re.search(r"<title>(.*?)</title>", html, re.S).group(1))


def link(html, rel):
    return re.findall(r'<link rel="%s"(?: hreflang="([^"]*)")? href="([^"]*)"' % rel, head(html))


class UnmarkedBengali(HTMLParser):
    """Text runs in Bengali script whose nearest lang attribute is not bn."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr", "use"}

    def __init__(self):
        super().__init__()
        self.stack, self.found, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        lang = dict(attrs).get("lang")
        self.stack.append((tag, lang if lang is not None else (self.stack[-1][1] if self.stack else None)))
        self.skip += tag in ("script", "style")

    def handle_endtag(self, tag):
        while self.stack:
            name, _ = self.stack.pop()
            self.skip -= name in ("script", "style")
            if name == tag:
                break

    def handle_data(self, data):
        if not self.skip and re.search("[ঀ-৿]", data) and (not self.stack or self.stack[-1][1] != "bn"):
            self.found.append(data.strip())


def sign_in(client, user):
    client.get("/en/sign-in/")
    data = {"email": user.email, "password": "A-strong-local-password-47", "return_to": "/en/", "password_purpose_consent": "on",
            "password_purpose_version": "password-account-v1"}
    if settings.CSRF_COOKIE_NAME in client.cookies:
        data["csrfmiddlewaretoken"] = client.cookies[settings.CSRF_COOKIE_NAME].value
    client.post("/en/sign-in/", data)


class SiteQualityTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        override = override_settings(MEDIA_ROOT=directory.name, MAISON_LOCAL_FIXTURES=True, LOCAL=True, PUBLIC_BASE_URL=ORIGIN)
        override.enable(); self.addCleanup(override.disable)
        call_command("seed_local_pilot", stdout=io.StringIO())
        self.reader_bn = f"/en/read/{BN}/40000000-0000-4000-8000-000000000002/"

    def get(self, path, status=200):
        response = self.client.get(path)
        self.assertEqual(response.status_code, status, path)
        return response.content.decode()

    def public_pages(self):
        return {"home": "/en/", "explore": "/en/explore/", "learn": "/en/learn/", "search": "/en/search/",
                "title_en": f"/en/titles/{EN}/", "title_bn": f"/en/titles/{BN}/", "reader_bn": self.reader_bn,
                "series": "/en/series/", "sign_in": "/en/sign-in/", "privacy": "/en/privacy/"}

    def test_every_page_type_has_its_own_title_and_description(self):
        pages = {name: self.get(path) for name, path in self.public_pages().items()}
        titles = {name: title(html) for name, html in pages.items()}
        descriptions = {name: meta(html, "name", "description") for name, html in pages.items()}
        self.assertEqual(len(set(titles.values())), len(titles), titles)
        self.assertEqual(len(set(descriptions.values())), len(descriptions), descriptions)
        self.assertEqual(titles["home"], "Earnalism · Read, listen and learn")
        self.assertEqual(titles["explore"], "Explore the library · Earnalism")
        self.assertEqual(titles["learn"], "Learn · Earnalism")
        for name in ("title_en", "title_bn"):
            edition = Edition.objects.select_related("live_revision").get(pk=EN if name == "title_en" else BN)
            self.assertEqual(titles[name], f"{edition.live_revision.title} · Earnalism")
            self.assertEqual(descriptions[name], edition.live_revision.description)
        for html in pages.values():
            self.assertEqual(head(html).count("<title>"), 1)

    def test_title_page_shares_the_book_with_its_cover(self):
        html = self.get(f"/en/titles/{BN}/")
        revision = Revision.objects.get(edition_id=BN, state="live")
        canonical = f"{ORIGIN}/en/titles/{BN}/"
        self.assertEqual(link(html, "canonical"), [("", canonical)])
        self.assertEqual(link(html, "alternate"), [("en", canonical), ("x-default", canonical)])
        self.assertEqual(meta(html, "property", "og:type"), "book")
        self.assertEqual(meta(html, "property", "og:url"), canonical)
        self.assertEqual(meta(html, "property", "og:title"), f"{revision.title} · Earnalism")
        self.assertEqual(meta(html, "property", "og:description"), revision.description)
        self.assertEqual(meta(html, "property", "og:site_name"), "Earnalism")
        self.assertEqual(meta(html, "property", "og:locale"), "bn_IN")
        image = meta(html, "property", "og:image")
        self.assertRegex(image, r"^https://theearnalism\.com/api/v1/content/covers/[0-9a-f-]{36}$")
        self.assertNotIn("/staff/", image)
        self.assertEqual(meta(html, "name", "twitter:card"), "summary_large_image")
        self.assertEqual(meta(html, "name", "twitter:image"), image)

    def test_hub_pages_share_the_logo_as_a_website(self):
        for path in ("/en/", "/en/explore/", "/en/learn/"):
            html = self.get(path)
            self.assertEqual(link(html, "canonical"), [("", ORIGIN + path)])
            self.assertEqual(meta(html, "property", "og:type"), "website")
            self.assertEqual(meta(html, "property", "og:locale"), "en_US")
            self.assertTrue(meta(html, "property", "og:image").endswith(static("maison/logo.png")))
            self.assertTrue(meta(html, "property", "og:image").startswith("https://"))
            self.assertEqual(meta(html, "name", "twitter:card"), "summary")
        # Query strings never become the canonical address.
        self.assertEqual(link(self.get("/en/explore/?format=reader"), "canonical"), [("", ORIGIN + "/en/explore/")])

    def test_private_and_error_pages_carry_no_sharing_tags(self):
        user = get_user_model().objects.create_user("w1@example.test", "A-strong-local-password-47", is_verified=True)
        for html in (self.get("/en/titles/00000000-0000-4000-8000-00000000dead/", 404), self.get("/en/password-reset/abc123token/")):
            self.assertEqual(link(html, "canonical"), [])
            self.assertNotIn('property="og:', html)
        sign_in(self.client, user)
        html = self.get("/en/settings/")
        self.assertEqual(link(html, "canonical"), [])
        self.assertIn('content="noindex,nofollow"', html)

    def test_draft_edition_is_never_shared(self):
        from web.seo import page_meta
        from django.test import RequestFactory
        from django.urls import resolve
        request = RequestFactory().get(f"/en/titles/{BN}/")
        request.resolver_match = resolve(request.path)
        draft = {"title": "Draft", "locale": "bn", "published_at": None, "cover": {"url": "/api/v1/staff/draft-covers/x"}}
        values = page_meta(request, {"edition": draft}, "web/title.html")
        self.assertFalse(values["share"])
        self.assertNotIn("staff", values["image"])

    def test_favicon_link_and_route_use_the_unaltered_logo(self):
        html = self.get("/en/")
        self.assertIn(f'<link rel="icon" type="image/png" href="{static("maison/logo.png")}">', html)
        for method in (self.client.get, self.client.head):
            response = method("/favicon.ico")
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response["Location"], static("maison/logo.png"))

    def test_sitemap_lists_hubs_and_live_titles_and_robots_points_to_it(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/xml"))
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        root = ET.fromstring(response.content)
        entries = {url.findtext("s:loc", namespaces=ns): url.findtext("s:lastmod", namespaces=ns) for url in root.findall("s:url", ns)}
        for path in ("/en/", "/en/explore/", "/en/learn/", f"/en/titles/{EN}/", f"/en/titles/{BN}/"):
            self.assertIn(ORIGIN + path, entries)
        revision = Revision.objects.get(edition_id=EN, state="live")
        self.assertEqual(entries[f"{ORIGIN}/en/titles/{EN}/"], revision.updated_at.date().isoformat())
        self.assertTrue(all(loc.startswith(ORIGIN + "/en/") for loc in entries))
        self.assertFalse(any("/staff/" in loc or "/read/" in loc for loc in entries))
        # A title that is no longer live leaves the sitemap.
        Revision.objects.filter(edition_id=BN).update(state="retired")
        self.assertNotIn(f"/en/titles/{BN}/", self.client.get("/sitemap.xml").content.decode())
        robots = self.client.get("/robots.txt")
        self.assertEqual(robots.status_code, 200)
        self.assertIn(f"Sitemap: {ORIGIN}/sitemap.xml", robots.content.decode())
        self.assertIn("Disallow: /en/staff/", robots.content.decode())

    def test_explore_hub_is_indexable_while_private_pages_stay_noindex(self):
        # Production refuses requests that bypass the edge (OriginMiddleware), so call the views directly.
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory
        from django.urls import resolve

        def robots(path):
            request = RequestFactory().get(path)
            request.user, request.territory, request.resolver_match = AnonymousUser(), "IN", resolve(request.path_info)
            match = request.resolver_match
            response = match.func(request, *match.args, **match.kwargs)
            self.assertEqual(response.status_code, 200, path)
            return re.search(r'<meta name="robots" content="([^"]+)"', response.content.decode()).group(1)

        with override_settings(LOCAL=False):
            self.assertEqual(robots("/en/explore/"), "index,follow")
            self.assertEqual(robots("/en/learn/"), "index,follow")
            for path in ("/en/explore/?q=river", "/en/search/", "/en/sign-in/"):
                self.assertEqual(robots(path), "noindex,nofollow", path)
        # Readers never ask to be indexed (the local fixture rights exist only in local builds).
        self.assertIn('<meta name="robots" content="noindex,nofollow">', self.get(self.reader_bn))

    def test_bengali_fragments_carry_their_edition_language(self):
        explore = self.get("/en/explore/")
        self.assertIn('<p lang="bn">Maison local fixture authors</p>', explore)
        title_page = self.get(f"/en/titles/{BN}/")
        self.assertRegex(title_page, r'<h1 lang="bn">[^<]+</h1><p lang="bn">Maison local fixture authors</p>')
        self.assertRegex(self.get(f"/en/titles/{EN}/"), r'<h1 lang="en">[^<]+</h1><p lang="en">Maison local fixture authors</p>')
        self.assertRegex(self.get(self.reader_bn), r'<span class="room-evening-title" lang="bn">')
        for path in ("/en/", "/en/explore/", "/en/learn/", f"/en/titles/{BN}/", self.reader_bn):
            parser = UnmarkedBengali()
            parser.feed(self.get(path).split("</head>", 1)[1])
            self.assertEqual(parser.found, [], path)

    def test_local_build_notice_is_not_shown_to_readers(self):
        notice = "Offline delivery is not qualified in this local build yet."

        def visible(path):
            # The inert UI catalogue (a JSON script) lists every string; only rendered text matters here.
            return re.sub(r"<script.*?</script>", "", self.get(path), flags=re.S)

        for path in (f"/en/titles/{EN}/", f"/en/titles/{BN}/"):
            self.assertNotIn(notice, visible(path))
        member = get_user_model().objects.create_user("w1-member@example.test", "A-strong-local-password-47", is_verified=True)
        sign_in(self.client, member)
        self.assertIn("data-save-edition", visible(f"/en/titles/{EN}/"))  # signed in
        self.assertNotIn(notice, visible(f"/en/titles/{EN}/"))


class TapTargetAndLogoStyleTests(TestCase):
    css = (Path(settings.BASE_DIR) / "static/maison/room/room.css").read_text()

    def test_small_controls_get_a_44px_hit_area_without_moving(self):
        rule = re.search(r"([^{}]*)::after\{content:\"\";position:absolute;left:50%;top:50%;width:max\(100%,44px\);height:max\(100%,44px\)", self.css)
        self.assertIsNotNone(rule)
        for selector in (".room-logo-mini", ".focus-toolbar>a", ".actions>a:not(.button)", ".book-row h3 a", ".room-footer a", ".unit-list a"):
            self.assertIn(selector + "::after", rule.group(1) + "::after")
        self.assertNotIn(".turn-dot{width:28px}", self.css)

    def test_reader_logo_image_box_stops_at_the_visible_logo(self):
        self.assertIn("width:calc(1197px*var(--s));max-width:none;object-fit:cover;object-position:0 0", self.css)
        self.assertIn(".room-logo-mini img{clip-path:inset(", self.css)
