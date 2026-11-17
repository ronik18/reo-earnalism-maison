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
