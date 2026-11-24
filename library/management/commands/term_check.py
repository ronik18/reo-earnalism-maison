"""Screen candidate titles' copyright terms across the active publication whitelist.

  python manage.py term_check --author-died 1941 --first-published 1892 [--year 2026]
  python manage.py term_check --candidates library/intake/candidates-20261124.json [--json]

Research screen only (library.term_check): it never writes rights, evidence or clearance.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from library.term_check import screen


class Command(BaseCommand):
    help = 'Public-domain term screen for candidate titles (read-only; not clearance).'

    def add_arguments(self, parser):
        parser.add_argument('--author-died', type=int)
        parser.add_argument('--first-published', type=int)
        parser.add_argument('--candidates')
        parser.add_argument('--year', type=int)
        parser.add_argument('--json', action='store_true', dest='as_json')

    def handle(self, *args, author_died, first_published, candidates, year, as_json, **options):
        year = year or timezone.now().year
        try:
            if candidates:
                data = json.loads(Path(candidates).read_text(encoding='utf-8'))
                rows = [screen(c, year) for c in data['candidates']]
            elif author_died is not None or first_published is not None:
                rows = [screen({'author_died': author_died, 'first_published': first_published}, year)]
            else:
                raise CommandError('Pass --candidates <file> or --author-died/--first-published')
        except (OSError, KeyError, ValueError) as exc:
            raise CommandError(str(exc))
        if as_json:
            self.stdout.write(json.dumps({'screened_for_year': year, 'is_clearance': False, 'rows': rows}, ensure_ascii=False, indent=2))
            return
        codes = list(rows[0]['territory_terms'])
        self.stdout.write('\t'.join(['verdict', 'slug', 'died', 'published'] + codes))
        for row in rows:
            marks = ['PD' if row['territory_terms'][c]['status'] == 'public_domain' else f"until {row['territory_terms'][c].get('expired_end_of', '?')}" for c in codes]
            self.stdout.write('\t'.join([row['verdict'], row.get('slug', '-'), str(row.get('author_died')), str(row.get('first_published'))] + marks))
        self.stdout.write(f'Screened for {year}. Research only: not publication clearance.')
