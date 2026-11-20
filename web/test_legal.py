from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from django.test import RequestFactory,SimpleTestCase,override_settings
from . import legal

class LegalNoticeTests(SimpleTestCase):
    def request(self,path,method='get'):
        request=getattr(RequestFactory(),method)(path);request.user=AnonymousUser();return request
    def test_notices_disclose_pending_facts_and_remain_private(self):
        for view in [legal.privacy,legal.terms,legal.contact]:
            response=view(self.request('/en/privacy/'),'en')
            self.assertEqual(response.status_code,200)
            self.assertContains(response,'sales@reoenterprise.org')
            self.assertContains(response,'Qualification notice')
            self.assertContains(response,'Reo Enterprise')
            self.assertContains(response,'Kolkata - 700083')
            self.assertContains(response,'Chief of Operations / Grievance Officer')
            self.assertIn('no-store',response['Cache-Control'])
    def test_bengali_copy_and_invalid_locale(self):
        response=legal.privacy(self.request('/bn/privacy/'),'bn')
        self.assertContains(response,'Privacy notice')
        with self.assertRaises(Http404):legal.privacy(self.request('/xx/privacy/'),'xx')
    def test_notices_cannot_submit_mutations(self):
        self.assertEqual(legal.privacy(self.request('/en/privacy/','post'),'en').status_code,405)

    def test_integrated_routes_and_footer_discovery(self):
        for locale in ["en","bn"]:
            for route in ["privacy","terms","contact"]:
                response=self.client.get(f"/{locale}/{route}/",follow=True)
                self.assertEqual(response.status_code,200)
                self.assertContains(response,'href="/en/privacy/"')
                self.assertContains(response,'href="/en/terms/"')
                self.assertContains(response,'href="/en/contact/"')
                self.assertContains(response,"sales@reoenterprise.org")

    def test_contact_form_requires_configured_support_destination(self):
        for destination,expected in [("",False),("sales@reoenterprise.org",True)]:
            with self.subTest(configured=expected),override_settings(SUPPORT_EMAIL=destination):
                response=self.client.get("/en/contact/")
                self.assertEqual(response.status_code,200)
                self.assertEqual(b'id="support-island"' in response.content,expected)
                self.assertContains(response,'mailto:sales@reoenterprise.org')


    def test_current_retention_and_provider_facts_replace_obsolete_pending_claims(self):
        response=legal.privacy(self.request('/en/privacy/'),'en')
        for fact in ['20 November 2026','7 days after expiry or use','35-day window','90 days after an operator records actual resolution','latest 12 calendar-month snapshots','7 days under the approved isolated-service exception','Cloudflare','signed Stream video','Google sign-in','Singapore','Recorded legal/retention holds']:
            self.assertContains(response,fact)
        for obsolete in ['awaiting confirmation','retention schedule and applicable request periods','Provider processing and applicable transfer arrangements must be finalized']:
            self.assertNotContains(response,obsolete)
        self.assertContains(response,'account deletion does not instantly erase immutable backups')
        self.assertContains(response,'Existing business-mail copies remain operator-managed')
        self.assertContains(response,'Future public-audience qualification and exact-edition publication across the approved 47 territories remain separate')

    def test_legacy_locale_uses_current_english_notice(self):
        response=legal.privacy(self.request('/bn/privacy/'),'bn')
        for fact in ['20 November 2026','35-day window','90 days','30 days','12 calendar-month snapshots','Google','Stream','Singapore','Recorded legal/retention holds','internationally']:
            self.assertContains(response,fact)
        self.assertContains(response,'lang="en" data-ui-locale="en"')
        self.assertNotContains(response,'awaiting confirmation')

    @override_settings(FREE_ACCESS_ENABLED=True)
    def test_free_terms_preserve_reading_audience_and_no_future_payment_commitment(self):
        response=legal.terms(self.request('/en/terms/'),'en')
        self.assertContains(response,'No payment details or automatic subscription are required')
        self.assertContains(response,'Any future paid plan requires a separate explicit choice')
        self.assertContains(response,'readers of any age')
        self.assertContains(response,'New paid purchases are disabled during free access')
        self.assertNotContains(response,'Payments, audio/video and offline access remain unavailable')


    def test_current_operator_tester_and_agreement_facts_do_not_claim_future_clearance(self):
        response=legal.privacy(self.request('/en/privacy/'),'en')
        for fact in ['registered Indian proprietorship','authorized adult staff/testers','no real customers or known child accounts','not a new age restriction','Cloud Data Processing Addendum accepted','Google sign-in is a separate identity service','IP-derived territory','approved 47 territories remain separate']:
            self.assertContains(response,fact)
        self.assertNotContains(response,'Account-specific acceptance and regional safeguards are being verified')
        terms=legal.terms(self.request('/en/terms/'),'en')
        self.assertContains(terms,'readers of any age')
        self.assertContains(terms,'do not establish a consent exemption or change the reading-age policy')

    def test_contact_channel_truthfully_tracks_disabled_and_enabled_form(self):
        with override_settings(SUPPORT_EMAIL=''):
            response=legal.contact(self.request('/en/contact/'),'en')
            self.assertContains(response,'The contact form is unavailable. Please use the email address above')
            self.assertContains(response,'support, privacy, grievance or incident requests')
            self.assertNotContains(response,'id="support-island"')
        with override_settings(SUPPORT_EMAIL='sales@reoenterprise.org'):
            response=legal.contact(self.request('/en/contact/'),'en')
            self.assertContains(response,'id="support-island"')
            self.assertNotContains(response,'The contact form is unavailable. Please use the email address above')


    def test_customer_notices_name_the_app_and_operator_without_internal_deployment_brand(self):
        for view in [legal.privacy,legal.terms,legal.contact]:
            response=view(self.request('/en/privacy/'),'en')
            main=response.content.decode().split('<main',1)[1].split('</main>',1)[0]
            self.assertIn('Earnalism',main)
            self.assertIn('Reo Enterprise',main)
            self.assertNotIn('Maison',main)
            self.assertNotIn('all testers are physically in India',main)
        response=legal.privacy(self.request('/en/privacy/'),'en')
        self.assertContains(response,'approved 47 territories remain separate')
