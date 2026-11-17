# Maison local implementation

This is a new independent Git project. Do not edit or run the legacy application or provision cloud resources. Bind local services to loopback. Keep dependencies, fixtures and test storage separate. No production credentials, customer records, paid calls or public book publication.

Four lanes share this checkout with exclusive ownership:
- A Application/data: accounts/, reader/, core/ models/services/API and their tests/migrations.
- B Experience: web/, templates/, static/ and their browser-facing behavior.
- C Content/media/learning: library/, learning/, billing/ (reassigned after initial handoff), their models/migrations/tests and original local-only fixture packets.
- D Root Integration: config/, operations/, manage.py, dependencies/containers/CI, contracts/, integration tests, status/evidence and final commits.

Only root integrates shared contracts, configuration and final commits. Send interface changes before altering another lane's files. No git reset/stash/force push/deletion or cloud resources. Existing review assets/fonts/logo may be copied with their licenses; protect the official logo pixels.

Use the reviewed OpenAPI shapes; root reconciles its 21 findings. SQL/ORM constraints and receipts must enforce the actual behavior, not constant version numbers or fake payment success. Use PostgreSQL for integration/locking tests. Local fixture success does not certify R2/CDN, merchant, real device, rights or production release.


## Owner instruction,17 November2026: approved design is binding

Follow the approved HLD, technical solution, LLD, API/DB/cache contracts and Maison visual design. Obtain explicit owner approval before any deviation in architecture, technology, design behavior, scope, availability or cost assumptions. An implementation shortcut or an agent-written milestone note does not amend the approved design. Fix gaps toward that baseline; do not rewrite the baseline to declare an incomplete implementation compliant. Continue the fastest qualified go-live work using the approved implementation sequence and retain the running legacy platform. New spending still requires the applicable budget authority.


Owner publication-scope amendment,17November2026: use contracts/publication-policy.json as the47-region whitelist. UAE/Mainland China are out of scope and pending jurisdictions are excluded. Publish a book only with exact-edition legal compliance across every active region and offered format/action. Keep incomplete titles draft/held; do not silently shrink or expand the whitelist. The corresponding book-production skill and BOOK_PUBLICATION_POLICY.md carry this standing rule.


## Owner-authorized parallel completion and zero-customer cutover,17November2026

The owner explicitly requests parallel sub-agents to complete Maison and GO LIVE, confirms the current production has no customers, and authorizes root to perform cutover when qualified. This supersedes the initial local-only preparation restriction for authorized staging/production and cutover work. Keep the approved architecture/design and47-region publication policy. No customer/wallet dual-write or migration bridge is needed; use a fresh Maison database, cleared content and necessary operator configuration. Root alone owns integration/release, provider mutations and cutover. Prepare the exact paid resource/cost package before requesting indispensable spending authority; no paid provisioning is implied without that authority. Preserve legacy code/data/backup for recovery; stop legacy services only after verified cutover, and do not delete historical assets or repositories.

Current active file ownership replaces the initial lane allocation for this completion run:
- Frontend agent: client/, package/build files, web/, templates/, static/.
- Backend agent: accounts/, reader/, core/.
- Media/commerce agent: library/, billing/, learning/.
- Root Integration: config/, operations/, deployment, dependencies, Docker/CI, contracts/, documentation and final commits.

Coordinate interfaces directly between lanes. Do not edit another lane's files or commit/push independently. Use separate MAISON_TEST_DB_NAME values for concurrent tests. Only actual feature rights, real adapter/device acceptance, authentication/spending facts and failing applicable checks may stop the affected release; avoid new services, wrappers and redundant approvals.


Owner database amendment,18November2026: retain the existing Neon PostgreSQL18 project and update the version baseline after compatibility verification. For the current Neon migration and first-book acceptance task, leave the existing platform unchanged; no cutover or paid provisioning is included.
