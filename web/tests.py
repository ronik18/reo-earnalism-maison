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
        self.assertEqual(safe_return(value, "en"), value.replace("/bn/","/en/",1))

    def test_external_and_auth_loop_destinations_are_rejected(self):
        for value in ("https://example.invalid/", "//example.invalid/", "/en/sign-in/", "/en/password-reset/", "/\\example.invalid/", "/en/\r\nX-Header:test", "/admin/"):
            with self.subTest(value=value):
                self.assertEqual(safe_return(value, "bn"), "/en/")

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
        data = {"email":self.user.email, "password":"A-strong-local-password-47", "return_to":destination, "password_purpose_consent":"on", "password_purpose_version":"password-account-v1"}
        if settings.CSRF_COOKIE_NAME in client.cookies:
            data["csrfmiddlewaretoken"] = client.cookies[settings.CSRF_COOKIE_NAME].value
        return client.post(reverse("web:sign-in", args=["en"]), data)

    def test_offline_shell_remains_anonymous_for_signed_in_member(self):
        self.login()
        response=self.client.get("/en/offline/")
        self.assertContains(response,'data-member="false"')
        self.assertNotContains(response,str(self.user.public_id))
        self.assertNotContains(response,self.user.email)
        self.assertContains(response,'"offline": true')

    def test_browse_and_title_use_actual_fixture(self):
        response = self.client.get("/en/")
        self.assertContains(response, "The River Notebook")
        self.assertNotIn("We could not complete that action.", response.content.decode().split("<main",1)[1].split("</main>",1)[0])
        self.assertContains(response, "draft and test editions")
        response = self.client.get("/en/titles/river-notebook-en/")
        self.assertContains(response, self.unit)
        self.assertContains(response, "20000000-0000-4000-8000-000000000002")
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
        response = self.client.get("/bn/titles/river-notebook-en/", follow=True)
        self.assertContains(response, "The River Notebook")

    def test_anonymous_reader_is_bounded_preview_not_full_book(self):
        from unittest.mock import patch
        from library import services
        from library.models import Paragraph
        rows = list(Paragraph.objects.filter(unit_id=self.unit).order_by("ordinal"))
        last = rows[-1]
        # The fixture's first chapter is about 200 words, so the whole chapter is the preview.
        response = self.client.get(f"/en/read/{self.edition}/{self.unit}/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for row in rows:
            self.assertIn(f'<p id="anchor-{row.anchor_id}" data-anchor="{row.anchor_id}">{row.text}</p>', html)
        self.assertContains(response, f"anchor%3D{last.anchor_id}%26offset%3D{len(last.text)}")
        self.assertLess(html.index(f'anchor-{last.anchor_id}"'), html.index("data-preview-fallback"))
        self.assertContains(response, "You have reached the end of the free preview.")
        self.assertContains(response, '"preview": true')
        self.assertNotContains(response, 'id="complete-reading"')
        # A longer chapter stops after the paragraph that reaches the word limit, never mid-paragraph.
        with patch.object(services, "PREVIEW_WORD_LIMIT", 70):
            response = self.client.get(f"/en/read/{self.edition}/{self.unit}/")
        self.assertContains(response, rows[1].text)
        self.assertNotContains(response, rows[2].text)
        self.assertNotContains(response, last.text)
        self.assertContains(response, "Sign in")
        self.assertContains(response, f"anchor%3D{rows[1].anchor_id}%26offset%3D{len(rows[1].text)}")
        self.assertContains(response, "You have reached the end of the free preview.")

    def test_signed_in_reader_still_gets_the_whole_unit_beyond_the_preview(self):
        from unittest.mock import patch
        from library import services
        from library.models import Paragraph
        self.login()
        rows = list(Paragraph.objects.filter(unit_id=self.unit).order_by("ordinal"))
        with patch.object(services, "PREVIEW_WORD_LIMIT", 70):
            response = self.client.get(f"/en/read/{self.edition}/{self.unit}/")
        for row in rows:
            self.assertContains(response, row.text)
        self.assertContains(response, '"preview": false')
        self.assertNotContains(response, "data-preview-fallback")
        self.assertContains(response, 'id="complete-reading"')

    def test_anonymous_preview_keeps_note_after_its_paragraph(self):
        from unittest.mock import patch
        from library import services
        from library.models import Paragraph
        rows = list(Paragraph.objects.filter(unit_id=self.unit).order_by("ordinal"))
        real = services.paragraph_dto
        def with_note(paragraph):  # published rows are frozen; mark the third anchor as the second paragraph's note
            value = real(paragraph)
            if paragraph.anchor_id == rows[2].anchor_id:
                value["kind"] = "note"
            return value
        with patch.object(services, "PREVIEW_WORD_LIMIT", 70), patch.object(services, "paragraph_dto", with_note):
            response = self.client.get(f"/en/read/{self.edition}/{self.unit}/")
        html = response.content.decode()
        self.assertIn(f'id="anchor-{rows[2].anchor_id}" data-anchor="{rows[2].anchor_id}" class="footnote" role="note">', html)
        self.assertLess(html.index(f'anchor-{rows[1].anchor_id}"'), html.index(f'anchor-{rows[2].anchor_id}"'))
        self.assertNotContains(response, rows[3].text)
        self.assertContains(response, f"anchor%3D{rows[2].anchor_id}%26offset%3D{len(rows[2].text)}")

    def test_password_sign_in_preserves_relative_reader_destination(self):
        destination = f"/bn/read/{self.edition}/{self.unit}/?anchor=existing-anchor"
        client = Client(enforce_csrf_checks=True)
        response = self.login(client, destination)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], destination.replace("/bn/","/en/",1))
        self.assertEqual(client.get("/api/v1/session").json()["authenticated"], True)

    def test_sign_in_rejects_external_redirect(self):
        response = self.login(destination="https://example.invalid/steal")
        self.assertEqual(response["Location"], "/en/")

    def test_ui_locale_does_not_change_reader_edition(self):
        self.login()
        from library.models import Paragraph
        english = Paragraph.objects.filter(unit_id=self.unit).first().text
        response = self.client.get(f"/bn/read/{self.edition}/{self.unit}/", follow=True)
        self.assertContains(response, 'lang="en" data-ui-locale="en"')
        self.assertContains(response, 'id="reading-text" lang="en"')
        self.assertContains(response, english)
        self.assertContains(response, "Mark finished")

    def test_author_note_renders_as_a_footnote_after_its_paragraph(self):
        self.login()
        from unittest.mock import patch
        from library import services
        from library.models import Paragraph
        unit="40000000-0000-4000-8000-000000000002"
        rows=list(Paragraph.objects.filter(unit_id=unit).order_by("ordinal")[:2])
        self.assertEqual(len(rows),2)
        real=services.get_reader_document
        def with_note(*args,**kwargs):  # published rows are frozen; mark the second anchor as an author's note
            document=real(*args,**kwargs)
            for paragraph in document["paragraphs"]:
                if paragraph["anchor_id"]==str(rows[1].anchor_id):
                    paragraph["kind"]="note"
            return document
        with patch.object(services,"get_reader_document",with_note):
            response=self.client.get(f"/en/read/20000000-0000-4000-8000-000000000002/{unit}/")
        html=response.content.decode()
        self.assertIn(f'id="anchor-{rows[1].anchor_id}" data-anchor="{rows[1].anchor_id}" class="footnote" role="note">',html)
        self.assertLess(html.index(f'anchor-{rows[0].anchor_id}"'),html.index(f'anchor-{rows[1].anchor_id}"'))

    def test_bengali_book_keeps_its_text_and_language_in_the_english_reader(self):
        self.login()
        from library.models import Paragraph
        edition="20000000-0000-4000-8000-000000000002"
        unit="40000000-0000-4000-8000-000000000002"
        original=Paragraph.objects.filter(unit_id=unit).first().text
        response=self.client.get(f"/en/read/{edition}/{unit}/")
        self.assertContains(response,'lang="en" data-ui-locale="en"')
        self.assertContains(response,'id="reading-text" lang="bn"')
        self.assertContains(response,original)
        self.assertContains(response,"Mark finished")
        self.assertNotContains(response,'aria-label="Interface language"')

    def test_legacy_login_error_uses_english_and_preserves_email(self):
        response = self.client.post("/bn/sign-in/", {"email":self.user.email,"password":"wrong","return_to":"/bn/vault/","password_purpose_consent":"on","password_purpose_version":"password-account-v1"}, follow=True)
        self.assertContains(response, "The email or password could not be verified.", status_code=403)
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
        self.assertNotContains(response, "<p>Answers are graded by the server")  # only the quiz island's offline notice may show this

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
        self.assertEqual(response["Referrer-Policy"], "strict-origin")

    def test_accepted_search_facets_and_saved_filter_control_are_exposed(self):
        self.login()
        response = self.client.get("/bn/search/?content_locale=en&house=golpo&duration_max=100&recency_days=7", follow=True)
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


    def test_welcome_and_new_destinations_preserve_safe_state(self):
        response=self.client.get("/en/welcome/?return_to=//foreign.invalid/")
        self.assertContains(response,'"return_to": "/en/"')
        self.assertContains(response,'onboarding-island')
        collection=self.client.get("/en/collections/90000000-0000-4000-8000-000000000001/")
        self.assertContains(collection,'The River Notebook')
        series=self.client.get("/en/series/")
        self.assertContains(series,'There are no released series')
        self.assertNotContains(series,'Local original stories')
        video=self.client.get(f"/en/watch/{self.edition}/")
        self.assertContains(video,'"enabled": false')
        self.assertNotContains(video,'<iframe')

    def test_member_home_is_private_and_preview_cannot_bootstrap_protected_navigation(self):
        self.login()
        home=self.client.get("/en/")
        self.assertContains(home,'home-island')
        self.assertIn('no-store',home['Cache-Control'])
        from library.models import Revision
        from unittest.mock import patch
        revision=Revision.objects.get(edition_id=self.edition)
        # Access policy is immutable after publication; simulate the service access denial.
        from core.api import DomainError
        with patch('library.services.get_reader_document',side_effect=DomainError('entitlement_required','Access required.',403)):
            response=self.client.get(f"/en/read/{self.edition}/{self.unit}/")
        self.assertContains(response,'"preview": true')
        self.assertContains(response,'"next_unit_url": null')
        self.assertContains(response,'"player_url": null')
        self.assertNotContains(response,'The complete notebook')

    def test_checkout_owner_scope_and_system_errors(self):
        from billing.models import Offer,Order
        from datetime import timedelta
        offer=Offer.objects.create(code='ui-checkout',name='UI fixture offer',price_minor=100,duration_seconds=86400,formats=['reader'])
        order=Order.objects.create(user=self.user,offer=offer,total_minor=100,currency='INR',offer_snapshot={},operation_id=uuid.uuid4(),request_sha256='0'*64,expires_at=timezone.now()+timedelta(hours=1),return_path=f"/bn/read/{self.edition}/{self.unit}/?anchor=exact")
        path=f"/en/checkout/{order.id}/"
        self.assertEqual(self.client.get(path).status_code,302)
        self.login()
        response=self.client.get(path)
        self.assertContains(response,str(order.id))
        self.assertContains(response,'anchor=exact')
        other=get_user_model().objects.create_user('other-ui@example.test','A-strong-local-password-47',is_verified=True)
        foreign=Order.objects.create(user=other,offer=offer,total_minor=100,currency='INR',offer_snapshot={},operation_id=uuid.uuid4(),request_sha256='1'*64,expires_at=timezone.now()+timedelta(hours=1))
        self.assertEqual(self.client.get(f'/en/checkout/{foreign.id}/').status_code,404)
        self.assertEqual(self.client.get('/en/404/').status_code,404)
        self.assertEqual(self.client.get('/bn/maintenance/', follow=True).status_code,503)


class OfflineAssetBuildTests(SimpleTestCase):
    def test_release_prefixed_cdn_urls_and_content_changes_version_worker(self):
        from django.test import RequestFactory
        from .views import service_worker
        from shutil import copyfile
        original=Path(settings.BASE_DIR)/"static/maison/offline-worker.js"
        with TemporaryDirectory() as directory:
            root=Path(directory);public=root/"static/maison";public.mkdir(parents=True)
            copyfile(original,public/"offline-worker.js")
            names=["app.css","app.js","logo.png","fonts/typography.css","fonts/example.woff2","art/ford-gold.webp","dist/reader-test.js"]
            for name in names:
                path=public/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b"public build fixture")
            (public/"dist/manifest.json").write_text(json.dumps({"__assets":["maison/dist/reader-test.js"]}))
            base="https://assets.example.test/static/"+"a"*64+"/"
            with override_settings(BASE_DIR=root,STATIC_URL=base,STATIC_RELEASE_ID="a"*64):
                request=RequestFactory().get("/maison-sw.js")
                first=service_worker(request).content.decode()
                self.assertIn(base+"maison/dist/reader-test.js",first)
                self.assertIn(base+"maison/fonts/example.woff2",first)
                self.assertIn(base+"maison/app.css?v=",first)
                self.assertNotIn("__ASSET_BASE__",first)
                self.assertIn('"/en/offline/"',first)
                (public/"app.css").write_bytes(b"updated public CSS")
                second=service_worker(request).content.decode()
                self.assertNotEqual(re.search(r'maison-shell-([a-f0-9]+)',first).group(1),re.search(r'maison-shell-([a-f0-9]+)',second).group(1))


@override_settings(DEBUG=False,ROOT_URLCONF='web.error_test_urls')
class ActualErrorHandlerTests(SimpleTestCase):
    def test_actual_handlers_preserve_locale_status_and_private_cache(self):
        client=Client(raise_request_exception=False)
        for locale in ('en','bn'):
            for path,status,key in [('missing/nested/path/',404,'not_found'),('test-denied/',403,'not_authorized'),('test-failed/',500,'error')]:
                with self.subTest(locale=locale,status=status):
                    response=client.get(f'/{locale}/{path}',follow=True)
                    self.assertEqual(response.status_code,status)
                    self.assertEqual(response['Content-Language'],'en')
                    self.assertIn('private',response['Cache-Control'])
                    self.assertIn('no-store',response['Cache-Control'])
                    self.assertContains(response,catalogue("en")[key],status_code=status)
                    self.assertNotContains(response,'Synthetic frontend error-handler fixture',status_code=status)


class DatabaseFailureErrorPageTests(SimpleTestCase):
    def test_server_error_does_not_resolve_failed_authentication(self):
        from django.db import OperationalError
        from django.test import RequestFactory
        from django.utils.functional import SimpleLazyObject
        from .views import server_error
        def failed_user():
            raise OperationalError("Synthetic database unavailable")
        request=RequestFactory().get('/bn/unavailable/')
        request.user=SimpleLazyObject(failed_user)
        response=server_error(request)
        self.assertEqual(response.status_code,500)
        self.assertEqual(response['Content-Language'],'en')
        self.assertIn('private',response['Cache-Control'])
        self.assertIn('no-store',response['Cache-Control'])
        self.assertNotIn(b'Synthetic database unavailable',response.content)

class PasswordPurposePresentationTests(TestCase):
    def test_password_pages_present_unchecked_separate_purpose_choice(self):
        for path in ('/en/sign-in/', '/en/sign-up/', '/en/password-reset/example/'):
            response = self.client.get(path)
            self.assertContains(response, 'name="password_purpose_consent" required')
            self.assertNotContains(response, 'name="password_purpose_consent" checked')
            self.assertContains(response, 'password-account-v1')
            self.assertContains(response, 'withdraw')

    def test_ssr_rejects_missing_choice_before_password_service(self):
        from unittest.mock import patch
        for path, service in (('/en/sign-in/', 'login_member'), ('/en/sign-up/', 'register_member')):
            with patch('accounts.services.' + service) as action:
                response = self.client.post(path, {'email':'tester@example.test','password':'secret-purpose-password'})
                self.assertEqual(response.status_code, 400)
                action.assert_not_called()

    def test_admin_password_form_presents_separate_unchecked_choice(self):
        response = self.client.get('/admin/login/')
        self.assertContains(response, 'name="password_purpose_consent"')
        self.assertContains(response, 'password-account-v1')
        self.assertContains(response, 'withdraw')
        self.assertNotContains(response, 'name="password_purpose_consent" checked')

    @override_settings(EARNALISM_PUBLIC_GRIEVANCE_OFFICER_NAME='Approved <Professional>')
    def test_configured_grievance_name_is_escaped_on_both_pages(self):
        for path in ('/en/privacy/', '/en/contact/'):
            response = self.client.get(path)
            self.assertContains(response, 'Approved &lt;Professional&gt;')
            self.assertNotContains(response, 'Approved <Professional>')

class SupportAvailabilityAndAdminChangeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser('frontend-staff@example.test', 'Frontend-Staff-Password-2026')

    def login_staff(self):
        response = self.client.post('/admin/login/', {'username':self.user.email, 'password':'Frontend-Staff-Password-2026', 'password_purpose_consent':'on', 'password_purpose_version':'password-account-v1', 'next':'/admin/'})
        self.assertEqual(response.status_code, 302)

    @override_settings(SUPPORT_EMAIL='')
    def test_unconfigured_settings_offer_mailbox_without_support_collection(self):
        self.login_staff()
        response = self.client.get('/en/settings/')
        self.assertContains(response, 'mailto:sales@reoenterprise.org')
        self.assertContains(response, 'The contact form is unavailable.')
        self.assertNotContains(response, 'id="support-island"')
        self.assertNotRegex(response.content.decode(), r'<script[^>]+src="[^"]*/support-[^"]+\.js"')

    @override_settings(SUPPORT_EMAIL='configured@example.test')
    def test_configured_settings_mount_support_form(self):
        self.login_staff()
        response = self.client.get('/en/settings/')
        self.assertContains(response, 'id="support-island"')
        self.assertNotIn('The contact form is unavailable.', response.content.decode().split('</main>')[0])
        self.assertRegex(response.content.decode(), r'<script[^>]+src="[^"]*/support-[^"]+\.js"')

    def test_admin_password_change_renders_and_submits_actual_consent_fields(self):
        self.login_staff()
        response = self.client.get('/admin/password_change/')
        self.assertContains(response, 'name="password_purpose_consent"')
        self.assertContains(response, 'name="password_purpose_version"')
        self.assertContains(response, 'password-account-v1')
        self.assertContains(response, 'Reo Enterprise uses your password')
        self.assertContains(response, 'href="/en/privacy/"')
        self.assertContains(response, 'withdraw')
        self.assertNotContains(response, 'name="password_purpose_consent" checked')
        response = self.client.post('/admin/password_change/', {'old_password':'Frontend-Staff-Password-2026','new_password1':'Changed-Frontend-Password-2026','new_password2':'Changed-Frontend-Password-2026','password_purpose_consent':'on','password_purpose_version':'password-account-v1'})
        self.assertRedirects(response, '/admin/password_change/done/')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Changed-Frontend-Password-2026'))
