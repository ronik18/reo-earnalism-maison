"""Browser-facing integration checks against the isolated PostgreSQL fixture build."""
import io
import re
from types import SimpleNamespace
import json
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .i18n import STRINGS, catalogue
from .views import safe_return, trusted_territory


class ReturnPathTests(SimpleTestCase):
    def test_return_path_retains_edition_and_anchor(self):
        value = "/bn/read/20000000-0000-4000-8000-000000000001/?anchor=example"
        self.assertEqual(safe_return(value, "en"), value)

    def test_external_and_auth_loop_destinations_are_rejected(self):
        for value in ("https://example.invalid/", "//example.invalid/", "/en/sign-in/", "/en/password-reset/", "/\\example.invalid/", "/en/\r\nX-Header:test", "/admin/"):
            with self.subTest(value=value):
                self.assertEqual(safe_return(value, "bn"), "/bn/")

    @override_settings(LOCAL=False)
    def test_production_territory_is_not_inferred_from_query(self):
        self.assertEqual(trusted_territory(SimpleNamespace(GET={"territory":"IN"})), "ZZ")
        self.assertEqual(trusted_territory(SimpleNamespace(territory="GB")), "GB")
        self.assertEqual(trusted_territory(SimpleNamespace(territory="invalid")), "ZZ")

    def test_every_literal_ui_key_and_format_label_exists(self):
        from django.conf import settings
        for template in (settings.BASE_DIR / "templates").rglob("*.html"):
            for key in re.findall(r"\{%\s*ui\s+['\"]([^'\"]+)['\"]", template.read_text()):
                self.assertIn(key, STRINGS, str(template))
        for key in ("reader", "audio", "video"):
            self.assertIn(key, STRINGS)

    def test_both_ui_catalogues_have_every_key(self):
        self.assertEqual(set(catalogue("en")), set(catalogue("bn")))
        for key, pair in STRINGS.items():
            self.assertEqual(len(pair), 2, key)
            self.assertTrue(all(isinstance(s, str) and s.strip() for s in pair), key)


class ExperienceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = TemporaryDirectory(prefix="maison-web-test-")
        cls.override = override_settings(MEDIA_ROOT=cls.media.name, MAISON_LOCAL_FIXTURES=True)
        cls.override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.override.disable()
        cls.media.cleanup()

    @classmethod
    def setUpTestData(cls):
        call_command("seed_local_pilot", stdout=io.StringIO())
        cls.user = get_user_model().objects.create_user("web-fixture@example.test", "A-strong-local-password-47", is_verified=True)
        cls.edition = "20000000-0000-4000-8000-000000000001"
        cls.unit = "40000000-0000-4000-8000-000000000001"

    def login(self, client=None, destination="/en/vault/"):
        client = client or self.client
        client.get(reverse("web:sign-in", args=["en"]))
        data = {"email":self.user.email, "password":"A-strong-local-password-47", "return_to":destination}
        if settings.CSRF_COOKIE_NAME in client.cookies:
            data["csrfmiddlewaretoken"] = client.cookies[settings.CSRF_COOKIE_NAME].value
        return client.post(reverse("web:sign-in", args=["en"]), data)

    def test_browse_and_title_use_actual_fixture(self):
        response = self.client.get("/en/")
        self.assertContains(response, "The River Notebook")
        self.assertNotIn("We could not complete that action.", response.content.decode().split("<main",1)[1].split("</main>",1)[0])
        self.assertContains(response, "draft and test editions")
        response = self.client.get("/en/titles/river-notebook-en/")
        self.assertContains(response, self.unit)
        self.assertContains(response, "20000000-0000-4000-8000-000000000002")
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
        response = self.client.get("/bn/titles/river-notebook-en/")
        self.assertContains(response, "The River Notebook")

    def test_anonymous_reader_is_bounded_preview_not_full_book(self):
        from library.models import Paragraph
        last = Paragraph.objects.filter(unit_id=self.unit).order_by("ordinal").last()
        response = self.client.get(f"/en/read/{self.edition}/{self.unit}/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, last.text)
        self.assertContains(response, "Sign in")
        self.assertContains(response, "offset%3D130")
        self.assertNotContains(response, 'id="complete-reading"')

    def test_password_sign_in_preserves_relative_reader_destination(self):
        destination = f"/bn/read/{self.edition}/{self.unit}/?anchor=existing-anchor"
        client = Client(enforce_csrf_checks=True)
        response = self.login(client, destination)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], destination)
        self.assertEqual(client.get("/api/v1/session").json()["authenticated"], True)

    def test_sign_in_rejects_external_redirect(self):
        response = self.login(destination="https://example.invalid/steal")
        self.assertEqual(response["Location"], "/en/")

    def test_ui_locale_does_not_change_reader_edition(self):
        self.login()
        from library.models import Paragraph
        english = Paragraph.objects.filter(unit_id=self.unit).first().text
        response = self.client.get(f"/bn/read/{self.edition}/{self.unit}/")
        self.assertContains(response, 'lang="bn" data-ui-locale="bn"')
        self.assertContains(response, 'id="reading-text" lang="en"')
        self.assertContains(response, english)
        self.assertContains(response, "পড়া শেষ চিহ্নিত করুন")

    def test_bengali_login_error_remains_localized_and_preserves_email(self):
        response = self.client.post("/bn/sign-in/", {"email":self.user.email,"password":"wrong","return_to":"/bn/vault/"})
        self.assertContains(response, "ইমেল বা পাসওয়ার্ড যাচাই করা যায়নি।", status_code=403)
        self.assertContains(response, self.user.email, status_code=403)
        self.assertNotContains(response, 'value="wrong"', status_code=403)

    def test_learning_question_stays_in_p0_and_quiz_is_semantic(self):
        self.login()
        response = self.client.get("/en/tracks/80000000-0000-4000-8000-000000000001/")
        self.assertContains(response, "/interview/sde/")
        self.assertNotContains(response, "/practice/")
        response = self.client.get("/en/interview/sde/80000000-0000-4000-8000-000000000001/questions/83000000-0000-4000-8000-000000000001/")
        self.assertContains(response, "circular buffer")
        self.assertContains(response, "Self-review rubric")
        response = self.client.get("/en/lessons/81000000-0000-4000-8000-000000000001/")
        self.assertContains(response, 'type="radio"')
        self.assertContains(response, "<fieldset")
        self.assertNotContains(response, '"is_correct"')

    def test_vault_lists_and_saved_have_distinct_views(self):
        self.login()
        response = self.client.get("/en/vault/?tab=saved")
        self.assertContains(response, 'data-tab="saved"')
        self.assertNotContains(response, "Highlights")
        response = self.client.get("/en/vault/?tab=lists")
        self.assertContains(response, 'id="create-list-form"')
        self.assertContains(response, "Create a list")

    def test_auth_confirmation_get_does_not_consume_action(self):
        from accounts.models import EmailActionToken
        from accounts.services import request_password_reset, _token_value
        request_password_reset(self.user.email)
        action = EmailActionToken.objects.filter(user=self.user, purpose="password_reset").first()
        if action is None:
            action = EmailActionToken.objects.filter(user=self.user).latest("created_at")
        token = _token_value(action)
        response = self.client.get("/auth/reset/", {"token":token})
        self.assertEqual(response.status_code, 200)
        action.refresh_from_db()
        self.assertIsNone(action.consumed_at)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")

    def test_accepted_search_facets_and_saved_filter_control_are_exposed(self):
        self.login()
        response = self.client.get("/bn/search/?content_locale=en&house=golpo&duration_max=100&recency_days=7")
        self.assertContains(response, 'name="duration_min"')
        self.assertContains(response, 'name="duration_max"')
        self.assertContains(response, 'name="recency_days"')
        self.assertContains(response, 'id="save-filter-form"')
        self.assertContains(response, "The River Notebook")

    def api_write(self, method, path, body, version=None):
        headers = {"HTTP_IDEMPOTENCY_KEY":str(uuid.uuid4())}
        if version is not None:
            headers["HTTP_IF_MATCH"] = f'"v{version}"'
        return self.client.generic(method, "/api/v1" + path, json.dumps(body), content_type="application/json", **headers)

    def test_reader_requests_roundtrip_without_completion_changing_progress_version(self):
        from library.models import Paragraph, Edition
        self.login()
        revision = str(Edition.objects.get(pk=self.edition).live_revision_id)
        anchor = str(Paragraph.objects.filter(unit_id=self.unit).first().anchor_id)
        progress_path = f"/me/progress/{self.edition}/reader"
        initial = self.client.get("/api/v1" + progress_path).json()
        response = self.api_write("PUT", progress_path, {
            "operation_id":str(uuid.uuid4()), "edition_revision_id":revision,
            "location":{"format":"reader","unit_id":self.unit,"anchor_id":anchor,"offset_chars":0},
            "occurred_at":timezone.now().isoformat().replace("+00:00","Z"),
        }, initial["version"])
        self.assertEqual(response.status_code, 200, response.content)
        progress_version = response.json()["version"]
        completion_path = f"/me/completion/{self.edition}/reader"
        initial_completion = self.client.get("/api/v1" + completion_path).json()
        response = self.api_write("PUT", completion_path, {"operation_id":str(uuid.uuid4()),"is_complete":True}, initial_completion["version"])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["is_complete"])
        finished = self.client.get("/api/v1/me/vault").json()["finished"]
        self.assertEqual(finished[0]["card"]["edition_id"], self.edition)
        self.assertEqual(self.client.get("/api/v1" + progress_path).json()["version"], progress_version)
        response = self.api_write("POST", "/me/annotations", {
            "annotation_id":str(uuid.uuid4()),"edition_revision_id":revision,"kind":"note","color":"mint","note_text":"A local reader note.",
            "range":{"unit_id":self.unit,"start_anchor_id":anchor,"start_offset_chars":0,"end_anchor_id":anchor,"end_offset_chars":4,"offset_unit":"unicode_code_point"},
        })
        self.assertIn(response.status_code, (200,201), response.content)
        notes = self.client.get("/api/v1/me/annotations?edition_revision_id=" + revision).json()["items"]
        self.assertEqual(notes[0]["note_text"], "A local reader note.")

    def test_saved_filter_and_full_reader_preferences_persist(self):
        self.login()
        old = self.client.get("/api/v1/me/preferences").json()
        change = {"reader_typeface":"sans","reader_font_size":30,"reader_line_height":1.85,"reader_margins":"compact","reader_alignment":"justify",
                  "saved_filters":[{"name":"My river choices","query":"River","filters":{"locale":"en","house":"golpo","duration_max":100,"recency_days":7}}]}
        response = self.api_write("PATCH", "/me/preferences", change, old["version"])
        self.assertEqual(response.status_code, 200, response.content)
        saved = self.client.get("/api/v1/me/preferences").json()
        for key, value in change.items():
            self.assertEqual(saved[key], value)
        self.assertGreater(saved["version"], old["version"])
