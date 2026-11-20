---
name: earnalism-book-production
description: Prepare and release Earnalism Reader editions, covers and pre-produced media through Maison's supported revision workflow, preserving exact editions, complete 47-region rights and verified assets.
---

# Earnalism book production in Maison

Read the [canonical audiovisual pipeline](https://github.com/ronik18/reo-earnalism-maison/blob/main/docs/EARNALISM_AUDIOVISUAL_PIPELINE.md)
in [ronik18/reo-earnalism-maison](https://github.com/ronik18/reo-earnalism-maison),
current AGENTS.md and the preserved
[supported release workflow](references/release-workflow.md). Standing authority,
source preservation and one Integration Lane continue to apply. Historical
provider/charging procedures belong to their actual system; Maison's current code
and API define Maison operations.

Resolve exact edition, language, complete text, chapter/paragraph structure,
offered formats/actions and title checkpoint. Reuse cleared sources, approved
covers and healthy media by hash. Keep rights/source evidence private; strip
boilerplate from customer content only where permitted. Import-only creates draft;
an explicit release request continues routine steps when actual title gates pass.

Read `book_import_manifest.json` for identity where relevant, but do not assume
every row has an importer. Current `POST /api/v1/staff/books/imports` accepts only
the reviewed `EN-071` Selfish Giant packet and always creates a draft. General
Colab book/episode import is not implemented by copying these skills. For an
unsupported title prepare cleared source and a private hash-bound handoff.

Use existing staff/admin mechanisms for revision content, rights and factual
validation evidence. Private R2 upload/state/completion and
`python manage.py verify_media_asset` handle eligible prepared media.
Already-uploaded signed Stream video has separate manifest verification; ordinary
upload currently rejects video. None of these generates content or publishes it.

Use `GET /api/v1/staff/editions/<edition-id>/review` and existing `validate`,
`mark-ready`, `publish`, `schedule`, `withdraw` operations with exact revision,
expected hash, current ETag, operation ID and required reason. Scheduled publication
rechecks the same gates. Reconcile uncertain writes before another mutation.

Use [publication-policy.json](https://github.com/ronik18/reo-earnalism-maison/blob/main/contracts/publication-policy.json) as the
authoritative **47-region whitelist** and [book policy](https://github.com/ronik18/reo-earnalism-maison/blob/main/docs/BOOK_PUBLICATION_POLICY.md).
Every offered format/action needs legal compliance for the exact text/assets in
every active region, including applicable distribution/public-domain permissions.
Keep private clearance hash-bound. Term expiry, artwork, draft review or CI is not
full clearance. A missing region holds the title; never silently narrow scope,
add a wildcard or expand from research alone. AE/Mainland CN are excluded;
HK/MO/TW remain separate. Deny pending, unknown and excluded jurisdictions.

Apply `earnalism-audiobook-go-live` with final-roster title pins and actual
performance/fidelity evidence, prepared renditions and complete measured maps.
Coordinate themed cleared score/source-bound visuals through the guide. Preserve
Open Window's exact soundtrack/style and approved cover pair.

Validate customer discovery, text/navigation, exact covers, applicable protected
playback/ending, rights and access/accounting. Reader-only release can proceed
under its own clearance while audio/video is held. Keep exact reviewed revisions,
current deployment rules and one release writer. Behind-main work is reconciled
without losing concurrent changes; it is not a blanket implementation stop.

Report per-title state, actual revision/asset IDs and missing evidence. Do not claim
generated, trained, published or LIVE without proof. The exact
[installed entrypoint snapshot](references/installed-entrypoint-20261121.md)
preserves provenance; it does not install historical scripts in Maison.
