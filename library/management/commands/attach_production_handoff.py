"""Attach a source-bound production bundle to one existing private draft."""
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Attach measured media/maps and private evidence to an existing draft; never publish. Default prepare-only."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--asset-root", required=True)
        parser.add_argument("--staging-receipt")
        parser.add_argument("--actor-email")
        parser.add_argument("--expected-etag")
        parser.add_argument("--operation-id")
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args, **options):
        from library.production_handoff import attach_private, prepare_handoff
        def bounded(path):
            with Path(path).open("rb") as source:
                raw = source.read(1048577)
            if len(raw) > 1048576:
                raise CommandError("A private JSON input is larger than1MiB.")
            return json.loads(raw)
        try:
            manifest = bounded(options["manifest"])
            if not options["execute"]:
                result = prepare_handoff(manifest, options["asset_root"])
            else:
                from django.contrib.auth import get_user_model
                required = ("staging_receipt", "actor_email", "expected_etag", "operation_id")
                if not all(options.get(k) for k in required):
                    raise CommandError("Execute requires staging receipt, verified actor, current ETag and operation ID.")
                actor = get_user_model().objects.filter(email__iexact=options["actor_email"]).first()
                if actor is None:
                    raise CommandError("A verified permitted publisher is required.")
                result = attach_private(manifest, options["asset_root"], bounded(options["staging_receipt"]),
                    actor, options["expected_etag"], options["operation_id"], execute=True)
        except CommandError:
            raise
        except Exception as exc:
            # Private provider/JSON exception messages are not copied into command logs.
            raise CommandError("Private handoff failed: " + type(exc).__name__) from None
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
