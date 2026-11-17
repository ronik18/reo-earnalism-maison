# Maison parallel implementation and go-live plan

17November2026. Owner authorizes parallel completion and cutover, confirms zero current customers, and requires the approved design/architecture with lean maintainable production code. Starting source:95cd49f. Root is the single integration/release owner.

| Lane | Owner | Independent implementation | Completion evidence |
| --- | --- | --- | --- |
| Experience | frontend_completion | Approved React/TypeScript Reader, Player, Quiz islands; responsive EN/BN screens and accessibility; preserve SSR/content security and brand assets | Frontend type/build checks, web/API journey and browser acceptance |
| Accounts and Reader | backend_completion | Identity/device controls, staff MFA, privacy export/deletion, Reader/offline licence and sync behavior | PostgreSQL ownership/replay/expiry/revocation tests; real delivery qualification where applicable |
| Media and commerce | media_commerce | Planned R2 uploads/direct delivery, audio/timing switches, learning/SDE/quiz completeness, hosted merchant/refund reconciliation adapters | Provider-contract tests, rights/asset checks, merchant sandbox acceptance; never fake capture/media readiness |
| Integration and launch | root | Settings/dependencies/image/CI, approved Render/Neon/Cloudflare deployment files, trusted edge/CDN, export/restore, combined validation, staged domain switch | Exact-source CI, actual provider health/journey, recovery and cutover verification |

## Execution order

1. The three implementation lanes run concurrently with exclusive file ownership. Root builds deployment/operational integration concurrently and reconciles APIs/config once. Use one Django app, one PostgreSQL, direct R2/CDN, existing outbox/maintenance, and gated approved providers. No Redis, microservices, alternate host/database, wallet bridge or repeated redesign is introduced.
2. Integrate the combined source, run affected checks and one complete PostgreSQL/frontend/contract suite, then exercise the actual book journey. Preserve valid unchanged text/cover/browser evidence. A deterministic contract test is not real provider or physical-device acceptance.
3. Qualify the prepared Render/Neon/Cloudflare profiles, email/domain and merchant sandbox. New paid resources are not created before a concrete spending package is approved. Existing provider sign-in/access is a fact to obtain while coding continues. Conditional features retain their already approved rollout rules; a reduced pilot cannot be called full P0.
4. Use a fresh Maison production database and individually cleared book assets. With zero customers, omit account/progress/wallet/balance migration and dual-write infrastructure. Carry forward only needed operator configuration, not historical complexity or test records.
5. When the enabled launch scope passes actual acceptance, root switches the domain and verifies discovery, account confirmation/sign-in, Reader/media, progress/Vault, enabled checkout, staff publishing and health. Keep a recoverable old configuration/database/media snapshot and a direct routing rollback. No long parallel-running migration programme is needed.
6. After verified cutover, stop the identified legacy frontend/backend/unused running dependencies to end duplicate running cost. Preserve repository/media/backups; deletion or unreviewed data destruction is not part of cutover.

## Non-negotiable scope facts, kept minimal

Approved HLD/technical solution/LLD and design remain binding; deviations require explicit owner approval. Active publication scope is the47-code whitelist. UAE/Mainland China and pending jurisdictions are excluded. A book needs exact-edition legal compliance in all active regions before publishing; do not fabricate this from term research or CI. Current The Selfish Giant remains draft until that evidence exists. No blanket worldwide availability or guaranteed recovery/performance claim is inferred from local tests.

Report real lane progress and one next integration action. Ask only for irreducible account access, actual merchant/legal facts or a concrete new spending approval; continue all independent work while these are pending. Do not claim a go-live timestamp before provider access, evidence and actual deployment are ready.
