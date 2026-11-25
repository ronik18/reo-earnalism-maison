"""Owner cover pair into an intake packet; cover_provenance.json is queued on the Monday review page."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.api import DomainError
from operations import review
from operations.intake import covers


class Command(BaseCommand):
    help = "Fetch the owner's Cloudinary front/back cover pair into an intake packet with provenance."

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("--front", required=True, help="Cloudinary front public_id")
        parser.add_argument("--back", required=True, help="Cloudinary back public_id")
        parser.add_argument("--folder", default=None, help="default library/intake/<slug>")
        parser.add_argument("--replace", action="store_true")
        parser.add_argument("--owner-statement-date", default=covers.DEFAULT_OWNER_STATEMENT["date"])
        parser.add_argument("--owner-statement-text", default=covers.DEFAULT_OWNER_STATEMENT["text"])
        parser.add_argument("--basis", default=covers.DEFAULT_BASIS)

    def handle(self, *args, **options):
        slug = options["slug"]
        folder = options["folder"] or f"library/intake/{slug}"
        provenance_path = Path(folder) / "cover_provenance.json"
        try:
            review.review_ref(provenance_path)  # refuse before fetching or writing anything unqueueable
        except DomainError as error:
            raise CommandError(f"{error.code}: {error.message}") from error
        try:
            provenance = covers.build_packet(
                slug, options["front"], options["back"], folder,
                replace=options["replace"],
                owner_statement={
                    "date": options["owner_statement_date"],
                    "text": options["owner_statement_text"],
                },
                basis=options["basis"],
            )
        except covers.CoverError as exc:
            raise CommandError(f"{exc.code}: {exc.detail}") from exc
        manifest = Path(folder) / "manifest.json"
        try:
            title = json.loads(manifest.read_text(encoding="utf-8"))["edition"]["title"]
        except (OSError, ValueError, KeyError, TypeError):
            title = slug
        item, = review.queue_files([("cover", provenance_path, {"edition_slug": slug, "title": title})])
        self.stdout.write(json.dumps({"slug": slug, "folder": folder, "status": provenance["status"], "review_item": str(item.pk)}))
