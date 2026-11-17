---
name: earnalism-book-production
description: Prepare and release Earnalism Reader editions, covers and audiobooks through the supported title workflow, reusing approvals and verified assets while preserving rights, quality and accurate accounting.
---

# Earnalism Book Production

Read [the supported release workflow](references/release-workflow.md) for any cover, Reader or audiobook generation/publication task. Use current repository AGENTS.md, active intelligence files and title checkpoint as live authority. Do not copy stale branch, provider or voice defaults from old instructions.

Use the existing Earnalism admin/import API and manifest for imports. Read book_import_manifest.json unless another manifest is specified; download only cleared sources, validate commercial use and strip source/license boilerplate from customer content as permitted. Keep rights/source evidence internal. Import-only work defaults to draft; an explicit release request proceeds under its recorded standing authority without repeated GO/NO-GO approval cycles.

## Whitelisted-region publication policy

Owner instruction,17November2026: publish a book only when its exact edition and every offered format/action are legally compliant in **all active whitelisted regions**. Use the active project's authoritative region list; Maison uses `contracts/publication-policy.json` in the dedicated `reo-earnalism-maison` repository. UAE (AE) and Mainland China (CN) are out of scope. Pending, unknown and other excluded jurisdictions are not whitelisted and must not receive delivery. HK, MO and TW retain their separately assessed entries; do not silently merge their regimes with CN.

Keep country/source/permission evidence private and bind clearance to the exact text and assets. Original-text term expiry, draft review, generated artwork or CI success alone is not full publication clearance. Resolve any applicable distribution/public-domain permission and format/download licence in every whitelisted region before publishing; otherwise keep the book draft/held. Do not silently narrow the whitelist for a difficult title, expand it from research alone, or add a worldwide wildcard. Change the approved whitelist only with supported evidence and explicit owner approval. Excluded jurisdictions do not block work for the approved scope. This policy does not itself publish a title, authorize paid infrastructure or replace the approved HLD/LLD and existing release checks.

For audiobook production/release, apply the available earnalism-audiobook-go-live skill and current campaign policy. Reuse accepted masters, measured alignment and immutable receipts; never silently substitute a fallback voice or provider. For covers, use the approved originals and existing canonical promotion workflow rather than repeat uploads or a new runtime architecture.

Validate the affected customer journey and complete relevant release checks. Publish only with sufficient rights and title scope and passing quality/access/accounting gates. Preserve Reader-only availability when audio is held. Maintain one release lane, exact merged-main manual deployments and automatic deployments OFF.

Report actual status per title, material limits, uploaded IDs/slugs or skipped reasons when importing, and one next integration action. Do not claim generated, published, highly available or LIVE without corresponding evidence.
