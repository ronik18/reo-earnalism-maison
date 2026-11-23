# Publishing

Publish only when the owner says so, and only to the destinations the owner names.
Root/Integration owns provider mutations; this skill prepares and stages.

## Maison: audio yes, video held

- **Audio** (chapter MP3s plus measured timing maps, private R2 intake) is allowed.
- **Video via Cloudflare Stream is held** until the owner confirms Stream's cost. The film
  is still produced, reviewed and offered to the social destinations the owner names.
- Access defaults to `free`, matching the Reader offering.

### Steps

1. After a passing `qc` of the assembled film (and the owner's review),
   `python3 -m eav.cli bundle-audio --root <root> --out <bundle dir> --score-dir <dir>
   --score-route vcsl|ace-step:<music job_id>` writes one 96 kbps MP3 per Maison unit: the narration with its best-fit background
   score (`<unit_id>.wav` per chapter from `earnalism-audiobook-score`), ducked under
   speech and mastered to −16 LUFS by `eav.mix.duck_and_master`. It refuses without a
   score, or when a bed is shorter than its chapter. `--dry` (narration only) is allowed
   only when the owner asks for it, is mastered to the same −16 LUFS / −1 dBTP gate and is
   recorded in the evidence draft. It also writes `timing.json` (paragraph segments
   measured by `eav.film.narration_track`, plus a `provenance` block). It also writes
   `<root>/maison/audiovisual-clearance-evidence.draft.json`
   (schema `earnalism.audiovisual-clearance-evidence.v1`) with `status: DRAFT_NOT_APPROVED`,
   `territories: []`, `term_per_territory: {}`, `text_source_licence: null`,
   `cover_provenance: null` and `owner_approval: null`; the score's route and licence
   (VCSL CC0-1.0, or ACE-Step Apache-2.0 with its music job id) are filled in.
   `stage` refuses it as written.
2. **Clearance (per title).** The owner pre-authorised the public-domain pattern of
   `docs/evidence/publication-clearance-20261123.json` for audio and video. The agent
   prepares the draft: territories = the active whitelist, term per territory,
   text-source licence, cover provenance, generator and music licences, asset hashes.
   **The owner approves it**: the owner (not the agent) sets `owner_approval`
   `{"by": <who>, "at": <ISO time>}` and a non-draft `status`; it is saved under
   `docs/evidence/`. **`stage` enforces this**: it refuses a status starting with
   `DRAFT`, a missing/blank `owner_approval`, a `term_per_territory` that misses any
   whitelisted territory, a missing `text_source_licence` or `cover_provenance`, or a
   `music` record without route, licence and source (unless `dry_narration` is true),
   and changes nothing. The agent never
   fills in the approval, never edits `publication_clearance` or rights rows by hand.
   Non-public-domain titles are refused.
3. Server (root lane): `python manage.py attach_audiovisual_audio stage <slug> --publisher
   <public_id> --bundle <bundle dir> --evidence docs/evidence/<file>.json`. It clones the
   live revision into a draft, stores the MP3s privately and validates the timing.
4. Export the staged draft (`export_audiovisual_source <slug> --revision <id>`), rebuild a
   local replica and browser-test the reader and audio player against the same
   content_sha256. Write the report `{"sha256", "status": "pass", "scope", "checks":
   {"audio_playback": true, ...}}`.
5. `attach_audiovisual_audio publish <slug> --publisher <public_id> --browser-report
   <report.json>` runs full validation and publishes, or changes nothing.

## Social

- Private staging first through the official adapters:
  `python -m operations.production_delivery prepare` then `social-stage --platform
  <youtube|instagram|facebook|x> --action private-upload`. There is no public CLI action.
- Post publicly only to platforms named in the owner's instruction. A Maison release does
  not authorise social posting, and a finished package does not either.
- Social posting of a public-domain story adaptation needs no Maison format grant, but it
  does need the owner's destination instruction.
- Caption: the reel's `caption.txt`. Turn on each platform's AI-content label; the reel
  already carries "AI-generated visuals" for 3 s. Cover = frame 1. Music: "Original
  audio", licence recorded in the production record.
