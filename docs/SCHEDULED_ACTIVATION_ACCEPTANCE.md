# Isolated maintenance activation acceptance

Prepared19November2026. Root Integration alone activates providers and records actual results. This document is a read-only acceptance plan, not evidence a cron has run. Keep The Selfish Giant draft, the legacy platform unchanged and DNS unchanged. Apply the owner's latest approved **Neon Launch0.25–2CU /7-day Render logs** package; older Scale/minimum0.5CU cost comments in prepared configuration are superseded and must not be used as the current approved quote. A minute-by-minute database poll normally prevents five-minute autosuspend; cron's minimum monthly fee is not the total database/platform cost.

## Configuration and source identity

Use the existing private Maison repository and its exact CI-passing deployed source. Record the Render cron service ID, deployed commit and UTC activation time. The cron runs in Singapore with Starter Docker compute, auto-deploy off, no public hostname, no persistent disk and this command:

```sh
python manage.py run_maintenance --apply-retention --run-source scheduled --max-seconds 45 --batch-size 25
```

Schedule: `* * * * *` in UTC. `--run-source scheduled` is an invocation label, not proof of an automatic provider trigger. Render's Runs history supplies that proof. Do not manually Trigger Run while another run is active: Render cancels the active run when manually retriggered. The application also has a120-second global maintenance lease for manual CLI/cron overlap; claims/finalization use short transactions, not locks across provider calls.

[Prepared maintenance Blueprint](../deployment/maintenance.render.yaml) explicitly sets `MAISON_ENV=production` and `MAISON_DATABASE_ROLE=direct`. The existing app-role direct URL must use verified TLS and the same isolated Neon database. Do not use the independent backup read-only role for mutating maintenance. One maintenance process can use its default direct connection plus the short-lived direct privacy-export alias: preserve the approved maximum of two direct maintenance connections. No worker/thread increase is needed.

The Blueprint includes all settings required by current production startup. Set secret values privately from the approved existing Maison configuration, never paste them into evidence. Required names:

- `DJANGO_SECRET_KEY`, `DATABASE_DIRECT_URL`, `DATABASE_URL`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `PUBLIC_BASE_URL`, `ORIGIN_SHARED_SECRET`, `HEALTH_PROBE_SECRET`.
- `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_FROM_ADDRESS`; SMTP backend,465/SSL and non-STARTTLS are explicit in the prepared Blueprint. Preserve the existing sender.
- `R2_ACCOUNT_ID`, `R2_PRIVATE_BUCKET`, private delivery/upload key IDs and secrets (`R2_APPLICATION_KEY_ID`, `R2_APPLICATION_SECRET`, `R2_UPLOAD_KEY_ID`, `R2_UPLOAD_SECRET`), `R2_PUBLIC_ASSET_HOST`, `STATIC_RELEASE_ID`.
- `SUPPORT_EMAIL`, `CLOUDFLARE_ZONE_ID`, `CLOUDFLARE_CACHE_PURGE_TOKEN` are needed when their relevant due jobs are present. A blank destination must not be reported as qualified support delivery. Copy only the existing approved scoped purge credential; no DNS/admin or public-asset deployment credential belongs in maintenance.

`DATABASE_DIRECT_URL` is the prepared key; settings also accept the existing `DATABASE_URL_UNPOOLED` fallback. `R2_ENDPOINT_URL` is derived from the account ID when not overridden. Optional `DATABASE_SSL_ROOT_CERT` is needed only if the approved configuration uses a custom trust root. Do not export all environment values to compare configuration.

## Before activation: read-only inventory

Root reads queue kind/status/count and oldest due time; scheduled-revision counts; the current draft/live-pointer/hash; and protected readiness. Do not dump queue payloads, recipient addresses, notes or storage keys. Retain the existing queue inventory approval before allowing ordinary due jobs to run. No synthetic live payment, publication or message is needed to prove a scheduler.

This optional inventory command performs no processing, sends nothing and cannot publish:

```sh
python manage.py shell <<'PY'
import json
from django.db import connection, transaction
from django.db.models import Count, Min
from django.utils import timezone
from core.models import OutboxJob
from library.models import Revision
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
    now = timezone.now()
    due = list(OutboxJob.objects.filter(status__in=['pending', 'claimed'], not_before__lte=now)
               .values('kind', 'status').annotate(count=Count('id'), oldest_due=Min('not_before'))
               .order_by('kind', 'status'))
    scheduled = Revision.objects.filter(scheduled_for__isnull=False)
    print(json.dumps({'observed_at': now.isoformat(), 'due_job_groups': due,
                      'scheduled_revisions': scheduled.count(),
                      'due_ready_revisions': scheduled.filter(state='ready', scheduled_for__lte=now).count()}, default=str))
PY
```

A scheduled-publication field is not an executed publication job: current `run_maintenance` does not scan `Revision.scheduled_for`. Report that separate baseline acceptance gap truthfully. Do not schedule the real draft book to exercise it.

## Actual automatic-run acceptance

1. Inspect the cron's deployed source, schedule, command and runtime settings. Record configuration without secret values.
2. Wait for an automatically scheduled run and a second subsequent minute run to finish. Poll in short intervals; no manual command substitutes for these provider-triggered runs. Capture provider run IDs, automatic trigger/cause, UTC start/end, source commit and exit status. Render single-run behavior can delay a run if its predecessor remains active; do not claim an exact60-second guaranteed execution latency.
3. After each completed run, read the singleton receipt using the command below. Keep both external evidence snapshots because the singleton intentionally overwrites its latest run instead of accumulating one database row every minute. Match source commit and start/end interval against the corresponding provider run; provider run IDs and application UUIDs are different identifiers.
4. Each accepted completed run has `latest.outcome=success`, `source=scheduled`, expected commit, a non-null finish time, and a cleared lease. The second run has a different application UUID and newer start/end times. Counts may all be zero: a real recurring run over an empty eligible queue is valid scheduling proof. A successful command does not mean every outbox item was delivered; inspect blocked/dead/oldest due aggregate separately.
5. Read back protected readiness and the existing draft/null-live-pointer/manuscript SHA invariant. Reuse unchanged browser/locking/failure evidence; do not repeat physical-device UAT or introduce publication to validate maintenance.

Read-only receipt command (set the public expected source SHA to the commit actually deployed to cron):

```sh
python manage.py shell <<'PY'
import json, os
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from core.models import OutboxJob
from operations.scheduled_runs import _counts
EXPECTED_SOURCE = 'REPLACE_WITH_EXACT_DEPLOYED_40_CHARACTER_COMMIT'
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
        cursor.execute('SHOW server_version_num')
        server_version = int(cursor.fetchone()[0])
    row = OutboxJob.objects.filter(dedupe_key='scheduled-run:maintenance:v1', kind='scheduled_run_checkpoint').first()
    payload = row.payload if row else {}
    def receipt(value):
        fields = ['run_id', 'started_at', 'finished_at', 'source', 'commit', 'outcome']
        return {**{key: value.get(key) for key in fields}, 'counts': _counts(value.get('counts', {}))}
    latest = payload.get('latest', {})
    result = {'observed_at': timezone.now().isoformat(), 'server_version_num': server_version,
              'database_role': settings.DATABASE_CONNECTION_ROLE,
              'tls_verified': connection.settings_dict['OPTIONS'].get('sslmode') == 'verify-full',
              'checkpoint_present': row is not None, 'control_row_terminal': bool(row and row.status == 'done'),
              'lease_cleared': bool(row and not row.lease_owner and row.locked_until is None),
              'latest': receipt(latest), 'last_success': receipt(payload.get('last_success', {})),
              'last_failure': receipt(payload.get('last_failure', {})),
              'commit_matches_expected': latest.get('commit') == EXPECTED_SOURCE}
    print(json.dumps(result, default=str))
PY
```

Readiness and receipt can be checked from the existing web shell, but its `DATABASE_CONNECTION_ROLE` describes that shell's runtime. For cron's direct-role proof, run the read-only probe in the cron runtime or combine its configured environment-name/value readback with provider startup/run evidence; do not mislabel a pooled web-shell observation as direct cron execution. Never print the DSN. An absent/blank `RENDER_GIT_COMMIT` prevents exact-source receipt acceptance; investigate provider source metadata instead of inserting a fabricated commit into evidence.

## Failure interpretation and safe follow-up

- `busy`: another unexpired global lease exists; this invocation does no work. Match provider history and retry on a later normal schedule. Do not erase or shorten the lease to manufacture success.
- `running` with no finish after the120-second lease: possible interrupted process or database outage. The next legitimate claim records the predecessor as incomplete while preserving last success. Do not mark that old run successful.
- Expired/lost/superseded completion lease produces a nonzero `CommandError`, not a success log. No stale finalizer overwrites a newer receipt.
- `failure` or provider nonzero exit: retain the safe outcome/error evidence and prior last-success record. Inspect the existing aggregate outbox/expiry results, readiness and provider failure logs. No unbounded manual retry loop and no change to book publication or credentials is implied.
- No automatic-run history, no fresh receipt or mismatched commit: scheduling remains pending. UI configuration alone is not a PASS.

Existing exact-source tests already cover concurrent manual/scheduled claims, lease expiry/recovery, stale completion, no transaction across maintenance work, safe nested count filtering, preserved last success, and retention checkpoints/holds. Do not rerun unchanged destructive/live scenarios merely for this checklist.

Independent encrypted archive/export scheduling remains a separate03:00UTC command with its own read-only DB role, public encryption recipient and archive credential. A one-minute maintenance success does not certify archive delivery,30daily/12monthly backup retention, provider log expiry, global legal clearance or production HA.
