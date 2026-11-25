"""Pass page: founding-member wording only while both founding offers are open; sourced anchors; one-step cancel."""
import re
from types import SimpleNamespace
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, RequestFactory, override_settings
from billing import founding
from billing.models import Offer
from billing.subscription_models import BillingPlan
from .views import pass_page

WORDING = 'INR 99/month or INR 999/year — your price stays the same for as long as you stay a member.'
BN_WORDING = '৯৯ টাকা মাসে অথবা ৯৯৯ টাকা বছরে'


class PassPageFoundingTests(TestCase):
    def render(self, locale='en', user=None):
        request = RequestFactory().get(f'/{locale}/pass/')
        request.user = user or AnonymousUser()
        request.territory = 'IN'
        request.resolver_match = SimpleNamespace(url_name='pass')
        return pass_page(request, locale).content.decode()

    def open_founding(self):
        staff = get_user_model().objects.create_user('staff-pass@example.test', 'Local-Fixture-Password-47', is_staff=True, is_verified=True)
        founding.ensure_founding_plans(staff)
        Offer.objects.filter(code__in=['founding-pass-month', 'founding-pass-year']).update(approved=True, active=True)

    def test_founding_price_and_lifetime_wording_shown_only_when_open(self):
        closed = self.render().split('<main', 1)[1].split('</main>', 1)[0]
        self.assertNotIn('ounding', closed)
        self.assertNotIn('INR 99/month', closed)
        staff = get_user_model().objects.create_user('staff-pass@example.test', 'Local-Fixture-Password-47', is_staff=True, is_verified=True)
        founding.ensure_founding_plans(staff)
        self.assertNotIn(WORDING, self.render().split('<main', 1)[1].split('</main>', 1)[0])  # created but inactive
        Offer.objects.filter(code='founding-pass-month').update(approved=True, active=True)
        self.assertNotIn(WORDING, self.render().split('<main', 1)[1].split('</main>', 1)[0])  # only one open
        Offer.objects.filter(code='founding-pass-year').update(approved=True, active=True)
        self.assertIn('Founding member: ' + WORDING, self.render().split('<main', 1)[1].split('</main>', 1)[0])

    def test_bengali_wording_exists_in_catalogue(self):
        from .i18n import STRINGS
        self.assertIn(BN_WORDING, STRINGS['founding_offer'][1])

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
        html = self.render().lower().split('<main', 1)[1].split('</main>', 1)[0]
        for word in ('countdown', 'hurry', 'limited time', 'only a few', 'spots left', 'ends in', 'checked', 'checkbox'):
            self.assertNotIn(word, html)
