---
name: earnalism-covers
description: Design and prepare Earnalism front/back cover pairs, then use Maison's private asset and exact-revision publication workflow while preserving approved artwork and edition rights.
---

# Earnalism cover pairs

Use the [canonical audiovisual pipeline](https://github.com/ronik18/reo-earnalism-maison/blob/main/docs/EARNALISM_AUDIOVISUAL_PIPELINE.md)
in [ronik18/reo-earnalism-maison](https://github.com/ronik18/reo-earnalism-maison)
and `earnalism-book-production`. Design-only ends with local candidates; explicit
production direction carries routine work within the pair's scope. It does not
activate audio or alter text, prices, regions or unrelated availability.

Resolve the exact edition; inspect synopsis/passages, current covers, publisher
identity, series dimensions and checkpoint. Reuse approved bytes/prior uploads by
hash. Use built-in image generation for missing original content-themed artwork.
An animated-film illustration style is not actual motion. Keep generated art free
of lettering; add exact title, author and verified publisher details through
editable deterministic typography. Never invent ISBN, address or endorsement.

Inspect front/back at full and card size for source accuracy, spelling, clipping
and contrast. Preserve art, editable layout, font-use/provenance evidence and
delivery exports. Inspect current dimensions/performance limits rather than
assuming old examples. `scripts/prepare_pair.py` packages already-final web files
without resizing/re-encoding; it never uploads, approves or publishes:

```sh
python3 <this-skill>/scripts/prepare_pair.py \
  --slug the-selfish-giant --book /path/to/current-public-book.json \
  --front /path/to/final-front.webp --back /path/to/final-back.webp \
  --output /path/to/new-cover-pair
```

For Maison, inspect current draft/live revision and supported staff asset intake.
Use bounded private R2 upload/state/completion and cover-pair evidence through
existing staff/admin mechanisms, with one writer for the same edition. Uploads
belong to drafts; a live edition needs its supported new-revision workflow, not
direct live-row edits. Candidate upload alone is not validated publication.
Preserve previous cover/rollback identities.

Bind the pair and consumed provenance/clearance to exact revision/assets. Reuse
unchanged text/audio evidence where its bindings remain valid. Do not overwrite
concurrent manifests. Complete 47-region edition/offered-format clearance still
applies. Historical static `frontend/public/assets/books/` promotion paths and
direct cover APIs are not assumed Maison capabilities.

Use actual review/validation/revision transitions in the guide. Deploy only when
the actual serving implementation needs it, preserving protections and current
automatic-deployment settings. Occupied worktrees do not block independent cover
preparation; the Integration Lane owns authoritative publication truth.

Verify both selected covers in the served edition on desktop/mobile; compare
delivered original-byte hashes where supported, and preserve intended text/audio
availability. If one side or an uncertain mutation succeeds, retain partial state
and reconcile before another write. Claim the pair LIVE only with serving proof.

The exact [installed entrypoint snapshot](references/installed-entrypoint-20261121.md)
retains historical source/provider guidance. Those paths are provenance until
verified in the actual serving system; renaming repository URLs creates no adapter.
