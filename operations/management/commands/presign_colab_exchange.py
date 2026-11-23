"""Sign one short-lived, single-object R2 URL for an Earnalism Colab exchange (owner-approved, 23 Nov 2026).

  presign_colab_exchange --key exports/colab-exchange/<title>/<job_id>/inputs.zip --method GET [--ttl-seconds N]
  presign_colab_exchange --key exports/colab-exchange/<title>/<job_id>/outputs.tar --method PUT \
      --content-type application/x-tar [--ttl-seconds N]

Prints exactly one JSON line on stdout: {"key", "method", "url", "headers", "expires_at"}. The URL is a
capability: paste it only into `eav.cli exchange-stage --signed <file>` (which writes the job's
exchange.json); never into a commit, a ticket or record.json. An audit line without the URL goes to stderr.

Only the exchange prefix is signable: the key must fullmatch
exports/colab-exchange/<title>/<job_id>/(inputs.zip|outputs.tar); GET is allowed only for inputs.zip
(read client) and PUT only for outputs.tar (upload client, Content-Type application/x-tar signed into
the request). TTL defaults to 21600 s (6 h) and is capped at 86400 s. Uses library.storage's configured
private R2 client and settings.R2_PRIVATE_BUCKET; refuses when private storage is not R2. Run it where
the R2 credentials live (a Render one-off job); it never uploads, lists or deletes anything.
"""
import json
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.api import DomainError
from library import storage

KEY = re.compile(r"exports/colab-exchange/[a-z0-9-]+/[a-z0-9-]+/(inputs\.zip|outputs\.tar)")
METHOD_FOR = {"inputs.zip": "GET", "outputs.tar": "PUT"}
CONTENT_TYPE = {"inputs.zip": "application/zip", "outputs.tar": "application/x-tar"}
DEFAULT_TTL, MAX_TTL = 21600, 86400
log = logging.getLogger("maison.operations.colab_exchange")


class Command(BaseCommand):
    help = "Sign one GET (inputs.zip) or PUT (outputs.tar) URL for a Colab job's R2 exchange."

    def add_arguments(self, parser):
        parser.add_argument("--key", required=True)
        parser.add_argument("--method", required=True, choices=("GET", "PUT"))
        parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL)
        parser.add_argument("--content-type")

    def handle(self, *args, key, method, ttl_seconds, content_type, **options):
        match = KEY.fullmatch(key or "")
        if not match:
            raise CommandError("Refused: the key must be exports/colab-exchange/<title>/<job_id>/"
                               "(inputs.zip|outputs.tar) with lowercase letters, digits and hyphens.")
        name = match.group(1)
        if METHOD_FOR[name] != method:
            raise CommandError(f"Refused: {name} is signed only for {METHOD_FOR[name]}, not {method}.")
        expected_type = CONTENT_TYPE[name]
        if content_type is not None and content_type != expected_type:
            raise CommandError(f"Refused: the content type of {name} is {expected_type}, not {content_type!r}.")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= MAX_TTL:
            raise CommandError(f"Refused: ttl-seconds must be 1..{MAX_TTL} (default {DEFAULT_TTL}).")
        try:
            if not storage.is_r2():
                raise CommandError("Refused: private storage is not R2 here; sign where the R2 credentials live.")
            params = {"Bucket": settings.R2_PRIVATE_BUCKET, "Key": key}
            headers = {}
            if method == "PUT":
                params["ContentType"] = expected_type
                headers = {"Content-Type": expected_type}
            # Expiry is computed before signing, so the recorded expiry is never later than the real one.
            expires_at = timezone.now() + timedelta(seconds=ttl_seconds)
            client = storage._client(upload=method == "PUT")
            url = storage._provider_call(client.generate_presigned_url,
                                         "get_object" if method == "GET" else "put_object",
                                         Params=params, ExpiresIn=ttl_seconds, HttpMethod=method)
        except DomainError as exc:
            raise CommandError(f"Refused: {exc.message if hasattr(exc, 'message') else exc}") from None
        audit = f"presigned {method} {key} ttl={ttl_seconds}s expires_at={expires_at.isoformat()}"
        log.info(audit)
        self.stderr.write(audit)
        self.stdout.write(json.dumps({"key": key, "method": method, "url": url, "headers": headers,
                                      "expires_at": expires_at.isoformat()}, sort_keys=True))
