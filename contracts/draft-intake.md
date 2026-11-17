# Draft intake API

POST /api/v1/staff/books/imports accepts exactly {"manifest_id":"EN-071"}. Requires verified session, CSRF, library.publish_revision and UUID4 Idempotency-Key. The server selects a retained approved packet; clients cannot supply rights, source paths, publication state or arbitrary URLs. Mutation and durable receipt share a transaction. Exact replay returns the same201 response; changed input under a key conflicts. A separately imported slug conflicts without overwrite.

201 returns edition_id, edition_revision_id, slug, state="draft", sha256 and paragraph_count. No live pointer is assigned. Source/license evidence is private and excluded from the customer document.

GET /api/v1/staff/drafts/{revision_id}/document requires the same staff permission. Returns title, state, edition_revision_id, sha256 and ordered units with canonical paragraphs. Always private/no-store. It never authorizes customer media delivery. Anonymous requests401; members without permission403; non-draft/missing revisions404. Drafts remain excluded from member catalog/manifest/grants. Existing review/publication API retains separate cover, browser/hash and rights gates.
