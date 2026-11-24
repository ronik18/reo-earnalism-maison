"""Member reading journey: correctness and bounded query cost.

Covers the 2026-11-21 review findings for grants, Reader units, progress,
Vault and personal saves. Budgets follow LLD section 8.
"""
import io
import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import User
from core.api import DomainError
from library import services as library
from library.models import Asset, Edition, Paragraph, Revision, Rights, Unit, Work
from library.services import prepare_reader_package
from .models import Completion, PersonalList, Progress
from . import services

PASS = 'Local-Journey-Passphrase-47'
EN = '20000000-0000-4000-8000-000000000001'


def make_book(units=3, paragraphs=2, durations=None, title='Journey book', edition=None, policy=None):
    """A live free edition with ready Reader packages (and audio when durations given).

    Passing an existing edition publishes a new correction revision and retires the old one.
    """
    if edition is None:
        key = uuid.uuid4().hex
        work = Work.objects.create(slug='journey-'+key, title=title, house='golpo', creators=['A writer'])
        edition = Edition.objects.create(work=work, slug='journey-'+key, locale='en')
    elif edition.live_revision_id:
        Revision.objects.filter(pk=edition.live_revision_id).update(state='retired')
    policy = policy or {'reader': 'free', **({'audio': 'free'} if durations else {})}
    revision = Revision.objects.create(edition=edition, title=title, access_policy=policy)
    for n in range(units):
        unit = Unit.objects.create(revision=revision, ordinal=n+1, title=f'Chapter {n+1}',
                                   duration_ms=durations[n] if durations else None)
        rows = [Paragraph.objects.create(unit=unit, ordinal=p+1, text=f'Unit {n+1} paragraph {p+1} has some text.')
                for p in range(paragraphs)]
        prepare_reader_package(unit, rows).save()
        if durations:
            Asset.objects.create(revision=revision, unit=unit, kind='audio_chapter', state='ready',
                                 storage_key=f'revisions/{revision.pk}/{uuid.uuid4()}', sha256='a'*64,
                                 bytes=10, content_type='audio/mpeg', duration_ms=durations[n])
    now = timezone.now()
    for fmt in policy:
        Rights.objects.create(revision=revision, format=fmt, action='read', territories=['IN'],
                              starts_at=now-timedelta(days=1), ends_at=now+timedelta(days=30), approved=True)
    revision.state = 'live'; revision.published_at = now; revision.save()
    edition.live_revision = revision; edition.save()
    return edition, revision


class JourneyFixture:
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        override = override_settings(MEDIA_ROOT=directory.name, MAISON_LOCAL_FIXTURES=True, LOCAL=True,
                                     PUBLIC_BASE_URL='https://example.test')
        override.enable(); self.addCleanup(override.disable)
        call_command('seed_local_pilot', stdout=io.StringIO())
        self.user = User.objects.create_user('journey@example.test', PASS, is_verified=True)
        response = self.client.post('/api/v1/auth/login', {'email': self.user.email, 'password': PASS,
            'password_purpose_consent': True, 'password_purpose_version': 'password-account-v1'}, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.device = response.json()['device_id']

    def progress(self, edition, revision, location):
        return services.set_progress(self.user, edition.pk, location['format'], {
            'operation_id': str(uuid.uuid4()), 'edition_revision_id': str(revision.pk), 'location': location,
            'occurred_at': timezone.now().isoformat()}, 0)

    def reader_location(self, revision, unit_ordinal=1, offset=0):
        unit = revision.units.get(ordinal=unit_ordinal); paragraph = unit.paragraphs.first()
        return {'format': 'reader', 'unit_id': str(unit.pk), 'anchor_id': str(paragraph.anchor_id), 'offset_chars': offset}


class GrantAndReaderCostTests(JourneyFixture, TestCase):
    def grant(self, revision, units):
        return library.package_grant(self.user, {'edition_revision_id': str(revision.pk), 'unit_ids': [str(u.pk) for u in units],
                                                 'device_id': self.device, 'purpose': 'online'})

    def test_package_grant_query_count_does_not_grow_with_assets(self):
        _, revision = make_book(units=10)
        units = list(revision.units.all())
        with CaptureQueriesContext(connection) as one:
            self.grant(revision, units[:1])
        with CaptureQueriesContext(connection) as ten:
            body = self.grant(revision, units)
        self.assertEqual(len(body['assets']), 10)
        self.assertEqual(len(ten), len(one), [q['sql'] for q in ten])

    def test_reader_unit_open_stays_within_content_budget(self):
        edition, revision = make_book(units=3)
        unit = revision.units.get(ordinal=2)
        with CaptureQueriesContext(connection) as measured:
            document = library.get_reader_document(self.user, edition.pk, unit.pk)
        self.assertEqual(document['unit']['formats'], ['reader'])
        self.assertEqual(len(document['paragraphs']), 2)
        self.assertLessEqual(len(measured), 8, [q['sql'] for q in measured])


class ProgressFractionTests(JourneyFixture, TestCase):
    def test_reader_fraction_is_book_wide_and_does_not_rescan_text(self):
        edition, revision = make_book(units=2, paragraphs=1)
        unit_one = revision.units.get(ordinal=1).paragraphs.get().text
        total = len(unit_one) + len(revision.units.get(ordinal=2).paragraphs.get().text)
        status, body = self.progress(edition, revision, self.reader_location(revision, 2, 0))
        self.assertEqual(status, 200)
        self.assertAlmostEqual(body['fraction_complete'], len(unit_one)/total, places=4)
        with CaptureQueriesContext(connection) as again:
            services.set_progress(self.user, edition.pk, 'reader', {'operation_id': str(uuid.uuid4()),
                'edition_revision_id': str(revision.pk), 'location': self.reader_location(revision, 2, 2),
                'occurred_at': timezone.now().isoformat()}, 1)
        self.assertFalse([q for q in again if 'LENGTH' in q['sql'].upper()], 'progress write rescanned book text')

    def test_audio_fraction_counts_previous_chapters(self):
        edition, revision = make_book(units=4, durations=[60000, 60000, 60000, 60000])
        second = revision.units.get(ordinal=2)
        with self.settings(FEATURES={**__import__('django.conf').conf.settings.FEATURES, 'audio': True}):
            status, body = self.progress(edition, revision, {'format': 'audio', 'unit_id': str(second.pk), 'position_ms': 30000})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(body['fraction_complete'], 90000/240000, places=4)


class VaultJourneyTests(JourneyFixture, TestCase):
    def vault(self):
        request = RequestFactory().get('/api/v1/me/vault'); request.user = self.user
        return services.vault_data(self.user, 'IN', request)

    def test_vault_summary_query_count_does_not_grow_with_shelf_size(self):
        def fill(count):
            for n in range(count):
                edition, revision = make_book(units=1, title=f'Shelf {count}-{n}')
                self.progress(edition, revision, self.reader_location(revision))
                done, _ = make_book(units=1, title=f'Done {count}-{n}')
                Completion.objects.create(user=self.user, edition=done, revision=done.live_revision, format='reader',
                                          is_complete=True, completed_at=timezone.now())
                services.create_list(self.user, f'List {count}-{n}', uuid.uuid4())
        fill(1)
        with CaptureQueriesContext(connection) as small:
            first = self.vault()
        fill(6)
        with CaptureQueriesContext(connection) as large:
            second = self.vault()
        self.assertEqual((len(first['continue']), len(second['continue'])), (1, 7))
        self.assertEqual(len(second['finished']), 7)
        self.assertEqual(sorted(x['item_count'] for x in second['lists']), [0]*7)
        self.assertEqual(len(large), len(small), [q['sql'] for q in large])
        self.assertLessEqual(len(large), 12, [q['sql'] for q in large])

    def test_continue_keeps_a_book_after_a_correction_and_resumes_at_chapter_start(self):
        edition, old = make_book(units=2, title='Corrected later')
        self.progress(edition, old, self.reader_location(old, 2, 3))
        _, new = make_book(units=2, title='Corrected later', edition=edition)
        entries = [x for x in self.vault()['continue'] if x['card']['edition_id'] == str(edition.pk)]
        self.assertEqual(len(entries), 1)
        progress = entries[0]['progress']
        chapter = new.units.get(ordinal=2)
        self.assertEqual(progress['edition_revision_id'], str(new.pk))
        self.assertEqual(progress['location'], {'format': 'reader', 'unit_id': str(chapter.pk),
                                                'anchor_id': str(chapter.paragraphs.first().anchor_id), 'offset_chars': 0})
        self.assertEqual(Progress.objects.get(edition=edition).revision_id, old.pk)


class PersonalSaveTests(JourneyFixture, TestCase):
    def draft_edition(self):
        work = Work.objects.create(slug='draft-'+uuid.uuid4().hex, title='Unreleased', house='golpo', creators=['A writer'])
        edition = Edition.objects.create(work=work, slug=work.slug, locale='en')
        Revision.objects.create(edition=edition, title='Unreleased', access_policy={'reader': 'free'})
        return edition

    def test_saving_an_unpublished_edition_is_not_found(self):
        with self.assertRaises(DomainError) as error:
            services.saved_set(self.user, self.draft_edition().pk, True, uuid.uuid4())
        self.assertEqual(error.exception.status, 404)

    def test_adding_an_unpublished_edition_to_a_list_is_not_found(self):
        _, created = services.create_list(self.user, 'Later', uuid.uuid4())
        row = PersonalList.objects.get(pk=created['list_id'])
        with self.assertRaises(DomainError) as error:
            services.mutate_list(self.user, row.pk, uuid.uuid4(), row.version, 'add', {'edition_id': str(self.draft_edition().pk)})
        self.assertEqual(error.exception.status, 404)

    def test_published_edition_can_still_be_saved(self):
        status, body = services.saved_set(self.user, EN, True, uuid.uuid4())
        self.assertEqual((status, body['available']), (200, True))
