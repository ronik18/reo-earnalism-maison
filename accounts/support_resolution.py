"""Privileged operator bookkeeping, not an HTTP endpoint or SMTP confirmation.

Authorization is access to the existing authenticated provider/management shell.
The active staff identifier attributes the action; it does not prove browser MFA.
No support content, recipient addresses or credentials are emitted or copied.
"""
import re
import uuid

from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from core.models import AuditEvent, OutboxJob
from .models import User
from .retention import _row_held, _support_case, _support_submitted


def resolve_support_case(*, operator_id, job_id, resolution_ref,
                         apply=False, obligations_reviewed=False):
    if type(apply) is not bool or type(obligations_reviewed) is not bool:
        raise CommandError('Apply and obligation-review flags must be boolean.')
    if not isinstance(resolution_ref, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', resolution_ref):
        raise CommandError('Use an opaque resolution reference:1–80 letters, digits, dots, underscores or hyphens; no message text or URLs.')
    try:
        operator_id, job_id = uuid.UUID(str(operator_id)), uuid.UUID(str(job_id))
    except (ValueError, TypeError):
        raise CommandError('Operator and job identifiers must be UUIDs.') from None
    with transaction.atomic():
        operator = User.objects.select_for_update().filter(
            public_id=operator_id, is_staff=True, is_active=True).first()
        if operator is None:
            raise CommandError('An existing active staff operator is required.')
        job = OutboxJob.objects.select_for_update(skip_locked=True).filter(
            pk=job_id, kind='contact_support').first()
        if job is None:
            raise CommandError('The exact support case is unavailable or busy; no changes made.')
        if _row_held(job):
            raise CommandError('The support case is held; preserve it until a separate authorized hold review.')
        metadata = _support_case(job)
        if metadata:
            case, _ = metadata
            if case['resolution_ref'] != resolution_ref:
                raise CommandError('The case already has a different resolution reference; its retention clock is unchanged.')
            return {'dry_run': not apply, 'job_id': str(job.id), 'already_resolved': True,
                    'resolved_at': case['resolved_at'], 'resolution_ref': resolution_ref,
                    'changed': False, 'mailbox_modified': False}
        if isinstance(job.result, dict) and job.result.get('retention_case') is not None:
            raise CommandError('Existing resolution metadata requires operator review; it was not replaced.')
        if not _support_submitted(job):
            raise CommandError('Only a known submitted support case can be resolved; pending or uncertain delivery is preserved.')
        result = {'dry_run': not apply, 'job_id': str(job.id), 'operator_id': str(operator.public_id),
                  'resolution_ref': resolution_ref, 'already_resolved': False,
                  'changed': False, 'mailbox_modified': False,
                  'requires_obligation_review': not obligations_reviewed}
        if not apply:
            return result
        if not obligations_reviewed:
            raise CommandError('Confirm actual resolution and no outstanding dispute/legal/financial obligation with --no-outstanding-obligation before applying.')
        stamp = timezone.now().isoformat().replace('+00:00', 'Z')
        case = {'schema_version': 1, 'resolved_at': stamp,
                'resolved_by': str(operator.public_id), 'resolution_ref': resolution_ref,
                'obligations_reviewed': True}
        job.result = {**job.result, 'retention_case': case}
        job.save(update_fields=['result'])
        AuditEvent.objects.create(actor=operator, action='support.resolved', entity_kind='OutboxJob',
                                  entity_id=str(job.id), detail={'resolution_ref': resolution_ref})
        result.update(changed=True, resolved_at=stamp)
        return result
