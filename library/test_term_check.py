"""Public-domain term screen: matches the recorded clearance evidence and holds edge cases."""
import io
import json
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from library.term_check import RULES, active_territories, assess, screen

ROOT = Path(__file__).resolve().parents[1]


class TermScreenTests(SimpleTestCase):
    def test_reproduces_the_owner_approved_evidence_for_both_live_titles(self):
        evidence = json.loads((ROOT / 'docs/evidence/publication-clearance-20261123.json').read_text())
        for slug, book in evidence['books'].items():
            terms = assess(book['author_died'], book['first_published'], 2026, evidence['territories'])
            for code, recorded in book['territory_terms'].items():
                with self.subTest(slug=slug, code=code):
                    self.assertEqual(terms[code]['status'], 'public_domain')
                    self.assertEqual(terms[code]['source'], recorded['source'])
                    if isinstance(recorded['expired_end_of'], int):
                        self.assertEqual(terms[code]['expired_end_of'], recorded['expired_end_of'])

    def test_every_active_territory_has_a_rule(self):
        self.assertTrue(set(active_territories()) <= set(RULES))

    def test_boundaries_life_plus_seventy_and_ninety_five_years_from_publication(self):
        died_1955 = assess(1955, 1920, 2026)
        self.assertEqual(died_1955['GB']['status'], 'public_domain')  # expired end of 2025
        self.assertEqual(assess(1956, 1920, 2026)['GB']['status'], 'in_copyright')
        self.assertEqual(assess(1900, 1930, 2026)['US']['status'], 'public_domain')
        self.assertEqual(assess(1900, 1931, 2026)['US']['status'], 'in_copyright')

    def test_disputed_or_late_death_year_holds_and_missing_years_are_unknown(self):
        held = screen({'slug': 'thakurmar-jhuli', 'author_died': 1957, 'first_published': 1907}, 2026)
        self.assertEqual(held['verdict'], 'hold')
        self.assertEqual(held['blocked_in'], ['BR', 'GB', 'ID', 'SG'])
        self.assertFalse(held['is_clearance'])
        unknown = screen({'first_published': 1900}, 2026)
        self.assertEqual(unknown['verdict'], 'hold')
        self.assertEqual(unknown['territory_terms']['IN']['status'], 'unknown')

    def test_translations_and_illustrations_need_review_and_bad_input_is_refused(self):
        self.assertEqual(screen({'author_died': 1900, 'first_published': 1890, 'illustrated': True}, 2026)['verdict'], 'review')
        for bad in ('1941', 41, True):
            with self.assertRaises(ValueError):
                assess(bad, 1890, 2026)
        with self.assertRaises(ValueError):
            assess(1900, 1890, 2026, ['AE'])

    def test_command_screens_the_candidate_list(self):
        out = io.StringIO()
        call_command('term_check', '--candidates', str(ROOT / 'library/intake/candidates-20261124.json'), '--year', '2026', '--json', stdout=out)
        rows = {r['slug']: r['verdict'] for r in json.loads(out.getvalue())['rows']}
        self.assertEqual(rows['kabuliwala'], 'screen_pass')
        self.assertEqual(rows['thakurmar-jhuli'], 'hold')
        self.assertEqual(rows['tuntunir-boi'], 'review')
        out = io.StringIO()
        call_command('term_check', '--author-died', '1941', '--first-published', '1892', '--year', '2026', stdout=out)
        self.assertIn('Research only: not publication clearance.', out.getvalue())
        with self.assertRaises(CommandError):
            call_command('term_check')
