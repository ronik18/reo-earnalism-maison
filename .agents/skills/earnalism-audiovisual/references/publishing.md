# Publishing

Publish only when the owner says so, and only to the destinations the owner names.
Root/Integration owns provider mutations; this skill prepares and stages.

## Maison: audio yes, video held

- **Audio** (chapter MP3s plus measured timing maps, private R2 intake) is allowed.
- **Video via Cloudflare Stream is held** until the owner confirms Stream's cost. The film
  is still produced, reviewed and offered to the social destinations the owner names.
- Access defaults to `free`, matching the Reader offering.

### Steps

1. `python3 -m eav.cli bundle-audio --root <root> --out <bundle dir> --score-dir <dir>`
   writes one 96 kbps MP3 per Maison unit: the narration with its best-fit background
   score (`<unit_id>.wav` per chapter from `earnalism-audiobook-score`), ducked under
   speech and mastered to −16 LUFS by `eav.mix.duck_and_master`. It refuses without a
   score; `--dry` (narration only) is allowed only when the owner asks for it and is
   recorded in the evidence draft. It also writes `timing.json` (paragraph segments
   measured by `eav.film.narration_track`, plus a `provenance` block). It also writes
   `<root>/maison/audiovisual-clearance-evidence.draft.json`
   (schema `earnalism.audiovisual-clearance-evidence.v1`) with `territories: []` and
   `owner_approval: null`, so `stage` refuses it as written.
2. **Clearance (per title).** The owner pre-authorised the public-domain pattern of
   `docs/evidence/publication-clearance-20261123.json` for audio and video. Complete the
   draft: territories = the active whitelist, term per territory, text-source licence,
   cover provenance, generator and music licences, asset hashes. Get the owner's approval
   and save it under `docs/evidence/`. Claude never marks clearance on its own, never
   edits `publication_clearance` or rights rows by hand. Non-public-domain titles are
   refused.
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
