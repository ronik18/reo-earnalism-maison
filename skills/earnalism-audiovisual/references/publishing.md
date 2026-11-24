# Publishing

Publish only when the owner says so, and only to the destinations the owner names.
Root/Integration owns provider mutations; this skill prepares and stages.

## Maison: audio and full films (R2); social: reels and trailers

- **Audio** (chapter MP3s plus measured timing maps, private R2 intake) is allowed.
- **Full films go to Maison from private R2** (owner decision, 24 November 2026; this
  replaces the earlier Cloudflare Stream route, which stays unprovisioned). The film is a
  progressive faststart MP4 in the private bucket, served only through a short-lived signed
  GET after an entitlement check, never cached (`contracts/cache-policy.json`
  `private_r2_film`). Films built from stills and narration are small (the 21-minute
  বিচারক film-01 is about 13 MB), so adaptive streaming is not needed.
- **YouTube and other social destinations get reels, Shorts and trailers**, each pointing to
  the full film on Maison. Full films are not posted to social platforms.
- Maison's film delivery path (grant endpoint and player) is not built yet; until it is,
  films are produced, reviewed and archived but not offered on Maison.
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

### Film bundle (full film to private R2)

After the film's `qc` passes (and the owner's review):
`python3 -m eav.cli bundle-film --root <root> --film film-NN --unit-id <Maison unit UUID>
--out <bundle dir>` writes `film.mp4` (copy), `film.vtt` (the SRT with WebVTT timestamps)
and `film.json` (schema `earnalism.audiovisual-film-bundle.v1`: unit id, file names, SHA-256
of each, `duration_ms`, `bytes`). It refuses without a passing film `qc` whose recorded
SHA-256 matches the current film MP4, when the MP4 is not faststart (moov before mdat),
when it is not exactly one H.264 video stream plus one AAC audio stream, or when it is over
1 073 741 824 bytes. The server step `attach_audiovisual_film` (root lane) stages this
bundle; it publishes nothing by itself, and publication still needs exact-edition clearance
for the `video` format in every active region. Validate and publish a film only through
`attach_audiovisual_film publish`, never the staff web publish action: validation hashes the
whole film, which can outlast a web request.

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
