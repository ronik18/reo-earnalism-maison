"""Post-release audit 2 (task W5): the hero is served as AVIF/WebP renditions, reader descriptions name the book,
its author and its own blurb, a one-part story drops its one-line Contents, and small controls get 44px boxes."""
import io
import re
import tempfile
from html import unescape
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings

from library.models import Unit

EN = "20000000-0000-4000-8000-000000000001"
BN = "20000000-0000-4000-8000-000000000002"
READER_EN = f"/en/read/{EN}/40000000-0000-4000-8000-000000000001/"
READER_BN = f"/en/read/{BN}/40000000-0000-4000-8000-000000000002/"
ART = Path(settings.BASE_DIR) / "static/maison/art"
WIDTHS = (480, 640, 800, 1200, 1480)


def description(html):
    found = re.findall(r'<meta name="description" content="([^"]*)"', html.split("</head>", 1)[0])
    return unescape(found[0]) if len(found) == 1 else found


class W5PageTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        override = override_settings(MEDIA_ROOT=directory.name, MAISON_LOCAL_FIXTURES=True, LOCAL=True, PUBLIC_BASE_URL="https://theearnalism.com")
        override.enable(); self.addCleanup(override.disable)
        cache.clear(); self.addCleanup(cache.clear)
        call_command("seed_local_pilot", stdout=io.StringIO())

    def get(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, path)
        return response.content.decode()

    def test_hero_is_a_picture_of_avif_and_webp_renditions_over_the_unchanged_png(self):
        home = self.get("/en/")
        figure = re.search(r'<figure class="room-frame room-hero-art">(.*?)</figure>', home, re.S).group(1)
        sources = re.findall(r'<source type="(image/[a-z]+)" srcset="([^"]+)" sizes="([^"]+)">', figure)
        self.assertEqual([kind for kind, _, _ in sources], ["image/avif", "image/webp"])
        for kind, srcset, sizes in sources:
            extension = kind.split("/")[1]
            candidates = [part.strip().rsplit(" ", 1) for part in srcset.split(",")]
            self.assertEqual([descriptor for _, descriptor in candidates], [f"{w}w" for w in WIDTHS])
            for (url, _), width in zip(candidates, WIDTHS):
                self.assertTrue(url.endswith(f"maison/art/hero-{width}.{extension}"), url)
                self.assertTrue((ART / f"hero-{width}.{extension}").is_file())
            self.assertTrue(sizes.endswith(", 574px"))
            self.assertIn("(max-width: 1200px) calc(53.5vw - 68px)", sizes)  # .room-wrap stops growing at 1200px
        img = re.search(r"<img [^>]*>", figure).group(0)
        self.assertIn('src="/static/maison/art/hero.png"', img)
        self.assertIn('fetchpriority="high"', img)  # above the fold: never lazy
        self.assertNotIn("loading=", img)
        self.assertIn('width="1480" height="1063"', img)

    def test_hero_renditions_keep_the_artwork_dimensions(self):
        from PIL import Image
        with Image.open(ART / "hero.png") as png:
            self.assertEqual(png.size, (1480, 1063))
        for width in WIDTHS:
            for extension in ("avif", "webp"):
                with Image.open(ART / f"hero-{width}.{extension}") as image:
                    self.assertEqual(image.size, (width, round(1063 * width / 1480)))
                    self.assertLess((ART / f"hero-{width}.{extension}").stat().st_size, 400_000)

    def test_no_image_on_home_has_an_empty_source(self):
        for path in ("/en/", "/en/explore/"):
            for tag in re.findall(r"<img\b[^>]*>", self.get(path)):
                self.assertRegex(tag, r'\ssrc="[^"]+"', tag)

    def test_reader_description_names_title_author_and_edition_blurb(self):
        for path, edition_id in ((READER_EN, EN), (READER_BN, BN)):
            revision = models_live(edition_id)
            text = description(self.get(path))
            self.assertEqual(text, f"{revision.title} by Maison local fixture authors — {revision.description}")
            # Never the story text itself.
            for unit in Unit.objects.filter(revision=revision):
                for paragraph in unit.paragraphs.all()[:3]:
                    self.assertNotIn(paragraph.text[:40], text)
        self.assertNotEqual(description(self.get(READER_EN)), description(self.get(READER_BN)))

    def test_reader_description_without_author_or_blurb(self):
        from web.seo import reader_description
        self.assertEqual(reader_description({"title": "Apad", "description": ""}, []), "Apad, an edition on Earnalism.")
        self.assertEqual(reader_description({"title": "Apad", "description": " A  story. "}, ["Tagore", " "]), "Apad by Tagore — A story.")

    def test_contents_hidden_when_the_only_unit_is_named_after_the_book(self):
        title_page = f"/en/titles/{EN}/"
        self.assertIn("<h2>Contents</h2>", self.get(title_page))  # unit title differs from the book title
        from unittest import mock
        import library.services as services
        revision = models_live(EN)
        real = services.edition_units

        def units_named(title):
            # Published revisions are frozen in the database, so the unit title is varied at the service boundary.
            return lambda *args, **kwargs: [{**unit, "title": title} for unit in real(*args, **kwargs)]

        # Same title (spacing and case aside): one-line Contents is dropped; the Preview / Read button still opens the story.
        with mock.patch.object(services, "edition_units", units_named("  " + revision.title.upper() + " ")):
            html = self.get(title_page)
        self.assertNotIn("<h2>Contents</h2>", html)
        self.assertNotIn('class="unit-list"', html)
        self.assertIn(f'href="{READER_EN}"', html)
        # Two units, or one unit with its own name, keep the list.
        with mock.patch.object(services, "edition_units", lambda *a, **k: real(*a, **k) * 2):
            self.assertIn("<h2>Contents</h2>", self.get(title_page))
        with mock.patch.object(services, "edition_units", units_named("Chapter one")):
            self.assertIn("<h2>Contents</h2>", self.get(title_page))


def models_live(edition_id):
    from library.models import Edition
    return Edition.objects.get(pk=edition_id).live_revision


class W5TapTargetStyleTests(TestCase):
    css = (Path(settings.BASE_DIR) / "static/maison/room/room.css").read_text()

    def test_small_links_get_44px_boxes_that_give_the_space_back(self):
        for rule in (
            ".room-footer a,.book-row h3 a,.series-episodes h2 a,.unit-list a{min-width:44px}",
            ".focus-toolbar>a{padding:0 7px;margin:0 -7px}",
            ".title-layout .actions>a:not(.button):not(.text-link){padding:9px 0;margin:-9px 0}",
            "[data-preview-fallback] a{padding:11px 0}",
            ".turn-actions .room-link{min-height:48px;margin:-2px 0}",
            ".room-logo-mini{box-sizing:content-box;padding:5px 0 6px;margin:-5px 0 -6px;background:none;outline:0;isolation:isolate}",
            ".room-hero-picture{display:contents}",
        ):
            self.assertIn(rule, self.css)
        # the 44px box grows only the title page's sign-in link, never a .text-link (whose 16px top margin must hold)
        for line in self.css.splitlines():
            if "padding:9px 0;margin:-9px 0" in line:
                self.assertTrue(line.startswith(".title-layout .actions>a:not(.button):not(.text-link){"), line)

    def test_mini_logo_tile_is_redrawn_by_pseudo_elements(self):
        self.assertIn(".room-logo-mini::before{content:\"\";position:absolute;z-index:-1;inset:5px 0 6px;border-radius:6px;background:var(--ivory)}", self.css)
        self.assertIn("outline:4px solid var(--ivory)}", self.css.split(".room-logo-mini::after{left:0", 1)[1].split("\n", 1)[0])
