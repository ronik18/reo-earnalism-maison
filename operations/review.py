"""Monday review queue: the owner approves a week's items in one sitting.

File-backed kinds (clearance, cover, edition) carry `ref` = repo-relative path and `sha256` = that file's hash;
`decide` re-hashes the file (relative to settings.BASE_DIR) and refuses REVIEW_ITEM_CHANGED if it moved on.
`post` items have a `social/<slug>/<post-id>` key and no file: their `summary` carries `edition_slug` and the
payload `sha256`, and the re-hash is skipped for them.

Standing permission (settings.MAISON_REVIEW_STANDING_FROM, two months after the first batch) may auto-approve
only `post` items for editions with an approved clearance that pass every automatic check.
"""
import hashlib
import re
from datetime import timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.api import DomainError
from core.services import audit
from .models import ReviewItem

KINDS = {k for k, _ in ReviewItem.KINDS}


def standing_permission_active(now):
    value = getattr(settings, 'MAISON_REVIEW_STANDING_FROM', None)
    if isinstance(value, str):
        value = parse_datetime(value) if value.strip() else None
    if not value:
        return False
    if timezone.is_naive(value):
        value = value.replace(tzinfo=dt_timezone.utc)
    return now >= value


def auto_checks(item):
    """Failure codes for standing approval; an empty list means every check passes."""
    if item.kind != 'post':
        return ['NOT_ELIGIBLE_FOR_STANDING']
    summary = item.summary or {}
    failures = []
    slug = summary.get('edition_slug')
    if not slug or not ReviewItem.objects.filter(kind='clearance', status='approved', summary__edition_slug=slug).exists():
        failures.append('EDITION_NOT_CLEARED')
    if not summary.get('cover_sha256'):
        failures.append('NO_OWNER_COVER')
    if summary.get('exact_words') is not True:
        failures.append('NOT_EXACT_WORDS')
    # Fail closed: a missing flag never passes. `ai` must be explicitly False, or AI must be labelled.
    if summary.get('ai') is not False and summary.get('ai_labelled') is not True:
        failures.append('AI_NOT_LABELLED')
    if 'claims' not in summary or summary['claims']:
        failures.append('HAS_CLAIMS')
    return failures


def _resolve(ref):
    root = Path(settings.BASE_DIR).resolve()
    path = (root / ref).resolve()
    if Path(ref).is_absolute() or not path.is_relative_to(root):
        return None
    return path


def _file_sha256(ref):
    path = _resolve(ref)
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def queue(kind, ref, sha256, summary):
    if kind not in KINDS:
        raise ValueError(f'Unknown review kind {kind!r}')
    if not re.fullmatch(r'[0-9a-f]{64}', sha256 or ''):
        raise DomainError('REVIEW_HASH_INVALID', 'sha256 must be 64 lowercase hex characters.', 400)
    if kind != 'post':
        if _resolve(ref) is None:
            raise DomainError('REVIEW_REF_INVALID', 'ref must be a repo-relative path inside the repository.', 400)
        if _file_sha256(ref) != sha256:
            raise DomainError('REVIEW_HASH_INVALID', 'sha256 does not match the file now.', 400)
    with transaction.atomic():
        item, created = ReviewItem.objects.get_or_create(kind=kind, ref=ref, sha256=sha256, defaults={'summary': summary})
        if created:
            for old in ReviewItem.objects.filter(kind=kind, ref=ref, status='pending').exclude(pk=item.pk):
                old.status, old.decision_note, old.decided_at = 'rejected', 'superseded', timezone.now()
                old.save(update_fields=['status', 'decision_note', 'decided_at'])
                audit(None, 'review.decided', old, {'decision': 'rejected', 'superseded_by': str(item.pk), 'kind': kind, 'ref': ref})
        if created and kind == 'post':
            now = timezone.now()
            if standing_permission_active(now) and not auto_checks(item):
                item.status, item.standing, item.decided_at = 'approved', True, now
                item.save(update_fields=['status', 'standing', 'decided_at'])
                audit(None, 'review.decided', item, {'decision': 'approved', 'standing': True, 'kind': kind, 'ref': ref})
    return item


def decide(actor, item_ids, decision, note=''):
    if decision not in ('approved', 'rejected'):
        raise DomainError('INVALID_DECISION', 'Decision must be approved or rejected.', 400)
    if not (actor and actor.is_active and actor.is_staff and actor.is_verified and actor.has_perm('operations.decide_review')):
        raise DomainError('ACCESS_DENIED', 'Reviewing needs a verified staff account with review permission.', 403)
    done = 0
    with transaction.atomic():
        items = list(ReviewItem.objects.select_for_update().filter(pk__in=item_ids, status='pending').order_by('created_at'))
        if decision == 'approved':  # rejecting never needs the file; only approval is bound to its exact bytes
            changed = [i.ref for i in items if i.kind != 'post' and _file_sha256(i.ref) != i.sha256]
            if changed:
                raise DomainError('REVIEW_ITEM_CHANGED', 'Changed or missing since queued: ' + ', '.join(changed), 409, details={'refs': changed})
        for item in items:
            item.status, item.decided_by, item.decided_at, item.decision_note = decision, actor, timezone.now(), (note or '')[:2000]
            item.save(update_fields=['status', 'decided_by', 'decided_at', 'decision_note'])
            audit(actor, 'review.decided', item, {'decision': decision, 'kind': item.kind, 'ref': item.ref, 'sha256': item.sha256})
            done += 1
    return done
