import json

from django.core.management.base import BaseCommand, CommandError

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
        self.stdout.write(json.dumps({"slug": slug, "folder": folder, "status": provenance["status"]}))
