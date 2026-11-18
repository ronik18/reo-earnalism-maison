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
            self.assertContains(response,'Qualification draft')
            self.assertContains(response,'Reo Enterprise')
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
