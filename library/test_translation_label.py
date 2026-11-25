"""AI and editor-revised translations are labelled; originals show no label."""
import hashlib
import io
import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from operations.book_source import SOURCE_SCHEMA, read_source_bytes, validate_manifest

from .models import Edition

BN_SOURCE = {'schema': SOURCE_SCHEMA, 'language': 'bn', 'units': [{
    'key': 'chapter-001', 'title': 'ক্ষুধিত পাষাণ', 'kind': 'chapter',
    'paragraphs': [{'kind': 'paragraph', 'text': 'আমি ফিরিয়া আসিতেছিলাম।'}]}]}
EN_SOURCE = {'schema': SOURCE_SCHEMA, 'language': 'en', 'units': [{
    'key': 'chapter-001', 'title': 'The Hungry Stones', 'kind': 'chapter',
    'paragraphs': [{'kind': 'paragraph', 'text': 'I was returning home.'}]}]}


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=1) + '\n').encode('utf-8')


@override_settings(LOCAL=True, MAISON_LOCAL_FIXTURES=True, FREE_ACCESS_ENABLED=True)
class TranslationLabelTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        o = override_settings(MEDIA_ROOT=self.tmp.name)
        o.enable()
        self.addCleanup(o.disable)
        call_command('seed_local_pilot', stdout=io.StringIO())
        self.en = Edition.objects.get(pk='20000000-0000-4000-8000-000000000001')
        self.bn = Edition.objects.get(pk='20000000-0000-4000-8000-000000000002')
        user = get_user_model().objects.create_user('translation-reader@example.test', 'Translation-Reader-47')
        self.client.force_login(user)

    def translate(self, method='ai', credit='', model='claude-sonnet-5-5'):
        self.en.translated_from = self.bn
        self.en.translation_method = method
        self.en.translation_credit = credit
        self.en.translation_model = model
        self.en.save()

    def pages(self):
        title = self.client.get(f'/en/titles/{self.en.pk}/')
        reader = self.client.get(f'/en/read/{self.en.pk}/')
        if reader.status_code == 302:
            reader = self.client.get(reader['Location'])
        self.assertEqual(title.status_code, 200)
        self.assertEqual(reader.status_code, 200)
        return title.content.decode(), reader.content.decode()

    def test_ai_translation_is_labelled_on_title_and_reader(self):
        self.translate('ai')
        for html in self.pages():
            self.assertIn('<p class="fine">AI translation</p>', html)
            self.assertNotIn('<p class="fine">Translated', html)

    def test_edited_translation_credits_the_editor(self):
        self.translate('ai_edited', credit='Asha Rahman')
        for html in self.pages():
            self.assertIn('<p class="fine">Translated with AI, edited by Asha Rahman</p>', html)
            self.assertNotIn('<p class="fine">AI translation', html)

    def test_editor_credit_is_escaped_on_the_title_page(self):
        self.translate('ai_edited', credit='<script>alert(1)</script>')
        html = self.pages()[0]
        self.assertIn('edited by &lt;script&gt;alert(1)&lt;/script&gt;</p>', html)
        self.assertNotIn('<script>alert(1)</script>', html)

    def test_original_editions_show_no_label(self):
        for html in self.pages():
            self.assertNotIn('<p class="fine">AI translation', html)
            self.assertNotIn('<p class="fine">Translated', html)

    def test_database_rejects_edited_without_credit(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.translate('ai_edited', credit='')

    def test_database_rejects_method_without_source_and_source_without_method(self):
        self.en.translation_method = 'ai'
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.en.save()
        self.en.refresh_from_db()
        self.en.translated_from = self.bn
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.en.save()

    def test_clean_requires_a_different_locale(self):
        other = Edition.objects.create(work=self.en.work, slug='another-en', locale='en')
        self.en.translated_from = other
        self.en.translation_method = 'ai'
        with self.assertRaises(ValidationError):
            self.en.clean()


class IntakeTranslationCommandTests(TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        packet = self.root / 'library/intake/kp'
        packet.mkdir(parents=True)
        raw = _bytes(BN_SOURCE)
        self.source_sha = hashlib.sha256(raw).hexdigest()
        (packet / 'source.json').write_bytes(raw)
        (packet / 'manifest.json').write_text(json.dumps({
            'schema': 'earnalism.book_import_manifest.v1', 'project_id': 'kp-1',
            'work': {'slug': 'kp', 'title': 'ক্ষুধিত পাষাণ', 'creators': ['রবীন্দ্রনাথ ঠাকুর'], 'house': 'golpo'},
            'edition': {'slug': 'kp', 'language': 'bn', 'title': 'ক্ষুধিত পাষাণ', 'description': 'বিবরণ'},
            'source': {'sha256': self.source_sha, 'bytes': len(raw), 'content_type': 'application/json', 'format': SOURCE_SCHEMA},
            'provenance': {'source_ref': 'https://bn.wikisource.org/x', 'source_edition': 'Galpa-Dashak, 1895.',
                           'rights_note': 'Tagore died 1941.', 'rights_evidence_refs': ['reo-earnalism-maison:docs/evidence/publication-clearance-kp.json']}},
            ensure_ascii=False), encoding='utf-8')
        evidence = self.root / 'docs/evidence'
        evidence.mkdir(parents=True)
        (evidence / 'publication-clearance-kp.json').write_text(json.dumps({
            'schema': 'earnalism.publication-clearance-evidence.v1', 'status': 'APPROVED', 'territories': ['IN'],
            'formats': ['reader'], 'actions': ['read', 'preview'], 'downloads': False,
            'books': {'kp': {'work': 'ক্ষুধিত পাষাণ', 'author': 'রবীন্দ্রনাথ ঠাকুর', 'author_died': 1941, 'first_published': 1895,
                             'territory_terms': {}, 'term_screen_verdict': 'pass'}}}), encoding='utf-8')
        self.translated = self.root / 'en.json'
        self.translated.write_bytes(_bytes(EN_SOURCE))
        base = override_settings(BASE_DIR=self.root)  # the command queues what it writes relative to the repository
        base.enable()
        self.addCleanup(base.disable)

    def run_command(self, *extra, slug='kp-en'):
        out = io.StringIO()
        call_command('intake_translation', slug, '--from', 'kp', '--source', str(self.translated),
                     '--title', 'The Hungry Stones', '--description', 'A tale.', '--model', 'claude-sonnet-5-5',
                     '--root', str(self.root), *extra, stdout=out)
        return out.getvalue()

    def test_intake_translation_writes_draft_packet_with_method_and_model(self):
        self.run_command('--method', 'ai_edited', '--credit', 'Asha Rahman')
        packet = self.root / 'library/intake/kp-en'
        manifest = json.loads((packet / 'manifest.json').read_text(encoding='utf-8'))
        validate_manifest(manifest)
        self.assertEqual(manifest['edition']['language'], 'en')
        raw = (packet / 'source.json').read_bytes()
        read_source_bytes(raw)
        self.assertEqual(manifest['source']['sha256'], hashlib.sha256(raw).hexdigest())
        edition = manifest['provenance']['source_edition']
        for fragment in ('kp', self.source_sha, 'ai_edited', 'claude-sonnet-5-5'):
            self.assertIn(fragment, edition)
        self.assertRegex(edition, r'\d{4}-\d{2}-\d{2}')
        self.assertIn('new work by Earnalism', manifest['provenance']['rights_note'])
        self.assertIn('Asha Rahman', manifest['provenance']['rights_note'])
        meta = json.loads((packet / 'translation.json').read_text(encoding='utf-8'))
        self.assertEqual({k: meta[k] for k in ('translated_from', 'method', 'credit', 'model', 'source_sha256')},
                         {'translated_from': 'kp', 'method': 'ai_edited', 'credit': 'Asha Rahman',
                          'model': 'claude-sonnet-5-5', 'source_sha256': self.source_sha})
        self.assertIn('date', meta)
        draft = json.loads((self.root / 'docs/evidence/publication-clearance-kp-en-draft.json').read_text(encoding='utf-8'))
        self.assertEqual(draft['status'], 'DRAFT_PENDING_OWNER_APPROVAL')
        book = draft['books']['kp-en']
        self.assertIsNone(book['term_screen_verdict'])
        self.assertEqual(book['term_screen_source_text'], 'pass')
        self.assertEqual(book['source_text']['author_died'], 1941)
        self.assertNotIn('author_died', book)
        self.assertIn('Translation is a new work; its own clearance needs owner review.', book['review_notes'])
        from operations.models import ReviewItem
        queued = {(i.kind, i.ref): i for i in ReviewItem.objects.all()}
        self.assertEqual(set(queued), {('clearance', 'docs/evidence/publication-clearance-kp-en-draft.json'),
                                       ('edition', 'library/intake/kp-en/manifest.json'),
                                       ('edition', 'library/intake/kp-en/translation.json')})
        for (_, ref), item in queued.items():
            self.assertEqual(item.sha256, hashlib.sha256((self.root / ref).read_bytes()).hexdigest())
            self.assertEqual(item.summary, {'edition_slug': 'kp-en', 'title': 'The Hungry Stones'})
            self.assertEqual(item.status, 'pending')

    def test_same_slug_as_source_is_refused_even_with_replace(self):
        with self.assertRaisesRegex(CommandError, 'SAME_SLUG'):
            self.run_command('--method', 'ai', '--replace', slug='kp')

    def test_refuses_overwrite_without_replace_and_bad_inputs(self):
        self.run_command('--method', 'ai')
        with self.assertRaisesRegex(CommandError, 'PACKET_EXISTS'):
            self.run_command('--method', 'ai')
        self.run_command('--method', 'ai', '--replace')
        with self.assertRaisesRegex(CommandError, 'CREDIT_REQUIRED'):
            self.run_command('--method', 'ai_edited', slug='other')
        self.translated.write_bytes(_bytes(BN_SOURCE))
        with self.assertRaisesRegex(CommandError, 'SAME_LANGUAGE'):
            self.run_command('--method', 'ai', slug='same')
