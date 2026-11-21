"""Bounded, preview-first housekeeping for the owner-approved retention windows.

No provider calls, financial/publication audit deletion, or blanket account purge.
"""
import time
from datetime import timedelta
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from core.models import AuditEvent, OperationReceipt, OutboxJob
from .models import User, Preferences, Consent, Device, EmailActionToken


def _held(user_id):
    # Conservative compatibility with recorded internal audit markers; this is
    # not a hold creation/release API and markers are never auto-released.
    if not user_id:
        return False
    return AuditEvent.objects.filter(action__in=['legal.hold', 'retention.hold']).filter(
        Q(actor_id=user_id) | Q(entity_kind='User', entity_id=str(user_id))).exists()


# Only existing routine authentication outcomes are eligible. New actions do not
# silently inherit a deletion policy; publication/rights/finance/privacy/consent
# records and hold markers are deliberately outside this allowlist. The exact
# password-purpose security receipt has a separate schema-checked180-day policy.
SECURITY_AUDIT_RETENTION_DAYS = 180

ROUTINE_SECURITY_ACTIONS = frozenset({
    'account.registered', 'account.email_verified', 'account.password_reset',
    'device.revoked', 'staff.mfa_enrolled', 'staff.mfa_recovery_used',
})


PASSWORD_PURPOSE_AUDIT_ACTION = 'password.purpose_consented'


def _password_purpose_receipt(row):
    """Only the exact bounded password security receipt inherits180-day expiry."""
    from .password_consent import PASSWORD_PURPOSE_VERSION, PASSWORD_PURPOSES
    detail = row.detail
    if (row.action != PASSWORD_PURPOSE_AUDIT_ACTION or row.entity_kind != 'User'
            or not isinstance(detail, dict)
            or set(detail) != {'purpose', 'notice_version', 'affirmative', 'collected_at'}
            or detail.get('purpose') not in PASSWORD_PURPOSES
            or detail.get('notice_version') != PASSWORD_PURPOSE_VERSION
            or detail.get('affirmative') is not True
            or not isinstance(detail.get('collected_at'), str)):
        return False
    try:
        stamp = parse_datetime(detail['collected_at'])
    except (ValueError, TypeError):
        return False
    if not stamp or timezone.is_naive(stamp) or stamp > row.created_at:
        return False
    # Abandoned/deleted accounts become null actors; the validated exact receipt
    # still expires180days after its event, subject to entity/row hold markers.
    return (row.entity_id == str(row.actor_id) if row.actor_id is not None
            else row.entity_id.isdigit() and int(row.entity_id) > 0)


def _row_held(row, *, actor_held=None, held_targets=None):
    if (_held(row.actor_id) if actor_held is None else actor_held):
        return True
    for field in ('payload', 'result', 'detail'):
        value = getattr(row, field, {})
        if not isinstance(value, dict) or value.get('retention_hold') or value.get('legal_hold'):
            return True
    identities={(type(row).__name__,str(row.pk))}
    targets = Q(entity_kind=type(row).__name__, entity_id=str(row.pk))
    if isinstance(row, AuditEvent):
        identities.add((row.entity_kind,row.entity_id))
        targets |= Q(entity_kind=row.entity_kind, entity_id=row.entity_id)
    if held_targets is not None:return bool(identities & held_targets)
    return AuditEvent.objects.filter(action__in=['legal.hold', 'retention.hold']).filter(targets).exists()


def _support_case(job):
    """Return validated operator resolution metadata, never infer it from SMTP."""
    import re
    import uuid
    if not isinstance(job.result, dict):
        return None
    case = job.result.get('retention_case')
    if (not isinstance(case, dict) or set(case) != {'schema_version', 'resolved_at', 'resolved_by', 'resolution_ref', 'obligations_reviewed'}
            or type(case.get('schema_version')) is not int or case.get('schema_version') != 1
            or case.get('obligations_reviewed') is not True):
        return None
    stamp = case.get('resolved_at')
    if not isinstance(stamp, str):
        return None
    try:
        resolved_at = parse_datetime(stamp)
        uuid.UUID(str(case.get('resolved_by')))
    except (ValueError, TypeError):
        return None
    if not resolved_at or timezone.is_naive(resolved_at):
        return None
    reference = case.get('resolution_ref')
    if not isinstance(reference, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', reference):
        return None
    return case, resolved_at


def _support_submitted(job):
    return (job.kind == 'contact_support' and job.status == 'done'
            and isinstance(job.payload, dict) and isinstance(job.result, dict)
            and job.payload.get('email_outcome') != 'unknown'
            and job.result.get('status') == 'submitted'
            and job.result.get('smtp_submission_accepted') is True)


def _terminal_mail(job):
    # SMTP timeout after DATA is uncertain even when retries eventually stop.
    if _held(job.actor_id):
        return False
    if job.status not in ('done', 'cancelled'):
        return False
    if job.payload.get('retention_hold') or job.payload.get('legal_hold'):
        return False
    if job.payload.get('email_outcome') in ('unknown', 'submitting'):
        return job.status == 'done' and job.result.get('status') == 'submitted'
    return True


def _abandoned(user, cutoff):
    if (user.is_verified or user.is_staff or user.is_superuser or not user.is_active
        or user.last_login or user.date_joined > cutoff or user.version != 1
        or user.session_epoch != 1):
        return False
    if EmailActionToken.objects.filter(user=user).filter(
        Q(created_at__gt=cutoff) | (Q(expires_at__gt=cutoff) & (Q(consumed_at=None) | Q(consumed_at__gt=cutoff)))
    ).exists():
        return False
    for event in AuditEvent.objects.filter(actor=user).exclude(action='account.registered'):
        if (event.action=='account.capacity_declared' and event.entity_kind=='User' and event.entity_id==str(user.pk)
            and event.detail=={'purpose':'registration','account_capacity':'adult','account_notice_version':'india-account-v1','account_terms_consent':True,'assurance':'self_declaration'}
            and event.created_at<=user.date_joined+timedelta(minutes=5)):
            continue
        if (not _password_purpose_receipt(event) or event.detail['purpose'] != 'registration'
                or event.created_at > user.date_joined + timedelta(minutes=5)):
            return False
    if any(not _terminal_mail(j) for j in OutboxJob.objects.filter(actor=user)):
        return False
    if OutboxJob.objects.filter(actor=user).exclude(kind='email_action').exists():
        return False
    # Only untouched registration scaffolding may cascade. Every other known or
    # future FK/M2M relationship conservatively means activity or an obligation.
    allowed = {Preferences, Consent, EmailActionToken, OutboxJob, AuditEvent}
    from django.apps import apps
    if apps.is_installed('allauth.account'):
        from allauth.account.models import EmailAddress
        # One unverified primary address is registration scaffolding, not activity.
        # A verified/secondary/different address remains evidence and blocks cleanup.
        if EmailAddress.objects.filter(user=user).exclude(email=user.email,verified=False,primary=True).exists():return False
        allowed.add(EmailAddress)
    for rel in User._meta.related_objects:
        if rel.related_model in allowed:
            continue
        if rel.related_model._default_manager.filter(**{rel.field.name: user}).exists():
            return False
    if user.groups.exists() or user.user_permissions.exists():
        return False
    initial = user.date_joined + timedelta(minutes=5)
    if Preferences.objects.filter(user=user).filter(Q(version__gt=1) | Q(updated_at__gt=initial)).exists():
        return False
    if Consent.objects.filter(user=user).filter(Q(version__gt=1) | Q(updated_at__gt=initial)).exists():
        return False
    return True


def _cleanup_account_retention(limit=100, max_seconds=5, dry_run=True, cursors=None):
    """Each category examines at most ``limit`` rows, with per-row lock/recheck.

    Preview performs no writes. Mail payloads are scrubbed, leaving a nonsecret
    outcome; uncertain/pending delivery is never discarded. Account deletion is
    restricted to untouched abandoned signup scaffolding, not existing members.
    """
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('limit must be1–1000')
    if not 0 < max_seconds <= 30 or type(dry_run) is not bool:
        raise ValueError('require a positive time budget<=30 and boolean dry_run')
    now = timezone.now(); cutoff = now - timedelta(days=7)
    deadline = time.monotonic() + max_seconds
    counts = dict(guardian_accounts_suspended=0, guardian_authorizations=0, action_tokens=0, mail_payloads=0, sessions=0, devices=0, receipts=0, abandoned_signups=0, audit_outcomes=0, support_payloads=0)
    report = {'dry_run': dry_run, 'eligible': counts, 'time_budget_exhausted': False}

    cursors = cursors if cursors is not None else {}

    def ids(query, category):
        cursor = cursors.get(category)
        if cursor is not None:
            query = query.filter(pk__gt=cursor)
        rows = list(query.order_by('pk').values_list('pk', flat=True)[:limit + 1])
        for pk in rows[:limit]:
            if not remaining(): return
            # Advance over examined rows as well as eligible rows. A hold or
            # locked worker must not starve every suffix on subsequent runs.
            cursors[category] = str(pk)
            yield pk
        if len(rows) <= limit:
            cursors[category] = None


    def remaining():
        if time.monotonic() >= deadline:
            report['time_budget_exhausted'] = True
            return False
        return True

    old_action = Q(expires_at__lte=cutoff) | Q(consumed_at__lte=cutoff)
    for pk in ids(EmailActionToken.objects.filter(old_action), 'actions'):
        if not remaining(): break
        with transaction.atomic():
            action = EmailActionToken.objects.select_for_update(skip_locked=True).filter(pk=pk).filter(old_action).first()
            if not action or _held(action.user_id): continue
            jobs = list(OutboxJob.objects.select_for_update(skip_locked=True).filter(kind='email_action', payload__action_id=str(action.pk)))
            # Don't race a worker holding a job lock; compare before accepting.
            if len(jobs) != OutboxJob.objects.filter(kind='email_action', payload__action_id=str(action.pk)).count(): continue
            if any(not _terminal_mail(j) for j in jobs): continue
            counts['action_tokens'] += 1
            for job in jobs:
                counts['mail_payloads'] += 1
                if not dry_run:
                    job.payload = {'retention_cleaned': True}
                    job.result = {'status': 'retention_cleaned'}
                    job.error_code = ''; job.save(update_fields=['payload', 'result', 'error_code'])
            if not dry_run: action.delete()

    # Older completed mail rows can outlive an already-removed token (for
    # example an explicit account deletion). Scrub these without touching other
    # job kinds or a pending/uncertain submission.
    for pk in ids(OutboxJob.objects.filter(kind='email_action', status__in=['done', 'cancelled'], completed_at__lte=cutoff).filter(Q(payload__retention_cleaned__isnull=True) | Q(payload__retention_cleaned=False)), 'mail'):
        if not remaining(): break
        with transaction.atomic():
            job = OutboxJob.objects.select_for_update(skip_locked=True).filter(pk=pk).first()
            if not job or not _terminal_mail(job): continue
            action_id = job.payload.get('action_id')
            try:
                action_exists = action_id and EmailActionToken.objects.filter(pk=action_id).exists()
            except (ValueError, ValidationError):
                # Malformed IDs are not enough evidence to discard delivery state.
                continue
            if action_exists: continue
            counts['mail_payloads'] += 1
            if not dry_run:
                job.payload = {'retention_cleaned': True}; job.result = {'status': 'retention_cleaned'}
                job.error_code = ''; job.save(update_fields=['payload', 'result', 'error_code'])

    # Expired account authority stops active managed-device/offline processing
    # without waiting for its separately configured evidence-retention deadline.
    from .guardian import account_available,_revoke_child_sessions
    expired_managed=User.objects.filter(guardian_managed=True,is_active=True,guardian_authorizations_received__purpose='account_processing',guardian_authorizations_received__expires_at__lte=now).distinct()
    for pk in ids(expired_managed,'guardian_expiry'):
        if not remaining(): break
        with transaction.atomic():
            child=User.objects.select_for_update(skip_locked=True).filter(pk=pk,guardian_managed=True).first()
            if not child or account_available(child):continue
            from reader.models import DownloadLicense
            if not Device.objects.filter(user=child,revoked_at=None).exists() and not DownloadLicense.objects.filter(user=child,revoked_at=None).exists():continue
            counts['guardian_accounts_suspended']+=1
            if not dry_run:_revoke_child_sessions(child.pk)

    # Only rows carrying an explicit reviewed retention deadline are eligible.
    # Legacy foundation rows with no deadline require review, never blind erasure.
    from .models import GuardianAuthorization
    for pk in ids(GuardianAuthorization.objects.filter(retain_until__lte=now,expires_at__lte=now), 'guardian_authorizations'):
        if not remaining(): break
        with transaction.atomic():
            row=GuardianAuthorization.objects.select_for_update(skip_locked=True).filter(pk=pk,retain_until__lte=now,expires_at__lte=now).first()
            if not row or _held(row.guardian_id) or row.child_id and _held(row.child_id):continue
            if AuditEvent.objects.filter(action__in=['legal.hold','retention.hold'],entity_kind='GuardianAuthorization',entity_id=str(row.pk)).exists():continue
            from .enrollment import DIRECT_PARENT_METHOD
            proof_events=AuditEvent.objects.none()
            if row.jurisdiction=='IN' and row.method==DIRECT_PARENT_METHOD:
                proof_events=AuditEvent.objects.filter(entity_kind='GuardianAuthorization',entity_id=str(row.pk),action__in=['guardian.electronic_permission','guardian.subject_bound'])
            if any(_row_held(event,actor_held=False) for event in proof_events):continue
            linked=OutboxJob.objects.filter(payload__guardian_authorization_id=str(row.pk))
            if linked.exclude(status__in=['done','cancelled','dead']).exists():continue
            blocked=False
            for job in linked.iterator(chunk_size=100):
                if not remaining() or _row_held(job,actor_held=False):
                    blocked=True;break
            if blocked:continue
            counts['guardian_authorizations']+=1
            if not dry_run:
                proof_events.update(detail={'retention_cleaned':True})
                row.delete()

    candidates = User.objects.filter(is_verified=False, is_staff=False, is_superuser=False, is_active=True, last_login=None, date_joined__lte=cutoff)
    for pk in ids(candidates, 'signups'):
        if not remaining(): break
        with transaction.atomic():
            user = User.objects.select_for_update(skip_locked=True).filter(pk=pk).first()
            if not user or not _abandoned(user, cutoff): continue
            # Preserve even registration audits and all mail outcome rows; ensure
            # no email material survives their actor's deletion.
            jobs = list(OutboxJob.objects.select_for_update(skip_locked=True).filter(actor=user))
            if len(jobs) != OutboxJob.objects.filter(actor=user).count(): continue
            counts['abandoned_signups'] += 1
            if not dry_run:
                for job in jobs:
                    job.payload = {'retention_cleaned': True}; job.result = {'status': 'retention_cleaned'}
                    job.error_code = ''; job.save(update_fields=['payload', 'result', 'error_code'])
                user.delete()

    for pk in ids(Session.objects.filter(expire_date__lte=now), 'sessions'):
        if not remaining(): break
        with transaction.atomic():
            session = Session.objects.select_for_update(skip_locked=True).filter(pk=pk, expire_date__lte=now).first()
            if not session: continue
            if any(_held(user_id) for user_id in Device.objects.filter(session=session).values_list('user_id', flat=True)): continue
            counts['sessions'] += 1
            if not dry_run: session.delete()
    for pk in ids(Device.objects.filter(expires_at__lte=now), 'devices'):
        if not remaining(): break
        with transaction.atomic():
            device = Device.objects.select_for_update(skip_locked=True).filter(pk=pk, expires_at__lte=now).first()
            if not device or _held(device.user_id): continue
            # Preserve downloads/security references instead of cascading them.
            if any(rel.related_model._default_manager.filter(**{rel.field.name: device}).exists() for rel in Device._meta.related_objects): continue
            counts['devices'] += 1
            if not dry_run: device.delete()
    # Do not trust a malformed earlier expires_at to shorten the35-day replay contract.
    receipt_cutoff = now - timedelta(days=35)
    for pk in ids(OperationReceipt.objects.filter(expires_at__lte=now, created_at__lte=receipt_cutoff), 'receipts'):
        if not remaining(): break
        with transaction.atomic():
            row = OperationReceipt.objects.select_for_update(skip_locked=True).filter(pk=pk, expires_at__lte=now, created_at__lte=receipt_cutoff).first()
            if not row or _held(row.actor_id): continue
            counts['receipts'] += 1
            if not dry_run: row.delete()
    security_cutoff = now - timedelta(days=SECURITY_AUDIT_RETENTION_DAYS)
    security_events = Q(action__in=ROUTINE_SECURITY_ACTIONS, actor__isnull=False) | Q(action=PASSWORD_PURPOSE_AUDIT_ACTION)
    for pk in ids(AuditEvent.objects.filter(security_events, created_at__lte=security_cutoff), 'security_audit'):
        if not remaining(): break
        with transaction.atomic():
            row = AuditEvent.objects.select_for_update(skip_locked=True).filter(
                security_events, pk=pk, created_at__lte=security_cutoff).first()
            if not row or _row_held(row): continue
            expected_kind = 'Device' if row.action == 'device.revoked' else 'User'
            # Unexpected entity/detail can carry incident evidence; preserve it.
            password_receipt = row.action == PASSWORD_PURPOSE_AUDIT_ACTION
            if password_receipt:
                if not _password_purpose_receipt(row): continue
            elif row.entity_kind != expected_kind or row.detail != {}: continue
            if expected_kind == 'User':
                if not password_receipt and row.entity_id != str(row.actor_id): continue
            else:
                try:
                    if not Device.objects.filter(pk=row.entity_id, user_id=row.actor_id).exists(): continue
                except (ValueError, ValidationError):
                    continue
            counts['audit_outcomes'] += 1
            if not dry_run: row.delete()

    # Scan only explicitly resolved support cases; SMTP submission alone never
    # starts the90-day clock. Keyset checkpointing advances past held prefixes.
    support_cutoff = now - timedelta(days=90)
    support = OutboxJob.objects.filter(kind='contact_support', status='done', result__retention_case__isnull=False).exclude(result__status='retention_cleaned')
    for pk in ids(support, 'support_cases'):
        if not remaining(): break
        with transaction.atomic():
            row = OutboxJob.objects.select_for_update(skip_locked=True).filter(pk=pk, kind='contact_support', status='done').first()
            if not row or _row_held(row) or not _support_submitted(row): continue
            metadata = _support_case(row)
            if not metadata or metadata[1] > support_cutoff: continue
            case, _ = metadata
            counts['support_payloads'] += 1
            if not dry_run:
                row.payload = {'retention_cleaned': True}
                row.result = {'status': 'retention_cleaned', 'retention_case': case}
                row.error_code = ''; row.save(update_fields=['payload', 'result', 'error_code'])
    return report


def cleanup_account_retention(limit=100, max_seconds=5, dry_run=True):
    """Serialize apply runs and durably resume bounded scans past held rows.

    Checkpoints contain only category keyset positions, not copied personal data.
    Preview reuses the last position but never creates or changes a checkpoint.
    """
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('limit must be1–1000')
    if not 0 < max_seconds <= 30 or type(dry_run) is not bool:
        raise ValueError('require a positive time budget<=30 and boolean dry_run')
    key = 'retention:v1'
    if dry_run:
        payload = OutboxJob.objects.filter(dedupe_key=key, kind='retention_checkpoint').values_list('payload', flat=True).first() or {}
        return _cleanup_account_retention(limit, max_seconds, True, dict(payload.get('cursors', {})))
    OutboxJob.objects.get_or_create(dedupe_key=key, defaults={
        'kind': 'retention_checkpoint', 'status': 'done', 'not_before': timezone.now(),
        'completed_at': timezone.now(), 'payload': {'cursors': {}}})
    with transaction.atomic():
        checkpoint = OutboxJob.objects.select_for_update(skip_locked=True).filter(dedupe_key=key, kind='retention_checkpoint').first()
        if checkpoint is None:
            return {'dry_run': False, 'busy': True, 'eligible': {}, 'time_budget_exhausted': False}
        cursors = dict(checkpoint.payload.get('cursors', {}))
        result = _cleanup_account_retention(limit, max_seconds, False, cursors)
        checkpoint.payload = {'cursors': cursors}
        checkpoint.completed_at = timezone.now()
        checkpoint.save(update_fields=['payload', 'completed_at'])
        return result
