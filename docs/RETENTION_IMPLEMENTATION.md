# Bounded retention cleanup

Owner approval:19November2026, “Approve proposed cleanup windows.” Uses existing Django models/maintenance, with no new service, schema migration, paid infrastructure or DNS changes. No child-account feature is added.

## Implemented categories

- Seven-day abandoned unverified signups: only untouched registration scaffolding, no staff/verified/used account, domain activity, obligations or non-registration audit. Registration audit and minimal mail outcomes survive with null actor.
- Reset/verification action material after expiry or consumption plus seven days. Scrub terminal mail payloads; preserve pending, claimed, failed/uncertain submission and recorded holds.
- Expired sessions/devices, with related download/security records preserved.
- Expired operation receipts only after their full35-day replay window, even if an incorrect earlier expiry was stored.

Each category has a bounded candidate batch and time budget, row locking and eligibility rechecks. One terminal checkpoint in the existing outbox stores keyset positions, so a protected record cannot repeatedly starve later eligible rows; apply runs serialize and wrap at the end of each scan. Preview reads the checkpoint without creating/updating it. Preview is the default. Existing private-export/rate/cache cleanup remains unchanged; preview below does not run those helpers or outbox jobs.

```sh
python manage.py cleanup_retention --batch-size 100 --max-seconds 5
python manage.py cleanup_retention --apply --batch-size 100 --max-seconds 5
```

Existing scheduled maintenance can opt into this cleanup without a separate worker:

```sh
python manage.py run_maintenance --apply-retention --batch-size 25 --max-seconds 45
```

`run_maintenance` still processes its normal due outbox work; use standalone `cleanup_retention` for a retention-only preview. Output reports aggregate category counts only, not emails, IDs, tokens or payloads. Do not treat time-limited partial batches as full-database completion. Repeat bounded maintenance under the approved schedule, not a request-thread loop.

## Preserved and pending

No blanket audit, support-message, active-member, manuscript, financial or backup deletion. Ordinary logs30days require actual provider-retention readback. Support90days begins at actual case resolution, not SMTP acceptance. Routine security outcomes90days require explicit categories/incident holds before purging mixed audit evidence. Existing backup retention and financial/legal holds remain binding. These are acceptance items in the single [checklist](PENDING_VALIDATIONS.md), not reasons to add another service.

Local PostgreSQL tests must prove preview/apply, replay floor, protected accounts/holds/uncertain mail and repeatability. Exact-source CI is required before main integration. Source deployment, an actual production preview/application receipt and scheduling remain separate from test-database evidence. Do not promise immediate deletion from provider logs or backups.
