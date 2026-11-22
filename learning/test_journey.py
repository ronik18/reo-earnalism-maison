"""Learning discovery stays bounded as paid tracks grow (LLD section 8)."""
import tempfile

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from reader.test_journey import make_book
from .models import Track
from . import services


@override_settings(LOCAL=True, MAISON_LOCAL_FIXTURES=True)
class TrackListCostTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        override = override_settings(MEDIA_ROOT=directory.name); override.enable(); self.addCleanup(override.disable)
        self.user = get_user_model().objects.create_user('tracks@example.test', 'Original-Track-Cost-47', is_verified=True)
        self.user.request_territory = 'IN'

    def paid_track(self, n):
        edition, _ = make_book(units=1, title=f'Track book {n}')
        return Track.objects.create(title=f'Paid track {n}', locale='en', description='Original fixture', access='paid',
                                    edition=edition, published=True)

    def page(self):
        request = RequestFactory().get('/api/v1/learning/tracks'); request.user = self.user; request.territory = 'IN'
        with CaptureQueriesContext(connection) as measured:
            result = services.tracks_page(request, self.user)
        return result, len(measured)

    def test_paid_track_listing_does_not_requery_each_track(self):
        self.paid_track(0)
        one, small = self.page()
        for n in range(1, 6): self.paid_track(n)
        many, large = self.page()
        self.assertEqual([t['access'] for t in many['items']], ['included']*6)
        self.assertEqual(one['items'][0]['access'], 'included')
        self.assertEqual(large, small, f'{small} queries for one paid track, {large} for six')
