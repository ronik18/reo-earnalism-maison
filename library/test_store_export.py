import hashlib, io, json, tempfile, uuid
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.api import DomainError
from library.models import Asset, Edition, Revision, Work
from library.storage import put_private
from library.store_export import export_play_books
from django.utils import timezone
from library.models import Paragraph, Unit
from library.services import prepare_reader_package

COVER = b'\xff\xd8\xff\xe0cover-bytes'


class StoreExportTests(TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        o = override_settings(MEDIA_ROOT=d.name, MAISON_LOCAL_FIXTURES=True, LOCAL=True); o.enable(); self.addCleanup(o.disable)
        self.out = Path(d.name) / 'bundle'
        key = uuid.uuid4().hex
        work = Work.objects.create(slug='sx-'+key, title='Export book', house='golpo', creators=['A writer'])
        self.edition = Edition.objects.create(work=work, slug='sx-'+key, locale='en')
        policy = {'reader': 'free', 'audio': 'free'}
        self.revision = rev = Revision.objects.create(edition=self.edition, title='Export book', description='Desc', access_policy=policy)
        for n, dur in enumerate([1000, 2000]):
            unit = Unit.objects.create(revision=rev, ordinal=n+1, title=f'Chapter {n+1}', duration_ms=dur)
            rows = [Paragraph.objects.create(unit=unit, ordinal=1, text=f'Unit {n+1} text.')]
            prepare_reader_package(unit, rows).save()
            Asset.objects.create(revision=rev, unit=unit, kind='audio_chapter', state='ready',
                                 storage_key=f'revisions/{rev.pk}/{uuid.uuid4()}', sha256='a'*64,
                                 bytes=10, content_type='audio/mpeg', duration_ms=dur)
        ckey = f'revisions/{rev.pk}/{uuid.uuid4()}'
        put_private(ckey, COVER, 'image/jpeg')
        Asset.objects.create(revision=rev, kind='cover', state='ready', storage_key=ckey,
                             sha256=hashlib.sha256(COVER).hexdigest(), bytes=len(COVER), content_type='image/jpeg')
        rev.state = 'live'; rev.published_at = timezone.now(); rev.save()
        self.edition.live_revision = rev; self.edition.save()
        self.clear()

    def clear(self, **over):
        c = {'status': 'pass', 'sha256': self.revision.content_sha256, 'formats': ['reader', 'audio'],
             'territories': list(settings.MAISON_PUBLICATION_TERRITORIES), 'evidence_ref': 'x#sha256=1'}
        c.update(over)
        self.revision.validation_evidence = {'publication_clearance': c}
        type(self.revision).objects.filter(pk=self.revision.pk).update(validation_evidence=self.revision.validation_evidence)

    def test_bundle_lists_exactly_the_nine_territories(self):
        m = export_play_books(self.edition.pk, self.out)
        self.assertEqual(m['territories'], list(settings.MAISON_PUBLICATION_TERRITORIES))
        self.assertEqual(json.loads((self.out / 'metadata.json').read_text())['territories'], m['territories'])
        self.assertEqual(m['publisher'], 'Earnalism')
        self.assertEqual((self.out / 'cover.jpg').read_bytes(), COVER)
        self.assertEqual([c['duration_ms'] for c in m['chapters']], [1000, 2000])
        self.assertEqual(len(json.loads((self.out / 'audio' / 'listing.json').read_text())), 2)
        self.assertFalse(list((self.out / 'audio').glob('*.mp3')))

    def test_audio_not_cleared_is_refused(self):
        for over in ({'formats': ['reader']}, {'territories': list(settings.MAISON_PUBLICATION_TERRITORIES)[:-1]},
                     {'status': 'fail'}):
            self.clear(**over)
            with self.subTest(over=over), self.assertRaises(DomainError) as e:
                export_play_books(self.edition.pk, self.out)
            self.assertEqual(e.exception.code, 'STORE_FORMAT_NOT_CLEARED')

    def test_unpublished_is_refused(self):
        ed = Edition.objects.create(work=Work.objects.create(slug='w-'+uuid.uuid4().hex, title='W', house='golpo'), slug='e-'+uuid.uuid4().hex, locale='en')
        with self.assertRaises(DomainError) as e:
            export_play_books(ed.pk, self.out)
        self.assertEqual(e.exception.code, 'NOT_PUBLISHED')

    def test_ai_narration_and_translation_disclosed(self):
        m = export_play_books(self.edition.pk, self.out)
        self.assertEqual(m['narration'], {'type': 'ai', 'disclosure': 'Narrated with an AI voice.'})
        self.assertIsNone(m['translation'])
        src = Edition.objects.create(work=self.edition.work, slug='src-'+uuid.uuid4().hex, locale='bn')
        self.edition.translated_from = src; self.edition.translation_method = 'ai_edited'
        self.edition.translation_credit = 'Edited by A'; self.edition.translation_model = 'm1'; self.edition.save()
        m = export_play_books(self.edition.pk, self.out / 'two')
        self.assertEqual(m['translation'], {'method': 'ai_edited', 'credit': 'Edited by A', 'model': 'm1'})

    def test_command_refuses_non_empty_out(self):
        self.out.mkdir(); (self.out / 'f').write_text('x')
        with self.assertRaises(CommandError):
            call_command('store_export', 'play-books', self.edition.slug, '--out', str(self.out), stdout=io.StringIO())
        (self.out / 'f').unlink()
        call_command('store_export', 'play-books', self.edition.slug, '--out', str(self.out), stdout=io.StringIO())
        self.assertTrue((self.out / 'metadata.json').exists())
