"""Film progress is bounded by the ready film's own duration, never the unit's audio duration."""
import uuid
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from core.api import DomainError
from library.models import Unit
from library import test_film_delivery as film_tests
from . import services

FILM_MS = film_tests.FILM_MS


@override_settings(LOCAL=True, MAISON_LOCAL_FIXTURES=False, FREE_ACCESS_ENABLED=False,
                   FEATURES={'video': True}, VIDEO_PROVIDER='r2')
class FilmProgressTests(TestCase):
    film = film_tests.FilmDeliveryTests.film
    publish = film_tests.FilmDeliveryTests.publish
    entitle = film_tests.FilmDeliveryTests.entitle

    def setUp(self):
        film_tests.FilmDeliveryTests.setUp(self)

    def save(self, position_ms, unit=None):
        location = {'format': 'video', 'unit_id': str((unit or self.unit).pk), 'position_ms': position_ms}
        return services.set_progress(self.user, self.edition.pk, 'video', {
            'operation_id': str(uuid.uuid4()), 'edition_revision_id': str(self.revision.pk), 'location': location,
            'occurred_at': timezone.now().isoformat()}, self.version)

    def arrange(self, unit_duration_ms):
        Unit.objects.filter(pk=self.unit.pk).update(duration_ms=unit_duration_ms)
        self.film()
        self.publish()
        self.entitle()
        self.version = 0

    def test_video_progress_past_unit_duration_within_film_succeeds(self):
        self.arrange(60_000)  # audio narration is one minute; the film runs ninety
        status, body = self.save(3_000_000)
        self.assertEqual(status, 200)
        self.assertEqual(body['location']['position_ms'], 3_000_000)
        self.assertEqual(Decimal(str(body['fraction_complete'])).quantize(Decimal('0.0001')),
                         (Decimal(3_000_000) / Decimal(FILM_MS)).quantize(Decimal('0.0001')))

    def test_video_progress_with_unit_duration_none_succeeds(self):
        self.arrange(None)
        status, body = self.save(FILM_MS)
        self.assertEqual(status, 200)
        self.assertEqual(body['fraction_complete'], 1.0)

    def test_video_progress_past_film_duration_is_invalid(self):
        self.arrange(None)
        with self.assertRaises(DomainError) as refused:
            self.save(FILM_MS + 1)
        self.assertEqual((refused.exception.code, refused.exception.status), ('invalid_position', 422))

    def test_video_progress_on_unit_without_ready_film_is_invalid(self):
        other = Unit.objects.create(revision=self.revision, ordinal=2, title='No film', duration_ms=FILM_MS)
        self.arrange(None)
        with self.assertRaises(DomainError) as refused:
            self.save(1_000, unit=other)
        self.assertEqual(refused.exception.code, 'invalid_position')
