import csv
import io
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings

from .models import Asset, Edition, Unit


@override_settings(LOCAL=True, MAISON_LOCAL_FIXTURES=True)
class LicensingCatalogueTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        call_command('seed_local_pilot', stdout=io.StringIO())
        self.en = Edition.objects.get(pk='20000000-0000-4000-8000-000000000001')
        self.bn = Edition.objects.get(pk='20000000-0000-4000-8000-000000000002')
        self.out = Path(self.tmp.name) / 'cat.csv'

    def translate(self, method, credit):
        self.en.translated_from = self.bn
        self.en.translation_method = method
        self.en.translation_credit = credit
        self.en.translation_model = 'm'
        self.en.save()

    def export(self, *extra):
        call_command('licensing_catalogue', '--out', str(self.out), *extra, stdout=io.StringIO())
        with self.out.open(encoding='utf-8', newline='') as fh:
            return list(csv.DictReader(fh))

    def test_only_editor_revised_translations_listed(self):
        self.assertEqual(self.export('--replace'), [])
        self.translate('ai', '')
        self.assertEqual(self.export('--replace'), [])
        self.translate('ai_edited', 'Rina Das')
        rows = self.export('--replace')
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['edition_slug'], self.en.slug)
        self.assertEqual(row['source_edition_slug'], self.bn.slug)
        self.assertEqual(row['source_language'], 'bn')
        self.assertEqual(row['language'], 'en')
        self.assertEqual(row['editor_credit'], 'Rina Das')
        self.assertEqual(row['title'], self.en.live_revision.title)

    def test_unpublished_edited_translation_not_listed(self):
        self.translate('ai_edited', 'Rina Das')
        Edition.objects.filter(pk=self.en.pk).update(live_revision=None)
        self.assertEqual(self.export('--replace'), [])

    def test_territories_column_is_the_nine(self):
        self.translate('ai_edited', 'Rina Das')
        row = self.export()[0]
        self.assertEqual(row['territories'].split(' '), list(settings.MAISON_PUBLICATION_TERRITORIES))
        self.assertEqual(len(row['territories'].split(' ')), 9)

    def test_audio_duration_and_cover(self):
        self.translate('ai_edited', 'Rina Das')
        self.assertEqual(self.export()[0]['audio_duration_ms'], '')
        rev = self.en.live_revision
        unit = Unit.objects.filter(revision=rev).first()
        with connection.cursor() as cur:  # the live revision is frozen; fixture-only bypass of the guard trigger
            cur.execute('SET LOCAL session_replication_role = replica')
        Unit.objects.filter(pk=unit.pk).update(duration_ms=1500)
        Asset.objects.bulk_create([Asset(revision=rev, unit=unit, kind='audio_chapter', state='ready', storage_key='t12/a1',
                             sha256='0' * 64, bytes=1, content_type='audio/mpeg', duration_ms=1500)])
        row = self.export('--replace')[0]
        self.assertEqual(row['audio_duration_ms'], '1500')
        cover = Asset.objects.get(revision=rev, kind='cover', state='ready')
        self.assertTrue(row['cover_url'].endswith(f'/api/v1/content/covers/{cover.pk}'))

    @override_settings(LOCAL=False, PUBLIC_BASE_URL='')
    def test_unset_public_origin_gives_blank_cover_not_failure(self):
        self.translate('ai_edited', 'Rina Das')
        row = self.export()[0]
        self.assertEqual(row['cover_url'], '')
        self.assertEqual(row['edition_slug'], self.en.slug)

    def test_failed_replace_keeps_old_export(self):
        self.translate('ai_edited', 'Rina Das')
        self.export()
        before = self.out.read_text(encoding='utf-8')
        with mock.patch('library.management.commands.licensing_catalogue.csv.DictWriter.writerows',
                        side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.export('--replace')
        self.assertEqual(self.out.read_text(encoding='utf-8'), before)
        self.assertFalse(Path(str(self.out) + '.tmp').exists())

    def test_refuses_overwrite_without_replace(self):
        self.translate('ai_edited', 'Rina Das')
        self.export()
        with self.assertRaises(CommandError):
            self.export()
        self.export('--replace')
