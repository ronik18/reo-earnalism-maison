"""Pass page: founding-member wording only while both founding offers are open; sourced anchors; one-step cancel."""
import re
from types import SimpleNamespace
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, RequestFactory, override_settings
from django.utils import timezone
from billing import founding
from billing.models import Offer
from billing.subscription_models import BillingPlan
from .views import pass_page

WORDING = 'INR 99/month or INR 999/year — your price stays the same for as long as you stay a member.'
BN_WORDING = '{month} টাকা মাসে অথবা {year} টাকা বছরে'


class PassPageFoundingTests(TestCase):
    def render(self, locale='en', user=None):
        request = RequestFactory().get(f'/{locale}/pass/')
        request.user = user or AnonymousUser()
        request.territory = 'IN'
        request.resolver_match = SimpleNamespace(url_name='pass')
        return pass_page(request, locale).content.decode()

    def main(self, locale='en', user=None):
        return self.render(locale, user).split('id="main"', 1)[1].split('</main>', 1)[0]

    def open_founding(self):
        staff = get_user_model().objects.create_user('staff-pass@example.test', 'Local-Fixture-Password-47', is_staff=True, is_verified=True)
        founding.ensure_founding_plans(staff)
        Offer.objects.filter(code__in=['founding-pass-month', 'founding-pass-year']).update(approved=True, active=True, test_only=False)
        BillingPlan.objects.update(merchant_approved_at=timezone.now())

    def test_founding_price_and_lifetime_wording_shown_only_when_open(self):
        closed = self.main()
        self.assertNotIn('ounding', closed)
        self.assertNotIn('INR 99/month', closed)
        staff = get_user_model().objects.create_user('staff-pass@example.test', 'Local-Fixture-Password-47', is_staff=True, is_verified=True)
        founding.ensure_founding_plans(staff)
        self.assertNotIn(WORDING, self.main())  # created but inactive
        Offer.objects.filter(code='founding-pass-month').update(approved=True, active=True)
        self.assertNotIn(WORDING, self.main())  # only one open
        Offer.objects.filter(code='founding-pass-year').update(approved=True, active=True)
        self.assertNotIn(WORDING, self.main())  # merchant approval still missing
        BillingPlan.objects.update(merchant_approved_at=timezone.now())
        self.assertNotIn(WORDING, self.main())  # still test-only offers: not purchasable in production
        Offer.objects.update(test_only=False)
        self.assertIn('Founding member: ' + WORDING, self.main())

    def test_bengali_wording_exists_in_catalogue(self):
        from .i18n import STRINGS
        self.assertIn(BN_WORDING, STRINGS['founding_offer'][1])
        for wording in STRINGS['founding_offer']:  # prices come from the offers, never hard-coded copy
            self.assertNotIn('99', wording)
            self.assertNotIn('৯৯', wording)

    def test_founding_wording_reads_the_offer_prices(self):
        self.open_founding()
        Offer.objects.filter(code='founding-pass-month').update(price_minor=12950)
        Offer.objects.filter(code='founding-pass-year').update(price_minor=129900)
        html = self.main()
        self.assertIn('Founding member: INR 129.50/month or INR 1299/year', html)
        self.assertNotIn('INR 99/month', html)
        self.assertIn('INR 129.50/month or INR 1299/year', self.main('bn'))  # English-only UI (owner decision)

    def test_non_inr_founding_offer_hides_the_wording(self):
        self.open_founding()
        Offer.objects.filter(code='founding-pass-year').update(currency='USD')
        self.assertNotIn('Founding member', self.main())

    def test_every_anchor_has_a_source_link(self):
        self.open_founding()
        html = self.render()
        for name, price, url in (('Storytel', '149', 'https://www.storytel.com/in'),
                                 ('Kuku FM', '899', 'https://inc42.com/buzz/after-2-5-mn-paid-subscribers-kuku-fm-25-mn-fuel-expansion/'),
                                 ('SpeakX', '300', 'https://www.magzter.com/de/stories/newspaper/Mint-Ahmedabad/STARTUPS-HELP-SMALLTOWN-INDIA-BREAK-BIGCITY-ENGLISH-BARRIER')):
            self.assertIn(name, html)
            self.assertRegex(html, rf'href="{re.escape(url)}"[^>]*rel="noopener"')
            self.assertIn(price, html)
        self.assertNotIn('_blank', html)

    def test_cancel_link_is_one_step_from_account(self):
        self.open_founding()
        user = get_user_model().objects.create_user('member-pass@example.test', 'Local-Fixture-Password-47', is_verified=True)
        self.assertIn('href="/en/settings/"', self.render(user=user))

    def test_no_countdown_or_preticked_box(self):
        self.open_founding()
        html = self.main().lower()
        for word in ('countdown', 'hurry', 'limited time', 'only a few', 'spots left', 'ends in', 'checkbox'):
            self.assertNotIn(word, html)
        self.assertNotRegex(html, r'<input[^>]*\bchecked\b')

    def test_unapproved_merchant_keeps_founding_closed(self):
        self.open_founding()
        BillingPlan.objects.filter(offer__code='founding-pass-year').update(merchant_approved_at=None)
        self.assertNotIn('Founding member', self.main())
        BillingPlan.objects.update(merchant_approved_at=timezone.now())
        self.assertIn('Founding member', self.main())

    def test_founding_price_hidden_while_free_access_is_on(self):
        self.open_founding()
        with override_settings(FREE_ACCESS_ENABLED=True):
            self.assertNotIn('INR 99/month', self.main())
        with override_settings(FREE_ACCESS_ENABLED=False):
            self.assertIn('INR 99/month', self.main())
