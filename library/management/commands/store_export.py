"""python manage.py store_export play-books <edition-slug> --out <dir>  (local bundle; no network)."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.api import DomainError
from library.models import Edition
from library.store_export import export_play_books


class Command(BaseCommand):
    help = 'Write a local store export bundle for a live edition.'

    def add_arguments(self, parser):
        parser.add_argument('store', choices=['play-books'])
        parser.add_argument('slug')
        parser.add_argument('--out', required=True)

    def handle(self, *args, slug, out, **options):
        edition = Edition.objects.filter(slug=slug).first()
        if edition is None:
            raise CommandError(f'No edition {slug!r}.')
        path = Path(out)
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            raise CommandError(f'{out} exists and is not an empty directory.')
        try:
            manifest = export_play_books(edition.pk, path)
        except DomainError as exc:
            raise CommandError(f'{exc.code}: {exc.message}') from exc
        self.stdout.write(f'Wrote {len(manifest["chapters"])} chapters for {slug} to {out}.')
