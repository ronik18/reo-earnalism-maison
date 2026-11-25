"""Export editor-revised translations for licensing partners as UTF-8 CSV.

  python manage.py licensing_catalogue --out catalogue.csv [--replace]
"""
import csv
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from library.licensing import COLUMNS, licensing_rows


class Command(BaseCommand):
    help = 'Licensing catalogue CSV of live, editor-revised translations (never AI-only).'

    def add_arguments(self, parser):
        parser.add_argument('--out', required=True)
        parser.add_argument('--replace', action='store_true')

    def handle(self, *args, out, replace, **options):
        path = Path(out)
        if path.exists() and not replace:
            raise CommandError(f'{path} exists; pass --replace to overwrite.')
        rows = licensing_rows()
        tmp = path.with_name(path.name + '.tmp')
        try:
            with tmp.open('w', encoding='utf-8', newline='') as fh:
                writer = csv.DictWriter(fh, fieldnames=COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            os.replace(tmp, path)  # a failed write leaves any previous export intact
        finally:
            tmp.unlink(missing_ok=True)
        self.stdout.write(f'{len(rows)} editions written to {path}')
