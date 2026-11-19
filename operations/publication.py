"""Execute an actor/revision-bound scheduled release through normal publication.

The scheduling action owns consent and creates the durable outbox entry. This
handler cannot infer an actor, upgrade a draft, or bypass current release checks.
Private asset verification precedes the short publication/audit transaction.
"""
import re
import uuid

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.api import DomainError
from core.services import audit
from library.models import Revision
from library import services


def process_scheduled_publication(job):
    data = job.payload
    try:
        revision_id = uuid.UUID(data['revision_id'])
        actor_id = int(data['actor_id'])
        version = data['expected_version']
        sha = data['expected_sha256']
        due = parse_datetime(data['scheduled_for'])
        reason = data['reason']
        valid = (job.kind == 'scheduled_publication' and job.actor_id == actor_id
                 and actor_id > 0 and type(version) is int and version > 0
                 and isinstance(sha, str) and re.fullmatch(r'[a-f0-9]{64}', sha)
                 and due is not None and timezone.is_aware(due)
                 and isinstance(reason, str) and 0 < len(reason.strip()) <= 1000
                 and job.dedupe_key == f'scheduled-publication:{revision_id}:{version}')
        if not valid:
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise DomainError('scheduled_publication_invalid', 'Scheduled release needs staff review.', 409) from None

    def matches(revision):
        return (revision.state == 'ready' and revision.version == version
                and revision.content_sha256 == sha and revision.scheduled_for == due)

    revision = Revision.objects.filter(pk=revision_id).first()
    if revision is None or not matches(revision):
        return {'status': 'skipped', 'reason': 'revision_superseded'}
    if due > timezone.now():
        raise DomainError('scheduled_publication_invalid', 'Scheduled release is not due.', 409)
    user = get_user_model().objects.filter(pk=actor_id).first()
    if (user is None or not user.is_active or not user.is_verified or not user.is_staff
            or not user.has_perm('library.publish_revision')):
        raise DomainError('scheduled_publication_held', 'Scheduled publisher authority changed.', 409)

    try:
        prepared = services.prepare_revision_validation(revision)
        with transaction.atomic():
            # Match the existing staff-mutation lock order: actor, edition, revision.
            user = get_user_model().objects.select_for_update().get(pk=actor_id)
            if not user.is_verified:
                raise DomainError('scheduled_publication_held', 'Scheduled publisher authority changed.', 409)
            current = Revision.objects.get(pk=revision_id)
            if not matches(current):
                return {'status': 'skipped', 'reason': 'revision_superseded'}
            result = services.transition_revision(user, revision_id, 'publish', version, sha,
                                                  reason, prepared=prepared)
            audit(user, 'content.publish', current, {'reason': reason, 'sha256': sha,
                                                     'scheduled_job_id': str(job.id)})
            return {'status': 'published', 'edition_revision_id': str(revision_id),
                    'version': result['version']}
    except DomainError as error:
        if error.code in {'version_conflict', 'invalid_transition'}:
            return {'status': 'skipped', 'reason': 'revision_superseded'}
        if error.code in {'publication_not_ready', 'permission_denied'}:
            raise DomainError('scheduled_publication_held', 'Scheduled release requires staff review.', 409) from None
        raise
