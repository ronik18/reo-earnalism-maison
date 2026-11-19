"""Free-access presentation never bootstraps new payment actions."""
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
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
            self.assertIn(f'/{locale}/sign-up/',html)
            self.assertIn('not charged' if locale=='en' else 'নেওয়া হচ্ছে না',html)
            self.assertNotIn('id="commerce-island"',html);self.assertNotIn('id="commerce-bootstrap"',html)
            self.assertNotIn('checkout.razorpay.com',html)
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
