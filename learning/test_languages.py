"""Content-language filtering is optional and independent of the English UI."""
from django.contrib.auth import get_user_model
from django.test import TestCase,RequestFactory,override_settings
from core.api import DomainError
from .models import Track
from . import services

@override_settings(LOCAL=True,FREE_ACCESS_ENABLED=True)
class TrackLanguageTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('original-all-languages@example.test','Original-Language-Fixture-47',is_verified=True)
        self.user.request_territory='IN';self.factory=RequestFactory()
        self.rows={locale:Track.objects.create(title=title,locale=locale,kind='learning',description='Original synthetic multilingual track',access='free',published=True) for locale,title in [('en','A English'),('bn','B বাংলা'),('fr','C Future published language')]}
        Track.objects.create(title='Private draft',locale='bn',kind='learning',description='Original draft',access='free',published=False)
        Track.objects.create(title='Not offered',locale='en',kind='learning',description='Original denied',access='deny',published=True)

    def request(self,**query):
        request=self.factory.get('/api/v1/learning/tracks',query);request.user=self.user;request.territory='IN';return request

    def test_default_lists_all_published_languages_and_explicit_filter_is_optional(self):
        self.assertEqual({row['locale'] for row in services.list_tracks(self.user)},{'en','bn','fr'})
        for value in [None,'','all']:
            self.assertEqual({row['locale'] for row in services.list_tracks(self.user,value)},{'en','bn','fr'})
        for value in ['en','bn','fr']:
            self.assertEqual([row['track_id'] for row in services.list_tracks(self.user,value)],[str(self.rows[value].pk)])
        self.assertEqual(services.list_tracks(self.user,'hi'),[])
        for value in ['EN','en-US','../../../',12,[],{}]:
            with self.subTest(locale=value),self.assertRaises(DomainError) as error:services.list_tracks(self.user,value)
            self.assertEqual(error.exception.code,'invalid_filter')

    def test_all_language_keyset_spans_languages_and_binds_explicit_filter(self):
        first=services.tracks_page(self.request(limit=2),self.user)
        second=services.tracks_page(self.request(limit=2,cursor=first['next_cursor']),self.user)
        self.assertEqual([row['locale'] for row in first['items']+second['items']],['en','bn','fr'])
        self.assertFalse(second['has_more'])
        with self.assertRaises(DomainError) as error:services.tracks_page(self.request(limit=2,cursor=first['next_cursor']),self.user,'en')
        self.assertEqual(error.exception.code,'invalid_cursor')
        self.user.request_territory='AE'
        self.assertEqual(services.tracks_page(self.request(),self.user)['items'],[])

    def test_http_default_and_explicit_language_preserve_page_shape(self):
        response=self.client.get('/api/v1/learning/tracks',{'limit':10})
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(set(response.json()),{'items','next_cursor','has_more'})
        self.assertEqual({row['locale'] for row in response.json()['items']},{'en','bn','fr'})
        response=self.client.get('/api/v1/learning/tracks',{'locale':'bn','limit':10})
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual([row['locale'] for row in response.json()['items']],['bn'])
        response=self.client.get('/api/v1/learning/tracks',{'locale':'fr','limit':10})
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual([row['locale'] for row in response.json()['items']],['fr'])
