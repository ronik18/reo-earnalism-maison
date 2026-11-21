"""One durable maintenance receipt; provider cron owns scheduling/single-run.

Only short receipt transactions run here. No DB lock spans maintenance or an
external call, and this control row is terminal so outbox workers never claim it.
"""
import os
import re
import uuid
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from core.models import OutboxJob

_ALLOWED_COUNTS = {
    'processed', 'expired_exports', 'cleaned', 'failed', 'rate_counters', 'deleted',
    'cache_references', 'retention', 'dry_run', 'eligible', 'time_budget_exhausted',
    'busy', 'action_tokens', 'mail_payloads', 'sessions', 'devices', 'receipts',
    'abandoned_signups', 'audit_outcomes', 'support_payloads', 'guardian_authorizations',
    'guardian_accounts_suspended',
}


def _stamp():
    return timezone.now().isoformat().replace('+00:00', 'Z')


def _key(name):
    if name != 'maintenance':
        raise ValueError('Unsupported scheduled run category')
    return 'scheduled-run:maintenance:v1'


def _counts(value, depth=0):
    if type(value) in (int, bool):
        return value
    if isinstance(value, dict) and depth < 4:
        return {key: _counts(item, depth + 1) for key, item in value.items()
                if key in _ALLOWED_COUNTS and (type(item) in (int, bool) or isinstance(item, dict))}
    return {}


def start_run(name='maintenance', source='manual'):
    """Record intent, not proof a provider scheduled this invocation."""
    if source not in ('manual', 'scheduled'):
        raise ValueError('Unsupported run source')
    key = _key(name); now = timezone.now()
    commit = os.environ.get('RENDER_GIT_COMMIT', '')
    commit = commit if re.fullmatch(r'[a-f0-9]{40}', commit) else ''
    run_id = str(uuid.uuid4())
    with transaction.atomic():
        row, _ = OutboxJob.objects.get_or_create(dedupe_key=key, defaults={
            'kind': 'scheduled_run_checkpoint', 'status': 'done', 'not_before': now})
        row = OutboxJob.objects.select_for_update().get(pk=row.pk)
        if row.kind != 'scheduled_run_checkpoint' or row.status != 'done':
            raise ValueError('Invalid scheduled run checkpoint')
        if row.locked_until and row.locked_until > now:
            return None
        payload = dict(row.payload)
        previous = payload.get('latest', {})
        if previous.get('outcome') == 'running':
            payload['last_failure'] = {**previous, 'outcome': 'incomplete', 'error_code': 'previous_run_incomplete'}
        payload['latest'] = {'run_id': run_id, 'started_at': _stamp(), 'finished_at': None,
                             'source': source, 'commit': commit, 'outcome': 'running', 'counts': {}, 'error_code': ''}
        row.payload = payload
        row.lease_owner = run_id
        row.locked_until = now + timedelta(seconds=120)
        row.save(update_fields=['payload', 'lease_owner', 'locked_until'])
    return run_id


def finish_run(name, run_id, outcome, counts=None, error_code=''):
    """Compare run UUID so a late old result cannot overwrite a newer run."""
    if outcome not in ('success', 'failure'):
        raise ValueError('Unsupported run outcome')
    error_code = error_code if re.fullmatch(r'[a-z][a-z0-9_]{0,63}', error_code or '') else ''
    with transaction.atomic():
        row = OutboxJob.objects.select_for_update().get(dedupe_key=_key(name), kind='scheduled_run_checkpoint')
        payload = dict(row.payload); latest = dict(payload.get('latest', {}))
        if (latest.get('run_id') != str(run_id) or latest.get('outcome') != 'running'
            or row.lease_owner != str(run_id) or not row.locked_until or row.locked_until <= timezone.now()):
            return False
        latest.update(finished_at=_stamp(), outcome=outcome, counts=_counts(counts or {}),
                      error_code=error_code if outcome == 'failure' else '')
        payload['latest'] = latest
        payload['last_success' if outcome == 'success' else 'last_failure'] = dict(latest)
        row.payload = payload; row.completed_at = timezone.now()
        row.lease_owner = ''; row.locked_until = None
        row.save(update_fields=['payload', 'completed_at', 'lease_owner', 'locked_until'])
        return True
