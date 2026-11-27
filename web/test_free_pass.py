"""Free-access presentation never bootstraps new payment actions."""
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlencode, quote, parse_qs, urlsplit
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from django.test import SimpleTestCase,TestCase,RequestFactory,override_settings
from django.utils import timezone
from .views import pass_page,checkout
from . import legal

@override_settings(FREE_ACCESS_ENABLED=True)
class FreePassPresentationTests(SimpleTestCase):
    def request(self,path,territory='IN'):
        request=RequestFactory().get(path);request.user=AnonymousUser();request.territory=territory
        request.resolver_match=SimpleNamespace(url_name='pass')
        return request
    def test_bilingual_free_page_labels_references_and_has_no_payment_island(self):
        for locale in ('en','bn'):
            html=pass_page(self.request(f'/{locale}/pass/'),locale).content.decode()
            self.assertIn('<s>₹99</s>',html);self.assertIn('<s>₹999</s>',html)
            self.assertIn('/en/sign-up/',html)
            self.assertIn('not charged',html)
            self.assertNotIn('id="commerce-island"',html);self.assertNotIn('id="commerce-bootstrap"',html)
            self.assertNotIn('checkout.razorpay.com',html)
    def test_free_signin_and_signup_preserve_safe_reader_destination(self):
        destination='/en/read/20000000-0000-4000-8000-000000000001/?anchor=sample&offset=3'
        for locale in ('en','bn'):
            html=pass_page(self.request(f'/{locale}/pass/?'+urlencode({'return_to':destination})),locale).content.decode()
            encoded=quote(destination,safe='/')
            self.assertIn(f'/en/sign-in/?return_to={encoded}',html)
            self.assertIn(f'/en/sign-up/?return_to={encoded}',html)
        html=pass_page(self.request('/bn/pass/?return_to=https://foreign.invalid/'),'bn').content.decode()
        self.assertNotIn('href="https://foreign.invalid/',html)
        self.assertIn('/en/sign-in/?return_to=/en/',html)

    def test_excluded_or_untrusted_territory_gets_no_free_offer_or_price(self):
        for territory in ('AE','CN','ZZ'):
            html=pass_page(self.request('/en/pass/',territory),'en').content.decode()
            self.assertIn('Access is not available in this region.',html)
            self.assertNotIn('<s>₹',html);self.assertNotIn('Create a free account',html.split('<main',1)[1].split('</main>',1)[0])
    def test_free_terms_describe_scope_and_no_automatic_subscription(self):
        html=legal.terms(self.request('/en/terms/'),'en').content.decode()
        self.assertIn('planned reference prices, not previous selling prices',html)
        self.assertIn('free access alone does not cancel an existing agreement',html)
    @override_settings(FREE_ACCESS_ENABLED=False)
    def test_flag_off_keeps_existing_qualified_commerce_bootstrap(self):
        html=pass_page(self.request('/en/pass/'),'en').content.decode()
        self.assertIn('id="commerce-island"',html);self.assertIn('id="commerce-bootstrap"',html)
        self.assertNotIn('<s>₹99</s>',html)

@override_settings(FREE_ACCESS_ENABLED=True)
class HistoricalCheckoutFreePresentationTests(TestCase):
    def test_owner_can_review_existing_order_while_payments_are_disabled(self):
        from billing.models import Offer,Order
        user=get_user_model().objects.create_user('free-checkout-owner@example.test','Local-Free-Pass-2026',is_verified=True)
        offer=Offer.objects.create(code='free-presentation-history',name='Original historical fixture',price_minor=100,duration_seconds=86400,formats=['reader'])
        order=Order.objects.create(user=user,offer=offer,total_minor=100,currency='INR',offer_snapshot={},operation_id=uuid.uuid4(),request_sha256='f'*64,expires_at=timezone.now()+timedelta(hours=1))
        request=RequestFactory().get(f'/en/checkout/{order.id}/');request.user=user;request.territory='IN';request.resolver_match=SimpleNamespace(url_name='checkout')
        html=checkout(request,locale='en',order_id=order.id).content.decode()
        self.assertIn('Review your existing order.',html);self.assertIn('Access follows regional availability.',html)
        self.assertIn('"free_access": true',html);self.assertIn(str(order.id),html)
        self.assertIn('/en/settings/',html);self.assertIn('id="commerce-island"',html)
        other=get_user_model().objects.create_user('free-checkout-other@example.test','Local-Free-Pass-2026',is_verified=True)
        request.user=other
        with self.assertRaises(Http404):checkout(request,locale='en',order_id=order.id)


import io
import tempfile
from unittest.mock import patch
from django.conf import settings
from django.core.management import call_command
from django.urls import reverse
from library import services as library_services


@override_settings(FREE_ACCESS_ENABLED=True,MAISON_LOCAL_FIXTURES=True)
class PreviewEndingTests(TestCase):
    """The signed-out preview ends with a free sign-in that keeps the reader's place."""
    edition='20000000-0000-4000-8000-000000000001'
    unit='40000000-0000-4000-8000-000000000001'
    @classmethod
    def setUpClass(cls):
        cls.media=tempfile.TemporaryDirectory(prefix='maison-preview-end-')
        cls.media_override=override_settings(MEDIA_ROOT=cls.media.name,MAISON_LOCAL_FIXTURES=True);cls.media_override.enable()
        super().setUpClass()
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass();cls.media_override.disable();cls.media.cleanup()
    @classmethod
    def setUpTestData(cls):
        call_command('seed_local_pilot',stdout=io.StringIO())
    def page(self,formats=None,features=None):
        real=library_services.edition_detail
        def detail(*args,**kwargs):
            data=real(*args,**kwargs)
            if formats is not None: data={**data,'formats':list(formats)}
            return data
        with patch('library.services.edition_detail',detail),override_settings(FEATURES={**settings.FEATURES,**(features or {'audio':True,'video':True})}):
            return self.client.get(f'/en/read/{self.edition}/{self.unit}/')
    def boot(self,response):
        html=response.content.decode()
        return json.loads(html.split('id="reader-bootstrap" type="application/json">',1)[1].split('</script>',1)[0])
    def test_preview_end_copy_exact(self):
        response=self.page()
        boot=self.boot(response)
        title=boot['edition_title']
        self.assertEqual(title,'The River Notebook')
        html=response.content.decode()
        fallback=html.split('data-preview-fallback',1)[1].split('</section>',1)[0].split('</article>',1)[0]
        self.assertIn(f'Sign in free to finish <span lang="{boot["content_locale"]}">{title}</span> — your place is kept',fallback)
        self.assertIn('Sign in free',fallback)
        self.assertNotRegex(fallback.lower(),r'price|trial|pay|₹')
    def test_preview_end_shows_remaining_minutes(self):
        from library.models import Paragraph
        boot=self.boot(self.page())
        total=sum(len(p.text) for p in Paragraph.objects.filter(unit__revision_id=boot['edition_revision_id']))
        self.assertIsInstance(boot['remaining_minutes'],int)
        self.assertGreaterEqual(boot['remaining_minutes'],1)
        self.assertLessEqual(boot['remaining_minutes']*900,total+900)
        self.assertIn(f'{boot["remaining_minutes"]} minutes left to read',self.page().content.decode().split('data-preview-fallback',1)[1].split('</section>',1)[0])
    def test_preview_end_omits_minutes_without_an_estimate(self):
        with patch('web.views.remaining_read_minutes',return_value=None):
            response=self.page()
        self.assertIsNone(self.boot(response)['remaining_minutes'])
        self.assertNotIn('minutes left to read',response.content.decode().split('data-preview-fallback',1)[1].split('</section>',1)[0])
    def test_preview_end_offers_listen_and_watch_when_available(self):
        both=self.page(formats=['reader','audio','video'])
        boot=self.boot(both);html=both.content.decode().split('data-preview-fallback',1)[1].split('</section>',1)[0]
        self.assertEqual(boot['formats'],{'listen':True,'watch':True})
        self.assertIn('Sign in free to listen',html);self.assertIn('Sign in free to watch',html)
        self.assertIn(quote(reverse('web:player',args=['en',self.edition]),safe=''),html)
        self.assertIn(quote(reverse('web:video',args=['en',self.edition]),safe=''),html)
        only=self.page(formats=['reader'])
        self.assertEqual(self.boot(only)['formats'],{'listen':False,'watch':False})
        self.assertNotIn('to listen',only.content.decode().split('data-preview-fallback',1)[1].split('</section>',1)[0])
        flagged=self.page(formats=['reader','audio','video'],features={'audio':False,'video':False})
        self.assertEqual(self.boot(flagged)['formats'],{'listen':False,'watch':False})
    def test_sign_in_returns_to_boundary_anchor(self):
        boot=self.boot(self.page(formats=['reader','audio','video']))
        query=parse_qs(urlsplit(boot['sign_in_url']).query)
        self.assertEqual(urlsplit(boot['sign_in_url']).path,'/en/sign-in/')
        target=urlsplit(query['return_to'][0])
        self.assertEqual(target.path,f'/en/read/{self.edition}/{self.unit}/')
        self.assertIn('anchor',parse_qs(target.query));self.assertIn('offset',parse_qs(target.query))
        sign_in=self.client.get(boot['sign_in_url']).content.decode()
        self.assertIn('"return_path": "'+query['return_to'][0].replace('&','\\u0026')+'"',sign_in)
        sign_up=self.client.get('/en/sign-up/?'+urlencode({'return_to':query['return_to'][0]})).content.decode()
        self.assertIn('"return_path": "'+query['return_to'][0].replace('&','\\u0026')+'"',sign_up)
        for field in ('listen_sign_in_url','watch_sign_in_url'):
            self.assertIn('return_to',boot[field])
    def test_external_return_to_is_still_rejected(self):
        from .views import safe_return
        for hostile in ('https://evil.invalid/x','//evil.invalid/x','/\\evil.invalid','/en/sign-in/?return_to=/en/','javascript:alert(1)'):
            self.assertEqual(safe_return(hostile,'en'),'/en/')
        page=self.client.get('/en/sign-in/?return_to='+quote('https://evil.invalid/x',safe='')).content.decode()
        self.assertNotIn('evil.invalid',page)
