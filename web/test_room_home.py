"""Owner-approved reading-room home (22 Nov 2026): light handmade-paper shell, capsule menu and the
taste-first carousel whose single action is "Start Chapter 1 free"."""
import io
import re
import tempfile
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from .views import carousel_links

HEADLINES = ["Five spare minutes? Read a page, not a feed.", "Your language, your shelf.",
             "Your place follows you.", "Learn one idea at a time."]
GIANT = {"edition_id": "11111111-1111-4111-8111-111111111111", "title": "The Selfish Giant", "locale": "en"}
JUDGE = {"edition_id": "22222222-2222-4222-8222-222222222222", "title": "বিচারক", "locale": "bn"}


class CarouselLinkTests(SimpleTestCase):
    def test_guest_signs_up_and_returns_to_that_books_first_chapter(self):
        links = carousel_links([GIANT, JUDGE], "en", authenticated=False)
        self.assertEqual(links["giant"], f"/en/sign-up/?return_to=/en/read/{GIANT['edition_id']}/")
        self.assertEqual(links["bicharak"], f"/en/sign-up/?return_to=/en/read/{JUDGE['edition_id']}/")

    def test_unpublished_title_falls_back_to_the_library(self):
        self.assertEqual(carousel_links([], "en", authenticated=False),
                         {"giant": "/en/sign-up/?return_to=/en/explore/", "bicharak": "/en/sign-up/?return_to=/en/explore/"})

    def test_member_goes_straight_to_the_chapter(self):
        links = carousel_links([GIANT], "en", authenticated=True)
        self.assertEqual(links, {"giant": f"/en/read/{GIANT['edition_id']}/", "bicharak": "/en/explore/"})


class RoomHomeTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        override = override_settings(MEDIA_ROOT=directory.name, MAISON_LOCAL_FIXTURES=True, LOCAL=True)
        override.enable(); self.addCleanup(override.disable)
        call_command("seed_local_pilot", stdout=io.StringIO())

    def html(self):
        response = self.client.get("/en/")
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_reading_room_shell_replaces_the_dark_shell_on_home(self):
        page = self.html()
        for needle in ("maison/room/room.css", "maison/room/room.js", "maison/fonts/typography.css", "maison/logo.png",
                       'class="room-nav"', 'data-route="home"', '<html lang="en"', "maison/art/hero.png"):
            self.assertIn(needle, page)
        self.assertRegex(page, r'<a[^>]*aria-current="page"[^>]*>Home</a>')
        self.assertNotIn("pc-halo", page)
        self.assertNotIn("fonts.googleapis", page)

    def test_page_obeys_the_content_security_policy(self):
        page = self.html()
        self.assertNotRegex(page, r'\sstyle="')
        for tag in re.findall(r"<script\b[^>]*>", page):
            self.assertTrue('src="' in tag or 'type="application/json"' in tag, tag)

    def test_carousel_has_four_cards_with_one_action(self):
        page = self.html()
        self.assertIn('id="turner"', page)
        self.assertIn("Swap one scroll for one story.", page)
        for headline in HEADLINES:
            self.assertIn(headline, page)
        self.assertEqual(page.count("Start Chapter 1 free"), 4)
        self.assertIn("Every afternoon, as they were coming from school", re.sub(r"<[^>]+>", "", page))
        self.assertIn("Coming soon", page)
        self.assertEqual(len(re.findall(r'href="/en/sign-up/\?return_to=/en/', page)), 4 + 4)  # 4 cards + header, hero, closing band, footer

    def test_open_territories_are_listed_from_settings(self):
        page = self.html()
        from .legal import active_countries
        for name in active_countries():
            self.assertIn(name, page)

    def test_member_keeps_the_continue_island_and_loses_the_signup_call(self):
        user = get_user_model().objects.create_user("room@example.test", "A-strong-local-password-47", is_verified=True)
        self.client.get("/en/sign-in/")
        data = {"email": user.email, "password": "A-strong-local-password-47", "return_to": "/en/", "password_purpose_consent": "on",
                "password_purpose_version": "password-account-v1"}
        if settings.CSRF_COOKIE_NAME in self.client.cookies:
            data["csrfmiddlewaretoken"] = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        self.client.post("/en/sign-in/", data)
        page = self.html()
        self.assertIn("home-island", page)
        self.assertNotIn("Start reading free", page)

    def test_every_room_asset_is_in_the_static_tree(self):
        page = self.html()
        root = Path(settings.BASE_DIR) / "static"
        for asset in set(re.findall(r"/static/(maison/room/[A-Za-z0-9_.-]+)", page)):
            self.assertTrue((root / asset).is_file(), asset)
        css = (root / "maison/room/room.css").read_text()
        for url in re.findall(r"url\(['\"]?([^)'\"]+)", css):
            self.assertTrue((root / "maison/room" / url).resolve().is_file(), url)
