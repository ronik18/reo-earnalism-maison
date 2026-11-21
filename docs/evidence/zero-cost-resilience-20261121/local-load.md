# Zero-cost local workload and resilience acceptance

21 November 2026. **Actual local checks PASS; no provider test, spend or production acceptance claimed.** Exact application source `74a48e85e551fec0dfddd0d633cf2f86a1642894` was mounted read-only into the already installed `earnalism-maison:guardian-final-20261121` dependency/runtime image. Only a separately writable owned runtime directory and newly owned local PostgreSQL18 database were used. No image pull, package installation, provider credentials/requests, mail, payment, title release or legacy operation occurred.

## Actual bounded workload

Ten verified synthetic local accounts used normal HTTP API sign-in, CSRF and device/session cookies. Original **River Notebook** English/Bengali local fixtures were seeded only into the owned database; it contained zero rows for The Selfish Giant's edition. Gunicorn ran the reviewed two gthread workers × two threads. It had **no per-container CPU/RAM cap**, so these numbers are not the Render0.5CPU/512MB service benchmark.

One70-second profile offered operations at5/s for30seconds,50/s for10seconds,then5/s for30seconds. The offered operation mix covered EN/BN catalog, Reader manifest, progress read/write, Vault, member profile and package grants. Each grant additionally fetched and checksummed its actual private Reader JSON bytes. Therefore the profile rates are **operations/second, not HTTP requests/second**. The burst actually completed563HTTP requests in10seconds. A24-worker HTTP executor sequenced each synthetic user to one inflight operation; at most10users were active concurrently. No artificial rate limit or security setting was disabled.

| Actual result | Measurement |
|---|---:|
| Offered/completed primary operations |800 /800|
| Dropped primary operations |0|
| Load-window HTTP requests |900, all200|
| Elapsed load window |70.012s|
| Progress writes / durable operation receipts |100 /100|
| Private Reader package SHA/header checks |100 PASS|
| Response bytes |586758|
| Semantic failures / transport exceptions |0 /0|
| HTTP service p50 /p95 /p99 |13.056 /25.149 /32.853ms|
| Maximum measured HTTP service time |50.428ms|

[Actual aggregate/stage/route receipt](local-load.json). Setup/preauthentication/smoke and post-load progress readback add33HTTP requests outside the timed load window. Reported latency starts after the per-user sequencing lock; scheduler/lock-queue time is not included. This is not a new approved latencySLO. Natural local application-cache state was used; no controlled cold-cache or CDN HIT/MISS test was performed. Root's separate recovery lane also used the shared local PostgreSQL container, so this is not a dedicated hardware benchmark.

Five users received20progress updates each; the other five had no writes under the deterministic route/user mix. Independent API readback matched every user's expected version. A SELECT-only local snapshot confirmed five progress rows,100operation receipts,10synthetic users and zero protected real-book edition rows. No inference is made from those synthetic rights to actual title clearance.

## Actual local restart and degraded dependency

[Resilience receipt](local-resilience.json): restarting **only the owned local app container** restored liveness in1.461seconds, followed by readiness200. The same authenticated browser-equivalent HTTP session survived, and its persisted progress payload/version20 was unchanged. This is local process/container recovery, **not Render rolling rollback or provider failover**.

A second owned loopback app used a deliberately unreachable local PostgreSQL port. Actual liveness remained200 and authenticated readiness returned503 `dependency_unavailable`. The shared PostgreSQL container was never stopped or reconfigured. This is a separate local dependency-degraded configuration, not a production outage or actual pool saturation test.

The first restart harness attempt called an unavailable unauthenticated urllib helper and reached its20-second harness deadline. The harness was corrected to use standard `urlopen`, then the bounded restart/dependency checks passed. No application source defect/change was involved; no failed provider or production action was repeated.

## Cleanup and remaining scope

[Owned-resource cleanup](local-cleanup.json) verified the synthetic state, removed only `maison-zero-load-20261121`, `maison-zero-load-degraded-20261121` and database `maison_zero_load_20261121_1200`, and verified their removal. Existing `earnalism-maison-pg18` and `earnalism-qualification-ui` remained running. Scripts are retained in this checkout's ignored `.local/zero_load_*.py`; no token/cookie/password/raw private response is in committed receipts.

This closes the bounded **local** workload/restart/dependency validation at$0new provider spend. Remote2–6replica autoscaling/HA, configuredCU capacity, native PITR, actual production-history restoration, CDN/media-region behavior, pool/lock telemetry and productionSLO/RPO/RTO remain unqualified. The owner-declined$50pilot was not executed. No plan, DNS, book state, public method or legacy change is implied.
