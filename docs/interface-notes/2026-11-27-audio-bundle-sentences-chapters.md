# Interface note: audiobook bundle gains chapters and sentence timing

From: audiovisual skill lane (`skills/earnalism-audiovisual`, eav Task 10). To: root integration and the
backend lane. Spec: `docs/superpowers/specs/2026-11-27-earnalism-cinematic-film-design.md` section 9.
No code in contracts/, core/, reader/, library/ or operations/ was changed; this note asks for those changes.

## What eav now writes

`python3 -m eav.cli bundle-audio` defaults to `--profile audiobook` (`--profile film` keeps the old bundle
byte for byte in shape). Each `timing.json` row `{"unit_id", "mp3", "segments"}` gains two keys; `segments`
is unchanged (paragraph precision, `anchor_id` = the live paragraph anchor, offsets 0..len(text)):

```json
{"unit_id": "...", "mp3": "unit-001.mp3", "segments": [ ...unchanged... ],
 "chapters":  [{"title": "প্রথম পরিচ্ছেদ", "start_ms": 5160}],
 "sentences": [{"anchor_id": "<paragraph anchor>", "sentence_index": 0, "start_ms": 5160, "end_ms": 5870}]}
```

- All times are integer ms from the start of that unit's MP3, in the same timeline as `segments`.
- `chapters`: one marker per heading paragraph recognised by `eav.retime._HEADING_LINE` (an ordinal then
  পরিচ্ছেদ, or পরিচ্ছেদ with a number), at that paragraph's measured start; `title` is the heading text
  without `#` and trailing ।/. . A unit with no heading, or with text before its first heading, also gets
  `{"title": <unit title>, "start_ms": 0}` first. Never empty.
- `sentences`: per paragraph (`anchor_id` as in `segments`), `sentence_index` counts sentences in the
  paragraph using `eav.text.sentences` (split after `.` `?` `!` `।`, whitespace collapsed; the paragraph text
  is never altered or stored). The first sentence starts at the segment's `start_ms`, the last ends at its
  `end_ms`; in between a sentence ends where the measured pause starts and the next begins where it ends
  (`start_ms < end_ms`, ordered, non-overlapping). Measured, never estimated: a paragraph whose pauses
  cannot show every sentence end gets no `sentences` rows and is listed in
  `provenance.units[unit_id].sentences_unmeasured` (it keeps paragraph-level timing).
- Both keys are additive and optional: a `film` profile bundle, and every bundle already built, has neither.
  Consumers must treat missing `chapters`/`sentences` as "paragraph precision only" and fall back to `segments`.
- `provenance.profile` is `"audiobook"` (absent for `film`), with `sentence_splitter`, `frame_units_sha256`
  (title, author, closing WAVs) and per unit `lufs`, `true_peak_dbtp`, `lra_lu`, `bed_under_voice_lu`,
  `voice_offset_ms`, `sentences_unmeasured`.
- `segments[*].start_ms/end_ms` now include the spoken opening on part 1 (title and author come first), so the
  first paragraph does not start at 0 ms.

## What root and backend must change before an audiobook-profile bundle can be attached (not done here)

1. `operations/management/commands/attach_audiovisual_audio.py` (`read_bundle`) requires
   `set(row) == {"unit_id", "mp3", "segments"}`: it refuses rows with `chapters`/`sentences`. Allow the two
   optional keys, validate `chapters` (non-empty, ints, strictly increasing `start_ms` inside the measured
   duration) and `sentences` (known `anchor_id` of the unit, `sentence_index` contiguous from 0 per anchor,
   inside that anchor's segment, ordered).
2. `library/production_handoff.py` `measure_mp3` accepts only `bit_rate in {48000, 96000}`. The audiobook master
   is mono 64 kbps (spec section 9), so 64000 must be admitted for the audio asset (and the "48 or 96 kbps" text
   in the command docstring and any contract/evidence wording changed). Until then the `film` profile is the
   only one the current stage command accepts.
3. Persist chapters and sentence timing and expose them through the timing map. Today `TimingSegment`
   (`contracts/openapi.yaml`, `components/schemas/TimingSegment`) is paragraph-only and `TimingMap.precision`
   already allows `"sentence"`: a sentence map would be `precision: "sentence"` with segments keyed by
   `anchor_id` plus `sentence_index` (root decides the exact schema; `TimingSegment` has
   `additionalProperties: false`, so a `sentence_index` field and a chapters list need a contract change).
   `contracts/api-contracts.md` and `contracts/payload-examples.json` should follow.
4. The sentence index is only meaningful against the same splitter. The reader/backend must split a paragraph
   with the rule above (or root fixes the rule in the contract and eav follows it) so highlighting lines up.
5. Evidence draft: `audio_sha256` and `timing_json_sha256` are still produced; `music.mix` is worded for the
   audiobook master. Clearance remains the owner's.

Questions to root: the bundle also needs `title.wav`, `author.wav` and `closing.wav` narrated in the book's
voice (eav `--frame-dir`); these are narration units outside the scene plan and are not yet produced by the
planner, so a producer supplies them per title.
