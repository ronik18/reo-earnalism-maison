"""The current notice is discoverable at collection without optional consent."""
from django.conf import settings
from django.test import TestCase
from accounts.models import Consent
from accounts.services import register_member

class NoticeAtCollectionTests(TestCase):
 def test_signup_discloses_both_notices_before_collection_in_both_languages(self):
  for locale in ['en','bn']:
   html=self.client.get(f'/{locale}/sign-up/').content.decode()
   self.assertIn('data-account-notice',html)
   self.assertIn(f'href="/{locale}/privacy/"',html);self.assertIn(f'href="/{locale}/terms/"',html)
   self.assertLess(html.index('data-account-notice'),html.index('name="email"'))
 def test_new_registration_records_current_notice_without_marketing_or_rewriting_existing_choice(self):
  register_member('current-notice-original@example.test','Original-Notice-Collection-47')
  c=Consent.objects.get(user__email='current-notice-original@example.test')
  self.assertEqual(c.necessary_notice_version,settings.PRIVACY_NOTICE_VERSION)
  self.assertFalse(c.analytics_opt_in);self.assertFalse(c.marketing_email_opt_in)
  c.necessary_notice_version='historic-preserved';c.save()
  register_member('current-notice-original@example.test','Original-Notice-Collection-47')
  c.refresh_from_db();self.assertEqual(c.necessary_notice_version,'historic-preserved')
