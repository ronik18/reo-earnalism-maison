"""Site quality task W4 (owner decisions 26 Nov 2026): readable gold text and labels on gold,
and a single Back link in the reader and classroom bodies (the header Back stays)."""
import io
import re
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings

EN = "20000000-0000-4000-8000-000000000001"
CSS = (Path(settings.BASE_DIR) / "static/maison/room/room.css").read_text()


def luminance(hex_colour):
    channels = [int(hex_colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def token(scope, name):
    """The last value of `name` declared in a rule whose selector is exactly `scope`."""
    values = [found.group(1) for body in re.findall(r"(?:^|[}\s])" + re.escape(scope) + r"\{([^}]*)\}", CSS)
              for found in re.finditer(r"(?:^|;)\s*" + re.escape(name) + r":(#[0-9A-Fa-f]{6})", body)]
    return values[-1]


def rule(selector):
    return re.search(re.escape(selector) + r"\{([^}]*)\}", CSS).group(1)


class GoldContrastTests(TestCase):
    def test_gold_text_on_light_surfaces_reaches_4_5(self):
        surfaces = [token(":root", "--ivory"), token(":root", "--parchment"), token("body.room", "--surface"), "#FFFFFF"]
        for text in (token("body.room", "--gold"), token(":root", "--gold-text")):
            for surface in surfaces:
                self.assertGreaterEqual(contrast(text, surface), 4.5, (text, surface))

    def test_labels_on_gold_fills_reach_4_5_at_every_gradient_stop(self):
        label = token(":root", "--burgundy-deep")
        fills = {".room-btn-gold": rule(".room-btn-gold"), ".room-cta": rule(".room-cta"),
                 ".room-nav a[aria-current=page]": rule(".room-nav a[aria-current=page]")}
        for selector, body in fills.items():
            background = re.search(r"background:([^;]*)", body).group(1)
            # body.room redefines --gold as the darker text gold, so a fill must not resolve through it.
            self.assertNotIn("var(--gold)", background, selector)
            for stop in re.findall(r"#[0-9A-Fa-f]{6}", background):
                self.assertGreaterEqual(contrast(label, stop), 4.5, (selector, stop))

    def test_gold_accents_and_dark_band_text_keep_their_approved_values(self):
        self.assertEqual(token(":root", "--gold"), "#D8B25E")
        self.assertEqual(token(":root", "--gold-deep"), "#B8913F")
        self.assertEqual(token(":root", "--gold-text"), "#7A5A1E")
        self.assertEqual(token(":root", "--gold-on-dark"), "#E6C987")
        self.assertIn("linear-gradient(180deg,#E8C676,var(--gold))", rule(".turn-pause[aria-pressed=true]"))


class SingleBackLinkTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        override = override_settings(MEDIA_ROOT=directory.name, MAISON_LOCAL_FIXTURES=True, LOCAL=True)
        override.enable(); self.addCleanup(override.disable)
        call_command("seed_local_pilot", stdout=io.StringIO())

    def test_reader_has_the_header_back_only(self):
        response = self.client.get(f"/en/read/{EN}/40000000-0000-4000-8000-000000000001/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertEqual(html.count('class="room-back"'), 1)
        self.assertIn(f'<a class="room-back" href="/en/titles/{EN}/">', html)
        toolbar = re.search(r'<div class="focus-toolbar">(.*?)</div>', html, re.S).group(1)
        self.assertNotIn("<a", toolbar)
        self.assertEqual(len(re.findall(r">Back<", html)), 1)

    def test_classroom_body_has_no_second_back(self):
        source = (Path(settings.BASE_DIR) / "templates/web/classroom.html").read_text()
        toolbar = re.search(r'<div class="focus-toolbar">(.*?)</div>', source, re.S).group(1)
        self.assertNotIn("<a", toolbar)
        self.assertNotIn("{% ui 'back' %}", source)
