"""Search acceptance on PostgreSQL; no providers or publication of real books."""
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from core.api import DomainError
from .models import Edition, Revision, Work
from .search import normalize_search_text, refresh_revision_search, search_editions
from .search_models import SearchAlias, SearchDocument


class SearchContractTests(TestCase):
    def edition(self, title, *, locale='en', description='', live=True, **work_metadata):
        key = uuid.uuid4().hex
        work = Work.objects.create(slug='search-'+key, title=title, **work_metadata)
        edition = Edition.objects.create(work=work, slug='search-'+key, locale=locale)
        revision = Revision.objects.create(edition=edition, title=title, description=description)
        if live:
            revision.state = 'live'; revision.save()
            edition.live_revision = revision; edition.save()
        refresh_revision_search(revision)
        return edition, revision

    def results(self, query, locale='en'):
        return list(search_editions(Edition.objects.all(), query, locale))

    def test_english_stemming_and_exact_prefix_priority(self):
        exact, _ = self.edition('Garden')
        prefix, _ = self.edition('Garden stories')
        stem, _ = self.edition('Winter observations', description='The gardener was gardening in the gardens.')
        found = self.results('garden')
        self.assertEqual([e.pk for e in found[:2]], [exact.pk, prefix.pk])
        self.assertIn(stem.pk, [e.pk for e in found])
        self.assertEqual(connection.vendor, 'postgresql')

    def test_reviewed_banglish_aliases_are_locale_and_time_scoped(self):
        target, _ = self.edition('ন্যায়বিচার', locale='bn')
        reviewer = get_user_model().objects.create_user('search-reviewer@example.test', 'Long-Search-Passphrase-47')
        alias = SearchAlias.objects.create(locale='bn', alias_normalized='bicharok', target_normalized='ন্যায়বিচার',
                                          reviewed_by=reviewer, reviewed_at=timezone.now())
        self.assertEqual([e.pk for e in self.results('BICHAROK', 'bn')], [target.pk])
        alias.active=False; alias.save()
        self.assertEqual(self.results('bicharok', 'bn'), [])
        alias.active=True; alias.reviewed_at=timezone.now()+timedelta(days=1); alias.save()
        self.assertEqual(self.results('bicharok', 'bn'), [])
        self.assertEqual(self.results('bicharok', 'en'), [])
        alias.active=False; alias.save()
        romanized, _ = self.edition('বিচারক', locale='bn')
        self.assertEqual([e.pk for e in self.results('bicharok', 'bn')], [romanized.pk])  # inactive alias does not suppress romanized match

    def test_bengali_nfc_and_punctuation_short_input_are_controlled(self):
        target, _ = self.edition('নদীর কথা', locale='bn', description='মীরা নদীতে নৌকা দেখল।')
        self.assertEqual([e.pk for e in self.results('  নদীর   কথা  ', 'bn')], [target.pk])
        self.assertIn(target.pk, [e.pk for e in self.results('নৌকা', 'bn')])
        self.assertEqual(self.results('%%', 'bn'), [])
        self.assertEqual(normalize_search_text('  মীরা\u200d  '), 'মীরা\u200d')

    def test_index_never_changes_revision_or_indexes_private_paragraphs(self):
        edition, revision = self.edition('Public metadata', description='Searchable synopsis')
        version = Revision.objects.get(pk=revision.pk).version
        refresh_revision_search(revision)
        self.assertEqual(Revision.objects.get(pk=revision.pk).version, version)
        row = SearchDocument.objects.get(pk=revision.pk)
        self.assertEqual(row.text_normalized, 'public metadata searchable synopsis')
        self.assertEqual(self.results('rights_document'), [])
        self.assertEqual(self.results('storage_key'), [])
        draft, _ = self.edition('Private draft phrase', live=False)
        self.assertNotIn(draft.pk, [e.pk for e in self.results('private draft')])
        edition.live_revision = None; edition.save()
        self.assertEqual(self.results('public metadata'), [])

    def test_trigram_typo_and_short_prefix_use_indexable_predicates(self):
        target, _ = self.edition('Watercolour adventures')
        self.assertIn(target.pk, [e.pk for e in self.results('watercolur')])
        short = search_editions(Edition.objects.all(), 'wa', 'en')
        self.assertEqual([e.pk for e in short], [target.pk])
        self.assertNotIn('SIMILARITY', str(short.query).upper())
        fuzzy = str(search_editions(Edition.objects.all(), 'watercolur', 'en').query)
        self.assertIn(' % ', fuzzy)
        self.assertIn('@@', fuzzy)
        with connection.cursor() as cursor:
            cursor.execute("SELECT indexname FROM pg_indexes WHERE tablename='maison_search_document'")
            names={row[0] for row in cursor.fetchall()}
        self.assertTrue({'maison_search_document_gin','maison_search_title_trgm','maison_search_title_prefix'} <= names)

    def test_query_bounds_and_scores_are_cursor_safe(self):
        self.edition('A long journey')
        for value in ('x'*121, None):
            with self.assertRaises(DomainError): self.results(value)
        found=self.results('journey')
        self.assertTrue(found and all(isinstance(row.search_score, float) for row in found))

    def test_bicharak_finds_bicharak_edition(self):
        from .romanize import romanize_bn
        self.assertEqual(romanize_bn('বিচারক'), {'bicharak', 'bicharok'})
        target, _ = self.edition('বিচারক', locale='bn')
        self.assertEqual([e.pk for e in self.results('bicharak', 'bn')], [target.pk])
        self.assertEqual([e.pk for e in self.results('Bi-Char ak', 'bn')], [target.pk])
        self.assertEqual([e.pk for e in self.results('bicharak')], [])  # English locale scope

    def test_bicharok_also_matches(self):
        target, _ = self.edition('বিচারক', locale='bn')
        self.assertEqual([e.pk for e in self.results('bicharok', 'bn')], [target.pk])
        self.assertEqual([e.pk for e in list(search_editions(Edition.objects.all(), 'bicharok'))], [target.pk])

    def test_draft_bengali_title_is_not_found_by_its_latin_form(self):
        self.edition('বিচারক', locale='bn', live=False)
        self.assertEqual(self.results('bicharak', 'bn'), [])
        self.assertEqual(list(search_editions(Edition.objects.all(), 'bicharok')), [])

    def test_romanized_scan_is_uncapped_so_no_published_title_drops_out(self):
        made = {self.edition('বিচারক', locale='bn')[0].pk for _ in range(12)}
        self.assertEqual({e.pk for e in self.results('bicharak', 'bn')}, made)

    def test_reviewed_alias_still_ranks_first(self):
        romanized, _ = self.edition('বিচারক', locale='bn')
        aliased, _ = self.edition('ন্যায়বিচার', locale='bn')
        reviewer = get_user_model().objects.create_user('search-rank@example.test', 'Long-Search-Passphrase-47')
        SearchAlias.objects.create(locale='bn', alias_normalized='bicharok', target_normalized='ন্যায়বিচার',
                                  reviewed_by=reviewer, reviewed_at=timezone.now())
        found = [e.pk for e in self.results('bicharok', 'bn')]
        self.assertEqual(found[:2], [aliased.pk, romanized.pk])


class FilmGrantContractExampleTests(TestCase):
    def test_r2_film_grant_example_validates_against_media_grant(self):
        import json
        from pathlib import Path
        from django.conf import settings
        from .validation import validate_schema
        examples=json.loads((Path(settings.BASE_DIR)/'contracts'/'payload-examples.json').read_text())
        grant=examples['video_grant_r2']['response']
        validate_schema(grant,'MediaGrant')
        self.assertEqual((grant['transport'],grant['content_type'],grant['range_supported']),('r2_s3_presigned','video/mp4',True))
