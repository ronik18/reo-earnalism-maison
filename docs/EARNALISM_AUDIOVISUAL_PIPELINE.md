# Earnalism audiovisual production in Maison

The canonical repository for this coordination guide and its six skill copies is
[ronik18/reo-earnalism-maison](https://github.com/ronik18/reo-earnalism-maison).
Use one content instruction, one durable production record and one release writer.
Prepare independent books/topics in parallel; serialize actual shared-model work
and mutations of the same edition or release record. Reuse the owner's existing
Colab notebook and retained inputs instead of creating a supervisor or notebook
for each stage. The checked-in notebook copy and private delivery adapters below
connect retained outputs to existing destinations. They do not generate cleared
source or certify performance and live provider acceptance.

## Instruction to finished candidate

An instruction such as “Prepare the Bengali cinematic audiobook of বিচারক” or
“Prepare Metal Rust for EverydayScience” resolves an exact edition or registered
episode, language, audience, intended length, requested formats and destinations.
Resolve ambiguous titles/queue entries from the existing catalogue/checkpoint;
do not invent the next episode or substitute a different edition. “GO LIVE ready”
means a completed, assessed candidate. Publication additionally requires the
owner's applicable release authority and the supported destination operation.

| Stage | Skill and required result |
|---|---|
| Source and edition | `earnalism-book-production`: complete cleared text or researched factual script, source hashes, chapter/paragraph boundaries, exact edition and offered-format rights. |
| Narration | `earnalism-audiobook-go-live`: final-roster/title pin, actual model/runtime/preset identities, source-bound spoken text, dry native masters and separately assessed performance. |
| Score | `earnalism-audiobook-score`: cleared themed music/ambience, cue timing measured from the selected narration, ducking, transitions and purposeful silence. |
| Visuals | `earnalism-video`: source-bound shot plan, stable characters/settings, demonstrated actions and frame transitions, content-accurate diagrams and captions. |
| Covers | `earnalism-covers`: content-themed front/back pair, exact verified text/branding, editable masters and delivery derivatives. |
| Integration | `earnalism-book-audiovisual`: synchronized candidate, platform renditions, evidence, private review and one destination-bound release decision. |

Read the complete content before directing performance. Keep a compact context
map from whole work and chapter through paragraph, sentence and phrase: speaker,
intent, emotional turn, factual meaning, pronunciation and required on-screen
action. Local expression must follow that context. A suspenseful word does not
justify making an entire explanation frightening. Performance directions are
unspoken controls supported by the actual engine; they never enter the narrated
text. Do not claim semantic or acting review from successful context extraction.

## Final voice roster and retained media

The owner chose these five base-model profiles as the final roster. Keep compatible
saved title pins and accepted recordings; ordinary content production does not
reopen speaker auditions.

| Content route | Default profile |
|---|---|
| English story | `en_tisha` |
| English tutorial/technical explanation | `en_mary` |
| Explicit English male route | `en_raghav` |
| Bengali story or explicit male route | `bn_arnav` |
| Bengali tutorial/technical or explicit female route | `bn_riya` |

Use the [private voice bank](https://drive.google.com/file/d/13e4EYrynikQqPbjIIxXy4oQxtf8wWJ4e/view)
and [existing voice notebook](https://colab.research.google.com/drive/1DTgjm3NeouooJ9ZVv6UIfYU0pvXtZiUy)
for actual model revisions, profile settings and current qualification receipts.
The approved current voice backend uses the five Parler base profiles; historical
B/Ryan choices remain only where an existing accepted title/audio pin requires
preservation. Do not treat them as new-content defaults. The
[private evidence folder](https://drive.google.com/drive/folders/17FQBpEtl2Nn8ipZ1k1dM6jFTug8rTBpp)
and [reviewed source companion](https://drive.google.com/file/d/1oBg_ueHgCtFuhSZckQRx4W41kxJjOOyz/view)
retain supporting receipts and runtime/helper source respectively. The companion
contains no model weights or credentials. Consult the mutable bank for the latest
actual run outcome; this guide does not freeze an in-progress qualification state.
The profile choice does not certify a newly generated recording. Retain native
audio and exact spoken text; assess missing/repeated words, Indian accent,
intelligibility, breathing/pacing, emotion and sustained consistency on the actual
candidate. ASR WER/CER and technical measurements are advisory evidence, never
invented listening, MOS, confidence or a premium-quality grade. Mark unassessed
dimensions explicitly. No new weight training is established by these skill edits.

Open Window keeps its exact retained soundtrack and owner-selected visual style.
Keep its source media, title pins, full original Clip2 reference and provenance
unchanged. Voice trials remain separate from that film until an explicitly
selected replacement and its affected synchronization are assessed. A reference
used only for comparison is not an audio-conditioning input or speaker transfer.

## Timing, score and visual composition

Freeze dry narration first. Measure actual word/paragraph/chapter boundaries and
bind timing to both source-text and audio hashes; estimated reading speed cannot
qualify synchronization. Retain dry masters before producing distribution audio.
Choose cleared score by narrative/factual purpose and energy arc, place cues at
measured boundaries, gently join compatible phrases and duck beneath speech.
Use silence for a turn, comprehension or a quiet passage. Check speech masking,
clipping, loudness, joins and the ending across the full mix; do not grade emotion
from a waveform. Exact owner KEEP ranges stay bound to their candidate hash.

Plan characters, objects, setting and shot continuity from the exact source.
Show the required action and expressive change in actual frames; camera pans or
animated stills do not prove character acting. For tutorials, preserve scientific
causality, units, labels and legibility. Transitions must support the content flow
without hiding errors or cutting words. Review opening, joins, demanding action
and the full ending in the actual synchronized export.

Compose each requested platform rendition for its own frame and reading distance:
Maison landscape/full-length and applicable YouTube, Instagram, Facebook and X
formats. Portrait/Shorts need intentional reframing or distinct composition,
readable captions and supported safe areas, not an automatic crop of a landscape
master. Keep the canonical `theearnalism` branding, approved in-video identity and
separate profile icon. Record each rendition hash, duration, captions, thumbnail,
metadata and destination. Publish only requested destinations; a private review
or Maison publication does not authorize social posting.

## Maison operations that exist

Read [AGENTS.md](../AGENTS.md), [the API contract](../contracts/api-contracts.md)
and [OpenAPI](../contracts/openapi.yaml) before a production mutation. The current
implementation supports the following operations; calling them still requires
the existing authentication, object permission and scope.

| Operation | Current implementation and boundary |
|---|---|
| Draft import | `POST /api/v1/staff/books/imports` in `library/intake_api.py` accepts the reviewed `EN-071` Selfish Giant packet only. It creates draft Reader content; it is not a general arbitrary-book importer. |
| Private asset intake | `POST /api/v1/staff/assets/uploads`, asset state and `/complete` use bounded, revision-bound direct R2 uploads. Current audio input is MP3; preserve native originals and create an explicitly identified derivative. Upload completion and provider processing must be verified. Video uses a private Stream TUS intent from the same endpoint, with revision/unit/source binding, encrypted short-lived capability and signed-URL privacy verified before returning the grant. |
| Pre-produced media verification | `python manage.py verify_media_asset <asset-id>` verifies eligible private draft audio/sample/video; it does not generate or publish. Audio additionally needs prepared-rendition evidence and measured maps. |
| Existing Stream video | `python manage.py verify_media_asset --stream-manifest <private.json> --actor-email <permitted-publisher>` verifies and registers an already-uploaded signed Stream rendition bound to its retained source and unit. This command does not upload video. The ordinary endpoint now also supports managed private video intake; neither route publishes. |
| Private production attachment | `GET/POST /api/v1/staff/editions/<edition-id>/production-handoffs`: cheap draft identity/ETag, then exact staged assets, measured maps and private QA/rights/caption references under existing staff session, CAS and operation receipts. No rights approval or listening pass is created. Audio piece/Stream readiness is independently checked; pending processing returns202. |
| Revision review and release | `GET /api/v1/staff/editions/<edition-id>/review`; `POST /api/v1/staff/editions/<edition-id>/{validate,mark-ready,publish,schedule,withdraw}` with the contract's revision ID, expected hash, current ETag, operation ID and reason as applicable. Draft → Ready → Live is enforced by `library/services.py`. |
| Scheduled release | `operations/publication.py` rechecks the exact Ready revision/hash/time and publisher authority, then uses the same publication transition. Scheduling does not bypass validation. |

Record rights, clearance, measured maps and actual browser acceptance through
supported staff/admin mechanisms using their current schemas. Validation binds
the exact revision text and ready assets, checks all offered formats/actions,
current rights, media integrity, covers, measured audio maps and browser evidence.
Only the Integration Lane reconciles an unknown write outcome and final release
state. Reuse receipts instead of repeating uploads or changing a live row directly.

For books, [publication-policy.json](../contracts/publication-policy.json) is the
authoritative **47-region whitelist**. Every offered format/action for the exact
edition and assets needs current clearance in every active region, including
applicable distribution/public-domain permissions. Keep evidence private and
hash-bound. Missing clearance holds the title; do not shrink the region set for
one book. AE and Mainland CN are excluded; HK/MO/TW remain separate entries.
Unknown, pending and other excluded jurisdictions must not receive delivery.
Reader-only publication can proceed under its own cleared scope while audio or
video remains held. See [the book policy](BOOK_PUBLICATION_POLICY.md).

## Runtime and historical boundaries

The copied skill references preserve prior Earnalism work, including links to
`ronik18/earnalism-digital-library`. Those are historical source/provenance, not
Maison serving paths. Use the checked-in
[existing notebook copy](../notebooks/Earnalism_Production_Orchestrator.ipynb)
and [private handoff instructions](EARNALISM_PRIVATE_HANDOFF.md). Run All is
execution-disabled. The common `python -m operations.production_delivery prepare`
verifies actual bundle bytes without provider requests; explicit `maison-stage`
or `social-stage` supports private staging only. There is no public CLI action.

The Maison adapter stages into an existing exact draft, reuses ordinary R2/Stream
intake and attaches measured maps/evidence through the new private endpoint.
Source WAVs and thumbnails remain retained provenance; server verification covers
only the exact staged subset. Stream verifies the original upload association,
provider UID, privacy and duration; it does not hash adaptive rendition bytes.
Unknown write outcomes require retained same-operation reconciliation; upload
creation is never retried blindly. The general arbitrary-title/episode source
importer remains unimplemented; the existing reviewed EN-071 import is unchanged.

Social adapters implement official YouTube private resumable video/captions/cover,
Instagram nonpublic Reels containers, Facebook Page draft Reels and X nonpublic
media. `social-stage --action private-upload` keeps temporary upload capabilities
in one process and reads processing once; it never posts publicly. Later checks
reuse acknowledged IDs and fresh provider status. Instagram/X have no private
feed-post equivalent. Separate cover/caption support varies by platform and is
reported explicitly. These adapters have local/mocked protocol tests; authenticated
live account permissions, real provider transfer/processing and served rendition
acceptance remain **unqualified** until actually exercised under applicable authority.
No service, account, purchase, publication or provider resource is provisioned by
this implementation. Never promote fixtures to customer-path acceptance.

## Finite review and reusable improvement

Use one candidate-bound review record: source/audio/video/rendition hashes,
reviewer or actual automated method, timestamp/frame range, observed finding,
preserve ranges, fix and resulting candidate hash. Reuse unchanged valid evidence.
Fix demonstrated defects in the smallest dependent span and revalidate affected
joins, captions, score/visual timing and required release gates. Do not regenerate
healthy narration, retrain, search voices or rerun unknown provider outcomes to
improve an imagined score. Preserve failed/unknown attempts and original counters.

Conclude each authorized pass with one terminal result: accepted within its
assessed scope, held for a named observed defect/missing evidence, or failed with
retained diagnostics. Collect owner review only where needed or requested; never
infer unperformed listening. Commit reusable, tested direction/routing improvements
through one integration writer. Weight training is a separate evidenced operation
requiring cleared data, pinned checkpoint, actual updates and a finite evaluation;
configuration changes and feedback aggregation are not training.

Release one exact candidate/destination set after applicable rights, fidelity,
performance, audiovisual/caption and customer-access checks actually pass. Verify
the served assets, protected playback/ending, correct per-format availability
and applicable billing/entitlement behavior. A GO LIVE instruction carries routine
work within recorded authority; private-only instructions remain private. This
guide grants no new purchases, runtime runs, publication or deployment authority.
