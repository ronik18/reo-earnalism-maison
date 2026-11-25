"""Attended batch of PRIVATE YouTube uploads for approved `post` review items.

  python manage.py post_approved --provider youtube            # dry run: prints the batch, changes nothing
  python manage.py post_approved --provider youtube --execute  # uploads each item once

Binding scope: this command performs PRIVATE uploads only, through the existing bridge `start` and `upload`
actions. It never calls `publish` and never changes privacy. Making a video public stays an owner action in
YouTube Studio until a public path is separately designed and approved.

Post summary contract (ReviewItem kind='post', status='approved'); every field is required:
  bundle_manifest  repo-relative path to the production bundle manifest JSON
  asset_root       repo-relative directory holding the bundle assets
  destination_key  bridge destination key 'youtube:<account_id>' (must name a youtube destination in the manifest)
  account_id       YouTube channel id; must equal the account in destination_key
  post_id          stable post identifier, recorded in the authority reference and the audit event
Paths resolve under settings.BASE_DIR; absolute or escaping paths are refused. An item missing a field, or
failing a check, gets a per-item error and is left untouched; the rest of the batch continues.

Receipt: `summary["receipt"]` = {video_id, upload_completed} as the bridge returns it, plus `summary["posted_at"]`
(ISO UTC). An item with a receipt is skipped on later runs. The token comes from EARNALISM_YOUTUBE_ACCESS_TOKEN,
is read once, kept in memory, and never logged or stored. The operation journal lives under
MAISON_SOCIAL_JOURNAL_DIR (setting or env, default .local/social-journal), so a re-run never starts a duplicate
upload.
"""
import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.services import audit
from operations.models import ReviewItem
from operations.production_journal import OperationJournal
from operations.social_delivery import Authority, Delivery, DeliveryError, prepare

PROVIDERS = ('youtube',)
TOKEN_ENV = 'EARNALISM_YOUTUBE_ACCESS_TOKEN'
# The only protocol actions a private upload needs. 'publish' is never granted.
UPLOAD_ACTIONS = ('start', 'upload')
REQUIRED = ('bundle_manifest', 'asset_root', 'destination_key', 'account_id', 'post_id')


def _inside(ref):
    if not isinstance(ref, str) or not ref or Path(ref).is_absolute():
        return None
    root = Path(settings.BASE_DIR).resolve()
    path = (root / ref).resolve()
    return path if path.is_relative_to(root) else None


def _journal_dir():
    configured = getattr(settings, 'MAISON_SOCIAL_JOURNAL_DIR', None) or os.environ.get('MAISON_SOCIAL_JOURNAL_DIR')
    path = Path(configured or Path(settings.BASE_DIR) / '.local' / 'social-journal')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _check(item):
    """Return (fields, error); a non-None error leaves the item untouched."""
    summary = item.summary or {}
    missing = [k for k in REQUIRED if not isinstance(summary.get(k), str) or not summary[k].strip()]
    if missing:
        return None, 'missing summary fields: ' + ', '.join(missing)
    manifest, root = _inside(summary['bundle_manifest']), _inside(summary['asset_root'])
    if manifest is None or root is None:
        return None, 'bundle_manifest and asset_root must be repo-relative paths inside the repository'
    if not manifest.is_file() or not root.is_dir():
        return None, 'bundle manifest or asset root not found'
    if summary['destination_key'] != 'youtube:' + summary['account_id']:
        return None, 'destination_key must be youtube:<account_id>'
    return {**{k: summary[k] for k in REQUIRED}, 'manifest_path': manifest, 'root_path': root}, None


def make_http():
    return None  # bridge default HTTPS client; tests replace this


class Command(BaseCommand):
    help = ('Upload approved posts as PRIVATE YouTube videos (dry run unless --execute). '
            'Never publishes or changes privacy; making a video public is an owner action in YouTube Studio.')

    def add_arguments(self, parser):
        parser.add_argument('--provider', required=True, help='Only "youtube" is accepted.')
        parser.add_argument('--execute', action='store_true', help='Actually upload (private). Default is a dry run.')

    def handle(self, *args, provider, execute=False, **options):
        if provider not in PROVIDERS:
            raise CommandError(f'Provider {provider!r} is not authorized; only {", ".join(PROVIDERS)} is accepted.')
        items = [i for i in ReviewItem.objects.filter(kind='post', status='approved').order_by('created_at', 'ref')
                 if not (i.summary or {}).get('receipt')]
        token = None
        if execute:
            token = os.environ.get(TOKEN_ENV, '').strip()
            if not token:
                raise CommandError(f'{TOKEN_ENV} is not set; nothing was uploaded.')
        checked = [(i, *_check(i)) for i in items]
        failures = 0
        for item, fields, error in checked:
            if error:
                failures += 1
                self.stderr.write(f'{item.ref}: REFUSED - {error}')
            elif not execute:
                self.stdout.write(f"{item.ref}\tWOULD UPLOAD (private)\t{fields['destination_key']}\t{fields['bundle_manifest']}")
        if not execute:
            self.stdout.write(f'Dry run: {sum(1 for c in checked if not c[2])} item(s) would upload privately; nothing changed.')
            return
        done = 0
        for item, fields, error in checked:
            if error:
                continue
            try:
                receipt = self._upload(item, fields, token)
                done += 1
                self.stdout.write(f"{item.ref}\tUPLOADED (private)\t{receipt['video_id']}")
            except Exception as exc:  # one bad item must not stop the batch; report the code, never details
                failures += 1
                self.stderr.write(f'{item.ref}: FAILED - {getattr(exc, "code", None) or type(exc).__name__}')
        self.stdout.write(f'{done} uploaded privately; {failures} refused or failed.')
        if failures:
            raise CommandError(f'{failures} item(s) were not uploaded; see messages above.')

    def _upload(self, item, fields, token):
        manifest = json.loads(fields['manifest_path'].read_text())
        plan = prepare(manifest, fields['root_path'])
        key = fields['destination_key']
        if not any(d['key'] == key for d in plan['destinations']):
            raise DeliveryError('destination_not_in_bound_manifest')
        journal = OperationJournal(_journal_dir())
        reference = f"post_approved:{fields['post_id']}:{item.sha256}"

        def authorize(authority, plan_, destination, action):
            return (action in UPLOAD_ACTIONS and authority.actions == frozenset([action])
                    and authority.destination_key == key and authority.account_id == fields['account_id']
                    and authority.candidate_sha256 == plan_['candidate_sha256'])

        delivery = Delivery(plan, journal, lambda platform, account: token, authorize, http=make_http())
        result = None
        for action in UPLOAD_ACTIONS:
            authority = Authority(plan['candidate_sha256'], key, fields['account_id'], frozenset([action]), reference)
            result = delivery.run(key, action, execute=True, authority=authority)
        if result.get('upload_completed') is not True or not result.get('video_id'):
            raise DeliveryError('upload_not_confirmed')
        receipt = {'video_id': result['video_id'], 'upload_completed': True}
        with transaction.atomic():
            item = ReviewItem.objects.select_for_update().get(pk=item.pk)
            item.summary = {**item.summary, 'receipt': receipt, 'posted_at': timezone.now().isoformat()}
            item.save(update_fields=['summary'])
            audit(None, 'social.upload_private', item, {'post_id': fields['post_id'], 'destination_key': key,
                  'video_id': receipt['video_id'], 'candidate_sha256': plan['candidate_sha256']})
        return receipt
