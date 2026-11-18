# Neon PostgreSQL18 and first-book acceptance

**Latest,18November2026:** all five follow-up migrations are now applied to dedicated Neon:43total,zero pending. Direct/pooled TLS, protected backup plus populated restore rehearsal, unchanged draft identity/content and the actual32-paragraph R2/browser journey pass. The staff-draft Finished projection was corrected without exposing drafts to customers. See the [central register](PENDING_VALIDATIONS.md) and [fresh browser record](evidence/neon-five-browser-journey.json); historical counts below are superseded.

**Latest provider/source milestone:** see [provider qualification handoff](PROVIDER_QUALIFICATION_HANDOFF.md). The historical37-migration result below predates the added cache-ledger migration.

**Pending acceptance checks:** use the [central pending validation register](PENDING_VALIDATIONS.md) for provider, CDN HIT/MISS/purge, email, device and final release dependencies. Earlier milestone gaps below are historical; close items only with actual evidence.


18 November2026. Integration Lane owns this record. The owner approved PostgreSQL18 in the existing dedicated project. Hosting, HA/scaling, publication scope and spending authority are unchanged.

## Result

The existing Singapore Neon project is PostgreSQL18.7. All37 Django migrations are applied, with zero pending. The Selfish Giant is imported through the existing staff draft API with the approved full front/back covers. It remains **draft**, with a null live revision pointer. The current Earnalism application, repository and infrastructure were not changed. No new paid infrastructure or public book publication occurred.

## Connection correction

Neon PgBouncer rejects timeout startup options and does not guarantee session SET state across transactions. The app therefore omits those startup options only on pooled connections. `configure_database_timeouts` uses the direct endpoint to set current-role/current-database defaults: statement5s, lock2s and idle transaction10s. A fresh actual pooled connection read back all three, and `pg_sleep(6)` was cancelled after5.08seconds. Certificate/hostname verification remains `verify-full` with a trusted platform CA bundle.

Migrations and streaming exports use the direct endpoint. Production requires that URL. The maintenance alias uses server-side cursors and no persistent connection; it independently validates TLS and must identify the same database/endpoint as the web connection. A blank optional override falls back to Neon's `DATABASE_URL_UNPOOLED`. Existing environment values are preserved; `.env.local` loads only when explicitly requested and stays ignored/mode0600.

## Compatibility evidence

- Approved Python3.13 container, PostgreSQL18: **116 combined tests passed** before the final configuration-only safeguards; six focused configuration/command tests passed afterward. Exact-head CI is the final combined check.
- Node24: TypeScript and **12 frontend regression tests passed**, including delayed GET/PUT ordering and genuine-versus-own-operation conflicts. `npm run build` passes.
- All new application migrations reversed and reapplied on the **empty isolated local PostgreSQL18** database. Populated, Neon and legacy databases were excluded from that operation.
- API schemas validated:165 schemas,125 distinct operation IDs. MFA, privacy expiry, upload headers and mapping selection contracts reflect the implementation.
- Image packaging includes the necessary private rights-review packet while excluding env files, credentials, `.local`, Git history and node_modules. Node is build-only.

Evidence: [runtime connection](evidence/neon-connection-check.json), [Neon migration log](evidence/neon-migrations.log), [Python3.13 suite](evidence/pg18-python313-suite.log), [rollback/reapply](evidence/pg18-rollback-reapply.log), [frontend checks](evidence/neon-frontend-check.log), [build](evidence/neon-frontend-build.log).

## Actual book journey

Edition `55a3f5e3-f713-40b2-a873-942cd97bb1b7`; revision `3988156b-2eee-4839-b542-2d3b8b253307`; slug `the-selfish-giant-en`. New IDs/anchors mean the revision root differs from the old local draft; canonical32-paragraph source content and approved cover hashes were verified unchanged.

Actual desktop browser checks covered password sign-in, both complete covers and the requested publisher footer, all32 paragraphs/first-last passages, explicit saved position, note and gold highlight restored after reload,23px sepia preferences, Bengali controls preserving the English edition, explicit completion and Saved/Finished reopening, then sign-out denying the draft. Browser-discovered annotation fallback, draft-orphan classification and progress snapshot races were fixed and rechecked.

Direct API checks against Neon independently verified ordinary-member Reader/manifest404, staff cover403; guest Reader/catalog404 and staff cover401. Both pooled and direct connections use TLS. See [browser and persisted-data record](evidence/neon-book-browser-journey.json), [draft identities/checks](evidence/neon-book-draft.json), [cover screenshot](evidence/neon-book-covers.png) and [restored highlight](evidence/neon-reader-final.png).

## Parallel lane handoff

| Lane | Integrated source | Qualification still needed before public launch |
| --- | --- | --- |
| Backend | Staff MFA, privacy exports/cleanup, device revocation, offline licenses, keyset pagination | Actual production email/storage, device and operational acceptance |
| Experience | React Reader/Player/Quiz/account/download islands, EN/BN controls, bounded sync and offline shell | Physical offline/mobile acceptance; playback across full document navigation; rejected queued-note recovery UX; configured merchant checkout UI |
| Media/commerce | R2/timing/prepared-media adapters, publication verification outside locks, learning rules, sandbox checkout | Real R2/Stream assets; live merchant/tax/invoice facts; production R2 draft intake must move package storage outside its receipt transaction |
| Integration | Neon setup/migrations, pooled/direct TLS and timeouts, Node container/CI, contracts and actual book acceptance | Production provider configuration, shared member rate-limit/header mapping, emitted exact-URL capture/CDN eviction readback, restore/load/failure qualification and authorized spending |

The exact-URL purge adapter is implemented and tested without network calls. Existing purge jobs contain edition/revision IDs but not captured emitted URLs; they fail explicitly rather than pretend eviction. No registry/new service or broad global purge was introduced.

Automatic approval review rejected the media lane's proposed refund provider handler; no external refund call occurred. Refund obligations remain durably blocked. Live payments are not qualified or enabled.

Desktop draft acceptance is not R2/CDN, physical-device, HA or public-release acceptance. Full47-region exact-edition publication permissions remain incomplete, so this book stays draft. Audio/video/payments/download are not offered for this book. Do not fabricate those qualifications from CI.

Next integration action: qualify the approved production providers and remaining release acceptance on this source; keep the current platform unchanged until the owner-authorized cutover scope is active and all applicable requirements pass.
