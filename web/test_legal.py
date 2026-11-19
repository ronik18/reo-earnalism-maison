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
        self.assertContains(response,'গোপনীয়তার বিজ্ঞপ্তি')
        with self.assertRaises(Http404):legal.privacy(self.request('/xx/privacy/'),'xx')
    def test_notices_cannot_submit_mutations(self):
        self.assertEqual(legal.privacy(self.request('/en/privacy/','post'),'en').status_code,405)

    def test_integrated_routes_and_footer_discovery(self):
        for locale in ["en","bn"]:
            for route in ["privacy","terms","contact"]:
                response=self.client.get(f"/{locale}/{route}/")
                self.assertEqual(response.status_code,200)
                self.assertContains(response,f'href="/{locale}/privacy/"')
                self.assertContains(response,f'href="/{locale}/terms/"')
                self.assertContains(response,f'href="/{locale}/contact/"')
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
        self.assertContains(response,'Applicable regional operating and age-appropriate requirements remain under review')

    def test_bengali_notice_discloses_matching_windows_and_provider_scope(self):
        response=legal.privacy(self.request('/bn/privacy/'),'bn')
        for fact in ['২০ নভেম্বর ২০২৬','৩৫ দিন','৯০ দিন','৩০ দিন','১২টি ক্যালেন্ডার-মাস','Google','Stream','সিঙ্গাপুর','আইনি বা সংরক্ষণের বাধা','আন্তর্জাতিকভাবে']:
            self.assertContains(response,fact)
        self.assertNotContains(response,'সম্পূর্ণ সংরক্ষণের সময়সূচি ও প্রযোজ্য অনুরোধের সময়সীমা নিশ্চিত করা বাকি')

    @override_settings(FREE_ACCESS_ENABLED=True)
    def test_free_terms_preserve_reading_audience_and_no_future_payment_commitment(self):
        response=legal.terms(self.request('/en/terms/'),'en')
        self.assertContains(response,'No payment details or automatic subscription are required')
        self.assertContains(response,'Any future paid plan requires a separate explicit choice')
        self.assertContains(response,'readers of any age')
        self.assertContains(response,'New paid purchases are disabled during free access')
        self.assertNotContains(response,'Payments, audio/video and offline access remain unavailable')
