---
name: earnalism-covers
description: Design, upload, replace and publish an Earnalism book’s front and back covers as one pair, using content-themed illustrated artwork and the existing canonical cover workflow.
---

# Earnalism covers

Take a title or slug and existing cover files, or design the missing pair from the book’s content. Complete the requested outcome; a request to upload/update covers in production or GO LIVE authorizes the narrow cover release. A design-only request ends with local candidates. Do not activate audio or alter text, prices, territory or title availability.

## One pair, one workflow

1. Resolve the exact book from current catalogue metadata. Read its synopsis and representative source passages. Inspect current covers, publisher branding, dimensions and the title’s existing cover checkpoint. Apply the available `earnalism-book-production` skill and current repository AGENTS.md. Reuse approved files and prior successful uploads by checksum; never regenerate a healthy approved pair.
2. When designing, use the built-in image-generation tool for original, content-themed illustration. “Animated themed” normally means an animated-film illustration style; create actual motion only when requested, with a static fallback. Match the current series aspect ratio and publisher treatment. Current examples use 2:3, with 1600×2400 masters and 800×1200 web images; inspect rather than assuming. Keep generated art free of lettering. Add the exact title, author and verified publisher details through deterministic editable typography. Use verified publisher identity; do not invent an ISBN, postal address, copyright owner or endorsement. Preserve original art and editable layout. Retain actual provenance and font-use evidence; do not invent rights acceptance or quality scores.
3. Inspect the finished pair at full and card size. Correct clipping, inaccurate story imagery, spelling, contrast and publisher details. Use the existing cover validator. Export web images within current performance limits; keep masters separate. `scripts/prepare_pair.py` packages the two already-final web files into one checksum-addressed handoff. It copies bytes without resizing or re-encoding, never uploads and never grants approval.
4. Complete production through the existing canonical path described below. An explicit owner production instruction is the approval to perform routine work within this pair’s scope; reuse it without another GO/NO-GO question. If the artwork is materially changed afterward, do not mislabel the changed version as the previously approved bytes. Ask only for genuinely missing rights, credentials, spending or a platform-required owner action, with the operation fully prepared.
5. Verify the actual public book response and rendered cover, fetch both final image URLs and compare delivered bytes with selected web hashes. Check desktop/mobile display and that Reader/audio availability is unchanged. Report LIVE only after serving proof. Otherwise state the exact blocker, preserved progress and next integration action.

## Canonical production path

Owner direction, 29 October 2026: cover GO LIVE is independent of pending PRs and parallel changes. Do not make an asset-only cover publication wait for PR merges, an occupied source worktree or unrelated release work. Prefer the existing authenticated direct cover publication path, with one writer for the same title and short serialization only for an actual conflicting mutation. Coordinate with the Integration Lane for release truth, not as an exclusive queue for unrelated work.

- Inspect existing intake and promotion capabilities first. Use authenticated admin cover intake/status and canonical promotion when enabled and suitable for the title. Reuse a stored candidate only when slug, side, checksum and immutable delivery identity match. Never enable general uploads or alter production flags merely to make a cover update work.
- For controlled static covers, use the existing content-addressed `frontend/public/assets/books/<slug>/` path and mirrored controlled-publication records through the sole Integration Lane. This is the normal alternate path when runtime cover intake is disabled or the running container lacks writable mirrors; do not demand a writable production checkout or invent a new upload service.
- Preserve previous covers/rollback pointers. Rebind only the affected cover provenance, approval evidence, catalogue fields, checksum/publication/rights bindings and derived bootstrap/SEO records that actually consume those bytes. Preserve text and audio evidence exactly. Reuse current repository validators/builders instead of recreating their schemas. Never copy an old whole manifest over concurrent work.
- For a supported runtime asset update, use its authenticated publication operation and verify the exact pair; no application deployment or PR merge is inherently required. If the current static-backed implementation genuinely needs a source deployment, prepare an isolated cover-only change against the actual serving source and identify its exact required platform gate. Do not bundle pending main changes or wait on unrelated PRs. Follow protections that actually apply to that deployment; do not remove protected approvals or deploy unreviewed application code. Keep automatic deployments off. Source integration must preserve parallel work and remain narrowly coordinated with the Integration Lane.
- Treat front/back as one user outcome. If only one side succeeds, report partial state and reconcile before another write; do not claim the pair is LIVE or blindly repeat uploads. Timeout or uncertain mutation: read-only reconciliation of existing candidate/audit/deployment receipts before retry. Do not reset an unresolved intent or remove platform protections.

## Quick preparation

```sh
python3 <this-skill>/scripts/prepare_pair.py \
  --slug the-selfish-giant \
  --book /path/to/current/public_book.json \
  --front /path/to/final-front.webp --back /path/to/final-back.webp \
  --output /path/to/new-cover-pair
```

One request should be enough: “Use $earnalism-covers to update The Selfish Giant’s front and back covers in production using these files.” Continue from prepared pair through the authorized canonical release; do not return only a plan or preparation receipt when production was requested. An occupied Integration Lane or pending unrelated PR is not a cover-publication blocker. Continue independent asset preparation and the supported direct publication path, coordinating only actual same-title conflicts. If a required capability is absent, name that capability precisely and prepare the narrow remedy; do not disguise it as a generic merge dependency or claim LIVE before verification.
