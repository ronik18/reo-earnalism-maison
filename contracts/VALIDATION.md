# Maison validation status

Updated17November2026. The initial static-only record is preserved in VALIDATION_BASELINE_20261117.md. Current first-slice application evidence is in the companion GO LIVE implementation milestone; these checks do not certify production.

The amended draft1.1 OpenAPI contains116 operations and154 schemas. Structural validation passes963 schema/example checks representing59 unique cases, including29 delivery/cache payload cases. All26 screen IDs and171 operation references resolve. The SQL parses as131 statements,54 application tables,49 explicit indexes and108 valid FK targets. All8 cross-file coherence probes now have explicit matching mappings.

The full54-table reference SQL has also executed on isolated PostgreSQL17 after real Django auth/session migrations. Eleven runtime checks verify default-deny policy, JSON-null/missing-policy rejection, positive versions, one bounded partial-refund approval, immutable approved amounts and reservation ceilings. This raw reference schema is separate from the running first-slice ORM database.

The actual Django first slice has real PostgreSQL migrations, strict API DTO checks, two-thread first-save/replay tests, reset/device revocation, interrupted-sync replay and the complete account/Reader journey using original test-only EN/BN content. Its latest full-suite count and runtime versions are recorded in ../go-live/implementation-status.json; do not substitute earlier counts for that result.

A local logical backup was restored to a separate database and all49 actual application/framework tables matched by row count and content hash. This does not qualify managed PITR, cross-region recovery or HA.

Desktop browser checks verified full Reader access after sign-in, persisted notes/completion, locale continuity, Saved/Finished Vault destinations and preview-only access after logout. Mobile emulation was inconclusive; actual mobile devices, screen readers and native Bengali editorial acceptance remain open.

Real R2/CDN/Stream, email/merchant providers, trusted production territory, offline text/audio, load/CU sizing, failover and commercial launch-title clearance remain unqualified. No paid infrastructure or legacy-platform cutover was performed.

Reproduce static checks with validate_contracts.py; run the new repository's Django/operations validation commands for local runtime checks. Never apply database.sql to the ORM application database.
