# Owner publication policy — active regions only

17November2026. UAE (AE) and Mainland China (CN) are out of scope. All13 other pending jurisdictions are excluded from the active launch scope and whitelist. Their earlier research is retained for history, not as an active launch blocker or permission. HK, MO and TW retain their separate previously assessed entries. This change does not claim all of Asia remains in scope.

**Owner amendment, 22 November 2026:** the active publication whitelist in `contracts/publication-policy.json` is the nine launch territories **IN, US, GB, BR, SG, MY, ID, PH, TH**. The other 38 previously whitelisted regions are listed under `deferred` (not cleared and not out of scope; each needs its own owner decision to return). UAE/Mainland China stay out of scope and the 13 pending jurisdictions stay excluded. Exact-edition compliance is required across every **active** region and offered format/action.

The authoritative whitelist is `contracts/publication-policy.json`. Publish future books only when the exact edition, cover/assets and every offered format/action are legally compliant in **every** whitelisted region. A book lacking clearance in any active region remains draft/held until its rights are resolved. Do not silently remove a region for one title or add a region without explicit owner approval and evidence. New titles are not automatically cleared by an earlier title's public-domain assessment.

Use the existing rights records and revision validation evidence. `publication_regions` checks current read/preview/eligible-download rights for every offered format across the complete active whitelist. `publication_clearance` requires a private evidence reference, pass status, exact revision text hash, exact region/format set and ready-asset hash map; the evidence must establish applicable permissions/compliance, not merely claim them. Staff record factual evidence through the existing admin. Test-only fixture acceptance is labelled and cannot authorize production. Delivery rejects nonwhitelisted codes even if an accidental or wildcard rights row exists.

The Selfish Giant's47 draft Reader content grants remain unchanged. Its original-text term assessment is not retroactively relabelled as full publication clearance; no new legal pass is fabricated and its state/live pointer remain draft/null. Its existing desktop browser/cover evidence can be reused by hash, but that evidence does not establish permissions in every region.

The installed `earnalism-book-production` skill and its release-workflow reference contain this standing rule. Tracked copies are under `.agents/skills/earnalism-book-production/` in the dedicated Maison repository, so the guidance survives repository handoff. The vendor plugin cache was not edited or published. The owner's memory update is stored through the permitted memory-note mechanism.

Next integration action: continue the approved implementation sequence for these47 regions and collect the exact book's complete whitelisted-region publication evidence before invoking the existing mark-ready/publish transition. No paid infrastructure, legacy application mutation or publication occurs in this policy update.

Verification: all80 PostgreSQL tests passed; both installed and tracked skill folders validate and their entry/reference bytes match. The restarted loopback Maison server returns HTTP200. Actual draft inspection confirms all47 Reader grants remain, every excluded code is denied, the live pointer is null and missing all-region publication evidence blocks release. See docs/evidence/publication-whitelist-application.json and publication-whitelist-full-suite.log.

## Owner clearance decision, 23 November 2026: The Selfish Giant and বিচারক

The owner directed that the staff web sign-in is not required for these two editions. The owner also authorised the integration lane to make the clearance call from the legacy library records. For these two exact editions only, three things together are the publication clearance across the nine active launch territories for Reader read/preview:

- the per-territory public-domain term evidence;
- the text-source licence: Project Gutenberg #902 for The Selfish Giant, and Bengali Wikisource under CC BY-SA 4.0 for বিচারক;
- the owner-held cover provenance.

This does not cover downloads, audio, video, other editions or other territories. Evidence: `docs/evidence/publication-clearance-20261123.json`, bound in each revision's `publication_clearance` by document SHA256, exact text hash and every ready asset hash. Browser acceptance is in `docs/evidence/publication-browser-20261123.json`. Publication runs `python manage.py publish_cleared_editions {import|evidence|publish|status} --publisher <public_id>`, which uses the same audited services and validation gates as the staff API. বিচারক's source, manifest, cover pair and legacy rights records are in `library/intake/bicharak/`.
