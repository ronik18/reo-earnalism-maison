# General private English/Bengali source import

The same [production notebook](../notebooks/Earnalism_Production_Orchestrator.ipynb)
and common CLI now accept any title through a source-bound private draft workflow.
The original reviewed `EN-071` packet route remains unchanged. General import has
no title allowlist and supports English/Bengali chapter, lesson and episode units;
it never creates rights approvals, offered formats, previews or publication.

## Prepare exact retained source

Supply two existing local JSON files: a metadata manifest and the complete source.
The [OpenAPI schemas](../contracts/openapi.yaml) `GeneralBookImportManifest` and
`GeneralBookSource` define their fields. The source has language, ordered units
with stable keys, and ordered paragraphs with explicit `paragraph`, `heading` or
`verse` kinds. No source or provenance string is executed or fetched as a URL.

Metadata identifies the work/edition, author, house, original source SHA256/bytes
and provenance/rights references. A reference records a claim or document; it does
not establish legal clearance. The existing complete 47-region publication policy
still applies to each future offered format/action.

```sh
python -m operations.production_delivery book-import \
  --import-manifest /private/book/import-manifest.json \
  --source /private/book/source.json \
  --output /private/book/new-preparation-receipt.json
```

This default performs no authentication, provider request, generation or import.
It verifies the exact source bytes and preflights all source/Reader limits. An
existing receipt path is rejected before any dispatch; originals are not replaced.

The supported source is at most 4MiB, 128 unique units and 50,000 source paragraphs.
Each paragraph is at most 48KiB UTF8 and 32,000 characters before and after NFC.
Reader batches hold at most 100 paragraphs and 60KiB canonical raw bytes, with at
most 128 packages. The package ceiling therefore permits at most 12,800 paragraphs,
and possibly fewer when byte limits apply. Unsupported layouts are rejected
before HTTP, without splitting a supplied paragraph or silently dropping content.

## Existing private operations

An authorized operator may add `--execute --journal /private/book/journal` using an
existing permitted Maison staff session (`MAISON_ORIGIN`, `MAISON_SESSION_COOKIE`,
`MAISON_CSRF_TOKEN`). Saved notebook defaults remain disabled; this documentation
and a valid source do not grant execution or publication authority.

1. `POST /api/v1/staff/books/imports` with `{"manifest": ...}` reserves an empty
   actor/source-bound draft. Reader/audio/video are denied, downloads are false,
   preview is empty and no Rights record is created.
2. The client uploads the exact original JSON through existing revision-bound
   `reader_source` Asset intent/PUT/completion. Large source bytes bypass the
   normal 256KiB JSON request boundary; no global request limit is raised.
3. `POST /api/v1/staff/editions/<edition-id>/source-imports`, with a stable finalize
   operation ID and an ETag attributed to this import’s acknowledged mutations and exact owned ready source Asset,
   verifies raw bytes and prepares deterministic private Reader chunks outside
   database locks. A short transaction attaches all source units/paragraphs/chunks
   together and computes Maison's actual revision content hash.

The response supplies actual edition/revision/unit/Reader Asset IDs and a strong
ETag. Use those values when binding later audiovisual handoffs; the original
source-file hash is distinct from Maison's canonical revision hash. Re-run
preparation on the newly bound production bundle rather than copying invented IDs.
No narration, score, video, new model or GPU run is part of source import.

## Original source and explicit Reader derivative

The raw uploaded source and its SHA256 remain unchanged. Maison's existing Reader
serialization uses UnicodeNFC, so general import creates an explicit NFC derivative
of unit titles/paragraph text for its canonical database/Reader representation.
This includes Bengali canonically decomposing letters and decomposed Latin accents.
Spelling, whitespace and paragraph boundaries are not rewritten.

The result's `source_transform` records the method, original raw SHA, canonical
source SHA and changed title/paragraph counts. Both original and derived identities
remain available; a canonical Reader derivative is never called byte-identical
to its original. This preserves the existing serializer and Reader coverage rules.

## Reconcile a finite import

Keep the private journal. Lost draft/finalize responses reuse the same operation;
a lost PUT is never repeated blindly. Finalize replay checks actual source,
canonical text, unit identities and the complete Reader Asset set before reporting
success. Concurrent edits, foreign actors, missing assets or frozen revisions hold.
A bounded preparation failure retains immutable source/object identities for an
explicit same-operation reconciliation; it does not attach partial source text.

The importer is software-tested against isolated PostgreSQL 18 with provider HTTP
mocked. Actual deployed staff access, R2 transfer and private customer paths are
separate provider-acceptance evidence. See the
[private provider plan](EARNALISM_PRIVATE_PROVIDER_ACCEPTANCE.md). Do not infer
release readiness from a source import or local fixture.
