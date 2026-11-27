"""Watch at the reader's place (spec 2026-11-27 cinematic film §10.5): film timing maps and /content/switch-position
for video in both directions, audio <-> video through the text, and the access, draft and unmapped rules (PostgreSQL).

The film timing comes from library/fixtures/film/synthetic-film.timing.json, the exact shape the film bundle emits
(docs/interface-notes/2026-11-27-film-timing-map.md). Its placeholder anchors a0..01-a0..06 stand for paragraphs 1-6
of the seeded English fixture unit; the test rewrites them to that live unit's anchors as the skill would, and the
film importer path (read_film_timing -> anchor_map_by_ordinal -> film_timing_maps) maps them onto the clone.
"""
import hashlib
import io
import json
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from billing.models import Entitlement
from core.api import DomainError
from . import services as svc
from .film_timing import FilmTimingError, anchor_map_by_ordinal, film_timing_maps, read_film_timing
from .models import Asset, Edition, Rights, TimingMap
from .timing import mappings, switch_position

FIXTURE = Path(__file__).parent / 'fixtures' / 'film'
EDITION = '20000000-0000-4000-8000-000000000001'
FILM_MS = 8000
PARA_STARTS = [1000, 2100, 3200, 4300, 5400, 6500]  # film time of paragraphs 1-6 in the fixture
SENTENCE_STARTS = [1000, 1300, 1600]                 # paragraph 1's sentences in the fixture's sentence map


def placeholder(n):
    return f'a0000000-0000-4000-8000-{n:012d}'


@override_settings(LOCAL=True, MAISON_LOCAL_FIXTURES=True, MEDIA_STORAGE_BACKEND='local', VIDEO_PROVIDER='r2',
                   FREE_ACCESS_ENABLED=False, STAFF_MFA_REQUIRED=False,
                   FEATURES={**settings.FEATURES, 'audio': True, 'video': True})
class FilmSwitchTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        media = override_settings(MEDIA_ROOT=self.directory.name)
        media.enable()
        self.addCleanup(media.disable)
        call_command('seed_local_pilot', stdout=io.StringIO())
        self.user = get_user_model().objects.create_user('film-switch@example.test', 'Synthetic-Switch-Passphrase-47',
                                                         is_verified=True)
        self.edition = Edition.objects.get(pk=EDITION)
        self.live_source = self.edition.live_revision
        self.live_unit = self.live_source.units.get()

    # ------------------------------------------------------------------ staging (the film importer's path)
    def bundle_timing(self, **override):
        """The fixture as the skill would emit it for the live source: live unit, live anchors, live text hash."""
        doc = json.loads((FIXTURE / 'synthetic-film.timing.json').read_text())
        live = {placeholder(p.ordinal): str(p.anchor_id) for p in self.live_unit.paragraphs.all()}
        for row in doc['maps']:
            for seg in row['segments']:
                seg['anchor_id'] = live[seg['anchor_id']]
        doc.update(unit_id=str(self.live_unit.id), text_sha256=self.live_source.content_sha256, **override)
        return json.dumps(doc).encode()

    def stage(self, *, video='free', audio=True, film_map=True, stale_film_maps=0, publish=True):
        revision = svc.clone_revision(self.live_source.id)
        revision.access_policy = {'reader': 'free', 'audio': 'free' if audio else 'deny', 'video': video}
        revision.save()
        revision.rights.update(approved=True)
        now = timezone.now()
        for fmt in ('video',) + (('audio',) if audio else ()):
            Rights.objects.create(revision=revision, format=fmt, action='read', territories=['IN'],
                                  starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1), approved=True, test_only=True)
        Rights.objects.create(revision=revision, format='reader', action='read', territories=['GB'],
                              starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1), approved=True, test_only=True)
        unit = revision.units.get()
        self.paragraphs = list(unit.paragraphs.order_by('ordinal'))
        raw = (FIXTURE / 'synthetic-film.mp4').read_bytes()
        self.film = Asset.objects.create(revision=revision, unit=unit, kind='video', provider='r2', state='ready',
                                         storage_key=f'revisions/{revision.id}/{uuid.uuid4().hex}.mp4',
                                         sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), content_type='video/mp4',
                                         duration_ms=FILM_MS)
        evidence = dict(revision.validation_evidence)
        if audio:
            unit.duration_ms = 1000 * len(self.paragraphs)
            unit.save()
            self.audio = Asset.objects.create(revision=revision, unit=unit, kind='audio_chapter', state='ready',
                                              storage_key=f'revisions/{revision.id}/{uuid.uuid4()}', sha256='c' * 64,
                                              bytes=64, content_type='audio/mpeg')
            evidence['media_assets'] = {str(self.audio.id): {'sha256': self.audio.sha256, 'unit_id': str(unit.id),
                'duration_ms': unit.duration_ms, 'quality_kbps': 96, 'prepared': True,
                'measurement_evidence': 'synthetic isolated test only'}}
            revision.validation_evidence = evidence
            revision.save()
            self.audio_map = TimingMap.objects.create(revision=revision, asset=self.audio, text_sha256=revision.content_sha256,
                asset_sha256=self.audio.sha256, measured=True, segments=[
                    {'anchor_id': str(p.anchor_id), 'start_offset_chars': 0, 'end_offset_chars': len(p.text),
                     'start_ms': i * 1000, 'end_ms': (i + 1) * 1000} for i, p in enumerate(self.paragraphs)])
        self.film_maps = []
        if film_map:
            parsed = read_film_timing(self.bundle_timing(), unit_id=self.live_unit.id, mp4_sha256=self.film.sha256,
                                      text_sha256=self.live_source.content_sha256)
            for mapping in film_timing_maps(revision, self.film, parsed, anchor_map_by_ordinal(self.live_unit, unit)):
                mapping.save()
                self.film_maps.append(mapping)
        # Rows bound to other film bytes (written past model clean): checked and skipped, never a query each.
        TimingMap.objects.bulk_create([TimingMap(revision=revision, asset=self.film, text_sha256=revision.content_sha256,
                                                 asset_sha256='d' * 64, precision='sentence', measured=True, segments=[])
                                       for _ in range(stale_film_maps)])
        self.revision, self.unit = revision, unit
        if publish:
            self.publish()
        return revision

    def publish(self):
        self.revision.state = 'live'
        self.revision.published_at = timezone.now()
        self.revision.save()
        self.edition.live_revision = self.revision
        self.edition.save()

    # ------------------------------------------------------------------ helpers
    def reader(self, n, offset=0):
        return {'format': 'reader', 'unit_id': str(self.unit.id), 'anchor_id': str(self.paragraphs[n].anchor_id),
                'offset_chars': offset}

    def at(self, fmt, ms):
        return {'format': fmt, 'unit_id': str(self.unit.id), 'position_ms': ms}

    def switch(self, location, to, user=None, territory='IN'):
        return switch_position(user or self.user, {'edition_revision_id': str(self.revision.id), 'from_location': location,
                                                   'to_format': to}, territory)

    def map_id(self, precision):
        return next(str(m.id) for m in self.film_maps if m.precision == precision)

    # ------------------------------------------------------------------ reader -> film
    def test_reader_anchor_opens_the_film_where_that_paragraph_is_narrated(self):
        self.stage()
        result = self.switch(self.reader(3, 10), 'video')
        self.assertEqual(result, {'outcome': 'mapped', 'to_location': self.at('video', PARA_STARTS[3]),
                                  'map_id': self.map_id('sentence'), 'precision': 'sentence', 'reason_code': None})

    def test_reader_sentence_opens_the_film_at_that_sentence(self):
        self.stage()
        p = self.paragraphs[0]
        self.assertEqual(self.switch(self.reader(0, 50), 'video')['to_location']['position_ms'], SENTENCE_STARTS[1])
        self.assertEqual(self.switch(self.reader(0, len(p.text)), 'video')['to_location']['position_ms'], SENTENCE_STARTS[2])

    def test_paragraph_map_alone_still_maps(self):
        self.stage(publish=False)
        TimingMap.objects.filter(pk=self.map_id('sentence')).update(asset_sha256='e' * 64)  # stale -> skipped
        self.publish()
        result = self.switch(self.reader(0, 50), 'video')
        self.assertEqual((result['precision'], result['to_location']['position_ms']), ('paragraph', PARA_STARTS[0]))

    # ------------------------------------------------------------------ film -> reader
    def test_film_position_opens_the_reader_at_the_narrated_anchor(self):
        self.stage()
        result = self.switch(self.at('video', PARA_STARTS[2] + 400), 'reader')
        self.assertEqual(result['outcome'], 'mapped')
        self.assertEqual(result['to_location'], self.reader(2, 0))
        sentence = self.switch(self.at('video', SENTENCE_STARTS[2] + 10), 'reader')
        self.assertEqual(sentence['to_location'], self.reader(0, 96))
        self.assertEqual(sentence['map_id'], self.map_id('sentence'))

    def test_film_between_narration_keeps_the_last_narrated_anchor(self):
        self.stage()
        self.assertEqual(self.switch(self.at('video', PARA_STARTS[2] - 50), 'reader')['to_location'], self.reader(1, 0))
        self.assertEqual(self.switch(self.at('video', FILM_MS), 'reader')['to_location'], self.reader(5, 0))  # credits

    def test_title_card_is_unmapped(self):
        self.stage()
        self.assertEqual(self.switch(self.at('video', 500), 'reader'),
                         {'outcome': 'unmapped', 'to_location': None, 'map_id': None, 'precision': None,
                          'reason_code': 'choose_chapter_or_start'})

    # ------------------------------------------------------------------ audio <-> film through the text
    def test_audio_and_film_switch_through_the_text(self):
        self.stage()
        to_film = self.switch(self.at('audio', 2500), 'video')
        self.assertEqual((to_film['outcome'], to_film['to_location']), ('mapped', self.at('video', PARA_STARTS[2])))
        to_audio = self.switch(self.at('video', PARA_STARTS[4] + 300), 'audio')
        self.assertEqual((to_audio['outcome'], to_audio['to_location'], to_audio['map_id']),
                         ('mapped', self.at('audio', 4000), str(self.audio_map.id)))

    # ------------------------------------------------------------------ unmapped, never an error
    def test_no_film_map_is_unmapped(self):
        self.stage(film_map=False)
        self.assertEqual(self.switch(self.reader(1), 'video')['outcome'], 'unmapped')
        self.assertEqual(self.switch(self.at('video', 3000), 'reader')['outcome'], 'unmapped')

    def test_stale_film_map_is_unmapped(self):
        self.stage(publish=False)
        TimingMap.objects.filter(asset=self.film).update(asset_sha256='e' * 64)
        self.publish()
        self.assertEqual(self.switch(self.reader(1), 'video')['outcome'], 'unmapped')

    def test_map_of_a_film_the_player_does_not_open_is_unused(self):
        self.stage(publish=False)
        # The player opens the lowest-id ready film of the unit: a second ready film ahead of the mapped one wins.
        raw = (FIXTURE / 'synthetic-film.mp4').read_bytes()
        Asset.objects.create(id=uuid.UUID(int=1), revision=self.revision, unit=self.unit,
                             kind='video', provider='r2', state='ready', storage_key=f'revisions/{self.revision.id}/first.mp4',
                             sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), content_type='video/mp4', duration_ms=FILM_MS)
        self.publish()
        self.assertEqual(self.switch(self.reader(1), 'video')['outcome'], 'unmapped')

    def test_film_maps_never_appear_in_audio_mappings(self):
        self.stage()
        listed = mappings(self.user, self.revision.id)
        self.assertEqual([m['map_id'] for m in listed['maps']], [str(self.audio_map.id)])

    # ------------------------------------------------------------------ access, drafts, features
    def test_video_feature_off_is_feature_disabled(self):
        self.stage()
        with override_settings(FEATURES={**settings.FEATURES, 'audio': True, 'video': False}):
            result = self.switch(self.reader(1), 'video')
        self.assertEqual((result['outcome'], result['to_location'], result['reason_code']),
                         ('feature_disabled', None, 'video_not_enabled'))

    def test_paid_film_without_entitlement_is_unreleased_then_mapped_once_entitled(self):
        self.stage(video='paid')
        result = self.switch(self.reader(1), 'video')
        self.assertEqual((result['outcome'], result['to_location'], result['map_id']), ('unreleased', None, None))
        with self.assertRaises(DomainError) as denied:  # the film source itself needs access, as audio does
            self.switch(self.at('video', 3000), 'reader')
        self.assertEqual(denied.exception.code, 'entitlement_required')
        now = timezone.now()
        Entitlement.objects.create(grant_key='film-switch-' + uuid.uuid4().hex, user=self.user, edition=self.edition,
                                   formats=['video'], source='one_time_order', scope='edition',
                                   valid_from=now - timedelta(seconds=1), valid_until=now + timedelta(hours=1))
        self.assertEqual(self.switch(self.reader(1), 'video')['outcome'], 'mapped')

    def test_other_territory_gets_no_film_timing(self):
        self.stage()
        result = self.switch(self.reader(1), 'video', territory='GB')  # reader cleared in GB, the film only in IN
        self.assertEqual((result['outcome'], result['to_location'], result['map_id']), ('unreleased', None, None))

    def test_unverified_member_is_refused(self):
        self.stage()
        self.user.is_verified = False
        self.user.save()
        with self.assertRaises(DomainError):
            self.switch(self.reader(1), 'video')

    def test_draft_film_timing_is_never_served(self):
        self.stage(publish=False)
        with self.assertRaises(DomainError) as hidden:  # a member cannot open the draft at all
            self.switch(self.reader(1), 'video')
        self.assertEqual(hidden.exception.code, 'content_unavailable')
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save()
        self.assertTrue(svc.can_review_draft(self.user, self.revision))
        svc.authorize_revision(self.user, self.revision, 'video')  # a reviewer may open the draft film itself
        for location, to in ((self.reader(1), 'video'), (self.at('video', 3000), 'reader')):
            result = self.switch(location, to)
            self.assertEqual((result['outcome'], result['to_location'], result['map_id'], result['precision']),
                             ('unreleased', None, None, None))

    # ------------------------------------------------------------------ importer geometry
    def test_importer_refuses_maps_that_do_not_fit_the_film_or_text(self):
        self.stage(film_map=False, publish=False)
        anchors = anchor_map_by_ordinal(self.live_unit, self.unit)

        def refused(mutate):
            doc = json.loads(self.bundle_timing())
            mutate(doc)
            parsed = read_film_timing(json.dumps(doc).encode(), unit_id=self.live_unit.id, mp4_sha256=self.film.sha256,
                                      text_sha256=self.live_source.content_sha256)
            with self.assertRaises(FilmTimingError):
                film_timing_maps(self.revision, self.film, parsed, anchors)
        refused(lambda d: d['maps'][0]['segments'][-1].update(end_ms=FILM_MS + 1))           # past the film
        refused(lambda d: d['maps'][0]['segments'].pop())                                      # a paragraph missing
        refused(lambda d: d['maps'][0]['segments'][0].update(anchor_id=str(uuid.uuid4())))     # not this unit
        refused(lambda d: d['maps'][0]['segments'].reverse())                                  # out of order
        refused(lambda d: d['maps'][1]['segments'][1].update(start_offset_chars=40))           # not the text's sentences
        self.assertEqual(TimingMap.objects.filter(asset=self.film).count(), 0)

    # ------------------------------------------------------------------ bounded queries
    def test_query_count_does_not_grow_with_maps(self):
        self.stage()
        with CaptureQueriesContext(connection) as few:
            self.switch(self.reader(2), 'video')
        self.stage(stale_film_maps=3)
        with CaptureQueriesContext(connection) as many:
            self.assertEqual(self.switch(self.reader(2), 'video')['outcome'], 'mapped')
        self.assertEqual(len(many), len(few))


class FilmTimingImportTests(SimpleTestCase):
    """The bundle's film timing file: exact shape and bindings, refused before anything is written."""
    def setUp(self):
        self.raw = (FIXTURE / 'synthetic-film.timing.json').read_bytes()
        self.doc = json.loads(self.raw)
        self.sha = self.doc['mp4_sha256']

    def read(self, doc=None, **binding):
        raw = self.raw if doc is None else json.dumps(doc).encode()
        args = {'unit_id': self.doc['unit_id'], 'mp4_sha256': self.sha, 'text_sha256': '0' * 64, **binding}
        return read_film_timing(raw, **args)

    def test_fixture_shape_is_accepted(self):
        parsed = self.read()
        self.assertEqual([p for p, _ in parsed['maps']], ['paragraph', 'sentence'])
        self.assertEqual(len(parsed['maps'][0][1]), 6)

    def test_bindings_are_exact(self):
        for binding in ({'unit_id': str(uuid.uuid4())}, {'mp4_sha256': 'f' * 64}, {'text_sha256': '1' * 64}):
            with self.subTest(binding=binding), self.assertRaises(FilmTimingError):
                self.read(**binding)

    def test_shape_errors_are_refused(self):
        def changed(fn):
            doc = json.loads(self.raw)
            fn(doc)
            return doc
        cases = {
            'extra key': changed(lambda d: d.update(extra=1)),
            'schema': changed(lambda d: d.update(schema='other')),
            'blank evidence': changed(lambda d: d.update(measurement_evidence_ref=' ')),
            'no paragraph map': changed(lambda d: d.update(maps=d['maps'][1:])),
            'repeated precision': changed(lambda d: d.update(maps=[d['maps'][0], d['maps'][0]])),
            'float ms': changed(lambda d: d['maps'][0]['segments'][0].update(start_ms=1.5)),
            'sentence index on paragraph map': changed(lambda d: d['maps'][0]['segments'][0].update(sentence_index=0)),
            'missing key': changed(lambda d: d['maps'][0]['segments'][0].pop('end_ms')),
        }
        for name, doc in cases.items():
            with self.subTest(name), self.assertRaises(FilmTimingError):
                self.read(doc)
        with self.assertRaises(FilmTimingError):
            read_film_timing(b'not json', unit_id='x', mp4_sha256=self.sha, text_sha256='0' * 64)
