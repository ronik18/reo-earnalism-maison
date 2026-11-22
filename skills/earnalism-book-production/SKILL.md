---
name: earnalism-book-production
description: Prepare and release Earnalism Reader editions, covers and pre-produced media through Maison's supported revision workflow, preserving exact editions, complete active-region rights and verified assets.
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

Use the [general source importer](https://github.com/ronik18/reo-earnalism-maison/blob/main/docs/EARNALISM_GENERAL_IMPORT.md)
for retained English/Bengali books, lessons and episodes. The existing reviewed
`EN-071` route stays unchanged. General import reserves a denied draft, uses
existing private source Asset upload/completion, and verifies/packages its exact
source under CAS. It supplies actual edition/revision/unit IDs and content hash;
it creates no rights approval, preview, offered format or publication. Keep the
original source bytes and declared NFC Reader derivative separately identified.
Do not fetch or generate missing source from a title alone.

Private R2 upload/state/completion and managed signed Stream TUS intake handle
eligible prepared media. `python manage.py verify_media_asset` verifies actual
processing; already-uploaded Stream has a separate source-manifest route. None
of these generates content or publishes it. Prepare live-provider acceptance
through the same notebook/common CLI, with execution disabled and actual account,
source, rights and format holds retained.

Use `GET /api/v1/staff/editions/<edition-id>/review` and existing `validate`,
`mark-ready`, `publish`, `schedule`, `withdraw` operations with exact revision,
expected hash, current ETag, operation ID and required reason. Scheduled publication
rechecks the same gates. Reconcile uncertain writes before another mutation.

Use [publication-policy.json](https://github.com/ronik18/reo-earnalism-maison/blob/main/contracts/publication-policy.json) as the
authoritative **active whitelist (nine launch territories since the 22 November 2026 owner amendment; 38 deferred)** and [book policy](https://github.com/ronik18/reo-earnalism-maison/blob/main/docs/BOOK_PUBLICATION_POLICY.md).
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


For private output delivery, use the common source-bound bundle and
[Colab-to-Maison/social handoff](https://github.com/ronik18/reo-earnalism-maison/blob/main/docs/EARNALISM_PRIVATE_HANDOFF.md).
Prepare verifies retained bytes without provider requests. Explicit private staging
reuses existing draft intake and nonpublic provider adapters; it does not grant
publication, rights or performance acceptance. Reuse measured timing and original
assets; never recreate narration/music/visuals merely to transfer them.
