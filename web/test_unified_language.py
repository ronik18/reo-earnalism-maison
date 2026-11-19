"""Content language is a reader choice, never an account/UI restriction."""
import io
from tempfile import TemporaryDirectory
from django.test import TestCase,override_settings
from django.core.management import call_command
from django.contrib.auth import get_user_model
from accounts.models import Preferences

class UnifiedLibraryJourneyTests(TestCase):
 def setUp(self):
  self.media=TemporaryDirectory();self.addCleanup(self.media.cleanup)
  s=override_settings(LOCAL=True,MAISON_LOCAL_FIXTURES=True,MEDIA_STORAGE_BACKEND='local',MEDIA_ROOT=self.media.name);s.enable();self.addCleanup(s.disable)
  call_command('seed_local_pilot',stdout=io.StringIO())
 def test_old_bengali_links_preserve_content_filters_tokens_and_post_bodies(self):
  r=self.client.get('/bn/search/?content_locale=bn&q=river');self.assertEqual(r.status_code,302);self.assertEqual(r['Location'],'/en/search/?content_locale=bn&q=river');self.assertIn('no-store',r['Cache-Control'])
  r=self.client.post('/bn/verify-email/exact-token/',{'confirmation':'yes'});self.assertEqual(r.status_code,307);self.assertEqual(r['Location'],'/en/verify-email/exact-token/')
 def test_every_reader_sees_both_book_languages_unless_explicitly_filtered(self):
  u=get_user_model().objects.create_user('language-reader@example.test','Original-language-password-47',is_verified=True);Preferences.objects.create(user=u,locale='bn');self.client.force_login(u)
  r=self.client.get('/en/explore/');self.assertEqual(r.status_code,200);self.assertEqual({c['locale'] for c in r.context['cards']},{'en','bn'});self.assertContains(r,'All languages');self.assertContains(r,'data-ui-locale="en"');self.assertNotContains(r,'aria-label="Interface language"')
  for code in ['bn','en']:
   r=self.client.get('/en/explore/',{'content_locale':code});self.assertEqual(r.status_code,200);self.assertEqual({c['locale'] for c in r.context['cards']},{code})
  r=self.client.get('/en/');self.assertEqual({c['locale'] for c in r.context['cards']},{'en','bn'})
 def test_old_bengali_signin_and_notices_use_same_english_journey(self):
  for route in ['sign-in','sign-up','privacy','terms','contact','settings','series']:
   r=self.client.get('/bn/'+route+'/',follow=True);self.assertEqual(r.status_code,200);self.assertEqual(r['Content-Language'],'en');self.assertContains(r,'data-ui-locale="en"');self.assertNotContains(r,'aria-label="Interface language"')

 def test_service_worker_precaches_only_the_shared_english_shell(self):
  response=self.client.get('/maison-sw.js');self.assertEqual(response.status_code,200)
  source=response.content.decode();self.assertIn('/en/offline/',source);self.assertNotIn('/bn/offline/',source)
