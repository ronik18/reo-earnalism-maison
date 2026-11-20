# Operations qualification — 18 November 2026

The approved full P0 and availability baseline remain unchanged: one Django application, Render Singapore with 2–6 autoscaling replicas, Neon Scale Singapore at the approved bounded compute range, Cloudflare/R2 and the prescribed recovery controls. The currently approved $7 single Render instance is qualification infrastructure; it does not satisfy that baseline. This lane made no provider, DNS, spending or publication changes.

[Sanitized current evidence](evidence/operations-current.json) records actual local checks, including the initial failure. Source and local evidence do not certify production HA, global performance, restore history, RPO or RTO.

## What passed locally

| Check | Observed result | Limit |
| --- | --- | --- |
| PostgreSQL18.7 logical dump/restore | 54 public tables; every row count and deterministic content hash matched; private dump mode0600 | Existing local development data only; not Neon PITR |
| Gunicorn contract | 2 gthread workers ×2 threads, timeout30s, graceful30s, max_requests2000 +jitter200; configuration check passed | Source now matches LLD/runtime-config; not deployed by this lane |
| Bounded HTTP health load |120 liveness requests at concurrency8 and24 readiness requests at concurrency4; all200, private/no-store | Health endpoints only; not a customer-journey capacity benchmark or SLO |
| Local process restart | Liveness returned200 after1.832s | One local process restart; not production rolling rollback/failover |
| Deliberately unreachable local DB | Readiness503 `dependency_unavailable`; liveness remained200 | No production outage injection |
| Encrypted export | New standard `pg_dump18 → age` command plus private manifest; real streaming decrypt/restore and ciphertext-tamper rejection are recorded in evidence | Synthetic local encryption identity only; no production recipient/archive/schedule configured |

The existing local PostgreSQL18 development database initially returned readiness503 because five migrations were pending. It was preserved. The passing HTTP checks used an owned disposable restore target migrated to current source; both disposable restore/health targets were removed after verification. The final combined backend regression run passed238 tests on19November2026, including the five export and four legal-route tests, with no migration drift. The runtime tool check passed as non-root uid10001 (age1.1.1 and pg_dump18.7), and Gunicorn configuration passed. Final exact-head CI remains required after integration.

## Small source corrections

`Dockerfile` now matches the approved Gunicorn timeout and recycling bounds. It installs PostgreSQL client18 from the official signed PGDG repository after checking the published signing-key fingerprint, and Debian's established `age` CLI; download/key-inspection tools are removed afterward. No new Python crypto dependency or custom encryption format is introduced. Resolved tool versions are recorded by the local drill; the final deploy image digest remains an Integration Lane responsibility.

`operations.backup_restore_local` supports only the two named local development mappings: PostgreSQL17 at127.0.0.1:55432 and PostgreSQL18 at127.0.0.1:55433, database `maison`. It still rejects remote/unknown destinations. This helper's local plaintext dump is never the production encrypted-export path.

`python manage.py export_database --encrypted --manifest` requires a separate `MAISON_BACKUP_DATABASE_URL` and public `BACKUP_AGE_RECIPIENT`. It rejects pooled endpoints and non-verified TLS remotely. The password is passed to libpq through the child environment, not command arguments or output. It reads a bounded schema/version manifest, streams a PostgreSQL custom dump directly into standard age encryption, and writes only mode0600 ciphertext/manifest. It enforces time and ciphertext-size bounds, checks both subprocess exit statuses and removes incomplete temporary artifacts. Default pipeline bounds are900s/2GiB, with separately bounded connection/metadata preflight. It performs no upload, scheduling or retention deletion and explicitly does not claim restore verification.

The job host needs only the public age recipient. Keep its restore identity in separately controlled durable storage; do not reuse the synthetic local test identity. Generate/retain the production identity through the owner's chosen credential process. Store all database/archive credentials in the job's encrypted environment. The web delivery token must not have backup-delete access.

## Exact export and restore procedure

Before a production export, configure the separate least-privilege direct backup role, verify TLS and confirm that its read permissions cover all required application tables. Supply the job environment privately, then run:

```sh
python manage.py export_database --encrypted --manifest
```

The output is an encrypted `.dump.age` and corresponding manifest beneath the configured backup root. Preserve both in the separately authorized private archive, verify the uploaded ciphertext hash/size, and alert on export age over26hours. Local job disk alone is not a durable independent backup. Archive upload remains a separate implementation/provider qualification step; this command deliberately has no silent upload fallback.

For a recovery drill, provision or use an explicitly approved isolated empty target. Verify the ciphertext SHA256 against its retained manifest first. Configure `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`, verified TLS and the separately held age identity privately; never point this command at an existing application database:

```sh
set -o pipefail
age --decrypt --identity "$RESTORE_IDENTITY_PATH" "$BACKUP_CIPHERTEXT" |
  pg_restore --no-owner --no-acl --exit-on-error
```

Check both pipeline exit statuses. A failed decrypt/restore leaves an unqualified isolated target; never promote it. Compare row counts, deterministic table hashes, applied migrations, constraints/indexes and representative content; verify matching private-media inventory independently. A database dump does not restore R2 objects, secrets, Cloudflare rules, Stream assets or DNS. Reconcile any external financial events since the restore point before reopening writes. Never replay charges or publication blindly.

For a bad application release, select the previous healthy image **and its matching immutable static release**, retain a compatible schema, then check liveness/readiness, origin denial, staff MFA and the protected draft journey. Auto-deploy remains off in the current qualification service. Do not reverse data migrations or retarget apex traffic as an improvised rollback. Actual Render rollback and Neon recovery drills remain pending; no live rollback was performed by this lane.

## Smallest remaining production work

1. Obtain the owner-approved provider configuration/quote for the required2–6 Render replicas and bounded Neon Scale compute with7-day restore history. Verify the configured caps, availability and observed billing; the single-instance approval does not authorize the expansion.
2. Configure the independently controlled age recipient, private archive bucket/credential and daily03:00UTC export delivery. Add bounded provider upload/readback and the approved retention schedule. Qualify an actual archive download/decrypt/isolated restore. No new archive or paid job has been provisioned here.
3. Qualify one-minute `run_maintenance --max-seconds 45 --batch-size 25` scheduling and lease/duplicate behavior, plus actual alert delivery for unhealthy previews, private5xx, outbox age, export freshness, DB saturation/pool wait and cost forecast. Existing source or manually run commands do not establish a persistent scheduler.
4. Run a bounded authenticated workload and failure/rollback drill on the approved production topology. Measure database query/pool latency and CPU at minimum CU before increasing caps. Keep the prescribed database/provider timeouts and four request clients per replica; do not add a cache or worker service to mask a measured problem.
5. Retain the recovery target labels as **untested** until actual drills: up to24-hour export RPO, four-hour regional restore target, ten-minute zonal allowance. Physical devices, full P0 provider/content/compliance gates and final apex cutover remain owned by their corresponding lanes and the Integration Lane.

Sources for the added standard tools: [official PostgreSQL Debian repository and signing-key instructions](https://www.postgresql.org/download/linux/debian/), [age's upstream stream-encryption/decryption usage](https://github.com/FiloSottile/age#readme).


## Actual isolated activation,19November2026

The owner-approved NeonLaunch0.25–2CU/7day history and existingRenderHobby/native7day-log exception are active. Separate Singapore0.5CPU/512MB maintenance and03:00UTC encrypted-export cron jobs are live on reviewed source171c794. Provider Scheduled runs and cleared-lease receipts passed. The one-time reference export uploaded/checksummed daily/monthly copies; its downloaded262499-byte ciphertext restored locally with all60table counts/content/column hashes matching the exported snapshot. No plaintext dump was written,private identity stayed local,and only the generated restore target was removed. Qualification hashing was removed from the normal daily command; maintenance resumed and passed again after named configuration correction. Protected readiness,liveness,draft denial and unchanged legacy HTTPS all pass.

See [actual activation](evidence/isolated-provider-activation.json), [restore](evidence/scheduled-archive-restore-result.json), [current checklist](PENDING_VALIDATIONS.md). This proves the stated logical archive/isolated scheduling behavior,not productionHA/autoscaling,nativePITR,retroactive7-day history or actual aged-object deletion. Web source7790139 and staticreleasebd1b698d remain unchanged. No DNS/publication/mailbox/legacy changes.

## Current isolated security acceptance,20November2026

Release6fda672 is Live on existing web/maintenance/archive services with merged-main CI604backend/37client PASS.105focused actual-crypto checks,42local and96live desktop/phone-viewport checks passed. Scheduled maintenance succeeds with a clear lease. The native daily job verified a new database backup/readback and complete scoped security-log capture. Four UTCpieces/66104records were independently checksum-verified and age-decrypted; the known request probe was recovered without plaintextfiles. Existing database backup identity/policy and prior restore evidence remain unchanged. The security identity is separately owner-held. No new service, plan, book/legacy/DNS change or aged-object deletion. [Current receipt](evidence/security-retention-20261120/README.md). This supersedes historical isolated scheduling/archive-pending statements above, not the separately approved full HA/Scale/publication baseline. PhysicalUAT remains deferred/non-blocking.

## Current enabled isolated-free P0 closeout —21November2026

Reviewed support/staffform/post-lock authority/staffassets defects are fixed and deployed on7297a9d. Exact-mainCI636backend/37client suite checks PASS (20CIcrypto skips covered locally),201immutable assets and120live browser checks PASS. Existing operator access,scheduledmaintenance and protected-book/finance/legacy invariants PASS. [Current register](PENDING_VALIDATIONS.md) and [actual receipt/previews](evidence/p0-closeout-20261121/README.md) supersede historical isolated-pending statements. PhysicalUAT remains deferred/nonblocking; future public/all-ages,productionHA/SLO/alert/nativePITR,paid,title and gated-capability acceptance remain distinct.
