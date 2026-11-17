# Draft intake API

POST /api/v1/staff/books/imports accepts exactly {"manifest_id":"EN-071"}. Requires verified session, CSRF, library.publish_revision and UUID4 Idempotency-Key. The server selects a retained approved packet; clients cannot supply rights, source paths, publication state or arbitrary URLs. Mutation and durable receipt share a transaction. Exact replay returns the same201 response; changed input under a key conflicts. A separately imported slug conflicts without overwrite.

201 returns edition_id, edition_revision_id, slug, state="draft", sha256 and paragraph_count. No live pointer is assigned. Source/license evidence is private and excluded from the customer document.

GET /api/v1/staff/drafts/{revision_id}/document requires the same staff permission. Returns title, state, edition_revision_id, sha256 and ordered units with canonical paragraphs. Always private/no-store. It never authorizes customer media delivery. Anonymous requests401; members without permission403; non-draft/missing revisions404. Drafts remain excluded from member catalog/manifest/grants. Existing review/publication API retains separate cover, browser/hash and rights gates.


Staff review now reuses the real SSR title/Reader, private progress/annotation/completion, Saved and Finished flows for the latest draft of an unpublished edition. Verified active staff with content-publisher permission are required; ordinary members and guests remain denied. The live revision pointer is changed only in memory for that staff rendering/service request, never saved. Publishing requires the existing separate transition operation and is not invoked by review.

GET /api/v1/staff/draft-editions/{edition_id} returns DraftEdition, including published_at:null. GET /api/v1/staff/draft-covers/{asset_id} returns only verified ready cover bytes belonging to a draft. Both require publisher permission and private/no-store. Public catalog endpoints continue to exclude drafts. Current cover_pair.front/back IDs select the attached pair; older uploads are retained rather than silently served or deleted.


### Requested-country review (17 November 2026)

EN-071 remains server-selected and always draft. Intake countries come from the private packet and must match the exact-text rights assessment and its approved decisions. The current private assessment lists62 requested codes, including Brazil and whole Asia:47 original-English Reader read/preview decisions and15 denied/pending. Runtime country lists come from that fixed reviewed packet, never an Asia wildcard. A changed text hash or territory/review mismatch returns409 `rights_review_mismatch`; it never silently grants a wildcard or publishes. Existing idempotent import receipts remain unchanged; a repeated import is not an existing-draft rights mutation. Use the existing staff rights admin to reconcile the imported draft. Public response shape is unchanged and never exposes source URLs or evidence.
