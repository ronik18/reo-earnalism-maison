import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from operations.models import ReviewItem


def run(*args):
    out = StringIO()
    call_command('queue_intake_packets', *args, stdout=out)
    return out.getvalue()


class QueueIntakePacketsTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        override = override_settings(BASE_DIR=self.root)
        override.enable()
        self.addCleanup(override.disable)

    def packet(self, slug, status='DRAFT_PENDING_OWNER_APPROVAL', translation=False):
        folder = self.root / 'library' / 'intake' / slug
        folder.mkdir(parents=True)
        (folder / 'manifest.json').write_text(json.dumps({'edition': {'slug': slug, 'title': f'Title {slug}'}}))
        (folder / 'source.json').write_text('{}')
        (folder / 'cover_provenance.json').write_text('{"status": "x"}')
        if translation:
            (folder / 'translation.json').write_text('{"translated_from": "a"}')
        evidence = self.root / 'docs' / 'evidence'
        evidence.mkdir(parents=True, exist_ok=True)
        approved = status == 'OWNER_APPROVED'
        (evidence / f'publication-clearance-{slug}-draft.json').write_text(json.dumps(
            {'status': status, 'approval': {'approved': approved, 'still_required': [] if approved else ['x']}}))
        return folder

    def test_queues_clearance_and_cover_once(self):
        self.packet('book')
        self.assertEqual(run().count(' queued'), 2)
        self.assertEqual(ReviewItem.objects.count(), 2)
        item = ReviewItem.objects.get(kind='clearance')
        self.assertEqual(item.summary, {'edition_slug': 'book', 'title': 'Title book'})
        self.assertEqual(item.ref, 'docs/evidence/publication-clearance-book-draft.json')
        self.assertEqual(run().count('already queued'), 2)
        self.assertEqual(ReviewItem.objects.count(), 2)

    def test_skips_in_file_owner_approved_clearance(self):
        self.packet('book', status='OWNER_APPROVED')
        out = run()
        self.assertIn('already owner-approved', out)
        self.assertIn('skipped: clearance approved in file', out)
        self.assertEqual(list(ReviewItem.objects.values_list('kind', flat=True)), [])

    def test_missing_draft_names_the_clearance_file_the_manifest_cites(self):
        folder = self.packet('book')
        (self.root / 'docs' / 'evidence' / 'publication-clearance-book-draft.json').unlink()
        (folder / 'manifest.json').write_text(json.dumps({'edition': {'slug': 'book'}, 'provenance': {'rights_evidence_refs': [
            'other:x.json', 'reo-earnalism-maison:docs/evidence/publication-clearance-20261123.json']}}))
        out = run()
        self.assertIn('manifest cites reo-earnalism-maison:docs/evidence/publication-clearance-20261123.json', out)
        self.assertNotIn('no draft record)', out.replace('no draft record;', ''))

    def test_review_exposes_public_file_sha256(self):
        from operations import review
        self.packet('book')
        ref = 'library/intake/book/cover_provenance.json'
        self.assertEqual(review.file_sha256(ref), review._file_sha256(ref))
        self.assertIsNone(review.file_sha256('library/intake/book/missing.json'))

    def test_translation_queues_edition_items(self):
        self.packet('book-en', translation=True)
        run()
        self.assertEqual(sorted(ReviewItem.objects.values_list('kind', flat=True)), ['clearance', 'cover', 'edition', 'edition'])

    def test_live_translation_edition_files_are_informational_and_not_queued(self):
        from library.models import Edition, Revision, Work
        self.packet('book-en', translation=True)
        work = Work.objects.create(slug='w-book', title='Work', creators=['a'], house='golpo')
        edition = Edition.objects.create(work=work, slug='book-en', locale='en')
        revision = Revision.objects.create(edition=edition, title='Book', content_sha256='')
        Revision.objects.filter(pk=revision.pk).update(state='live')
        Edition.objects.filter(pk=edition.pk).update(live_revision=revision)
        out = run()
        self.assertIn('edition files skipped (informational: the edition is already live)', out)
        self.assertEqual(sorted(ReviewItem.objects.values_list('kind', flat=True)), ['clearance', 'cover'])

    def test_changed_file_supersedes_pending(self):
        folder = self.packet('book')
        run()
        (folder / 'cover_provenance.json').write_text('{"status": "changed"}')
        run()
        self.assertEqual(ReviewItem.objects.filter(kind='cover', status='pending').count(), 1)
        self.assertEqual(ReviewItem.objects.filter(kind='cover', status='rejected', decision_note='superseded').count(), 1)

    def test_dry_run_writes_nothing_and_slug_filter(self):
        self.packet('one')
        self.packet('two')
        self.assertIn('would queue', run('--dry-run'))
        self.assertEqual(ReviewItem.objects.count(), 0)
        run('--slug', 'two')
        self.assertEqual({i.summary['edition_slug'] for i in ReviewItem.objects.all()}, {'two'})
