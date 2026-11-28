# The Earnalism Voice

One recognisable narrator per language, in every film and reel. It is a **fixed preset
plus a direction method**, not a new voice.

## Identity

| Language | Profile | Preset (byte-for-byte from the roster) |
|---|---|---|
| English stories | `en_tisha` | `en_tisha::story` |
| Bengali stories | `bn_arnav` | `bn_arnav::story` |

The roster is `skills/earnalism-audiobook-go-live/references/final-voice-roster.json`
(Indic Parler-TTS `ai4bharat/indic-parler-tts` at revision
`7b527af5ee8ed1f9a28d80b19703ed9bb8ba10ca`). `eav.cli plan` copies the preset
description into `plan.json`; `job narration` sends it unchanged, together with the preset's pinned generation
settings (e.g. `temperature: 0.91` for both story presets), which reach Parler's
`generate` call and are recorded in the job's build manifest and output model info. Explicit owner routes
(e.g. `en_raghav` for an English male narrator) still apply; ask, never substitute.

## The performance we want

Warm, intimate storyteller. Unhurried (about 115–130 wpm). Quiet wonder. Drops pitch and
slows slightly for reveals. A brief held breath before a turn. Dialogue coloured by small
shifts of pace and intensity, never by character impersonation.

## How we get it (only controls Parler really has)

1. **Description.** The preset, plus at most one appended clause of ≤ 12 words
   (`--clause`), and only where the preset's qualification allows it. Example clause:
   "slightly slower, hushed, for the reveal". The CLI rejects longer clauses.
2. **Sentence grouping.** One voice unit per sentence (`eav.voice.voice_units`); the
   scene plan keeps paragraphs and turns together. Indic Parler-TTS stops every
   `generate()` at about 30 s (measured 30.2 s; the story voice speaks about 11–12
   Bengali characters a second), so no unit is longer than `MAX_UNIT_CHARS = 200`
   characters (about 18 s), in every language. A longer sentence becomes several
   ordinary units. It is split only at clause punctuation (`;` `:` `,` `—` `–`, a danda
   or double danda inside it), after the whole punctuation run (e.g. `;—`), whether or
   not a space follows, at the point closest to the middle that leaves both parts within
   the limit, else the one closest to the middle, recursing on each part. A space is used
   only inside a stretch with no clause mark that is itself longer than the limit (again
   closest to the middle). Never inside a word or a number; every part keeps its exact
   characters, and the parts with their original separators (a space, or nothing after
   unspaced punctuation) rebuild the sentence byte for byte. Unit keys stay
   `<scene_id>-NNN` in order.
3. **Pauses in the edit, once.** Colab writes dry per-unit WAVs with no added silence;
   `eav.film.narration_track` is the only place pauses are inserted, so measured unit ends
   are speech ends. 150 ms after each part of a split sentence (`CLAUSE_PAUSE_MS`; its
   last part keeps the sentence's own pause), 400 ms between sentences, 800 ms at a
   paragraph end, 1200 ms after a heading; in a reel, 400 ms between lines (Squint
   pacing). Silence is never added anywhere else, and a held breath is never written as
   spoken text.
4. **Context.** Read the whole work first and keep the context map from
   `earnalism-audiobook-go-live/references/narrative-performance.md`: who speaks, what
   turns, where the reveal lands, how it ends. A suspenseful word does not make a calm
   paragraph frightening.

## Never

- Add, drop, repeat or reorder words. Stage directions are never spoken.
- Re-audition, clone or retrain voices; reopen speaker search.
- Claim a listening result from a waveform, ASR score or a successful run. Owner review
  of the first package is the title's listening assessment; other dimensions stay
  `unassessed`.

## Dry first, then measure

Narration is generated dry, imported (hash-verified), frozen, and only then measured
(`film.narration_track`, ffprobe durations). Score and pictures follow measured timing;
they never move a word.

## Cut-off narration (suspect_truncated)

A unit WAV is `suspect_truncated` when it lasts at least 29.0 s (`eav.qc.TRUNCATION_CAP_S`)
or its characters per second exceed 1.6 x the job's median (`eav.qc.CPS_RATIO`): Parler
stopped and text was probably lost. The ratio test (and the median) leaves out units under 40
characters (`eav.qc.MIN_RATIO_CHARS`: their rate is mostly breath); a unit with no audio is always
suspect. `import` lists them (advisory: the import stands), `qc` lists them in
`qc/report.json`, and `film`, `bundle-audio` and the reel assembly (`reel N`) refuse to build
from narration holding one until the owner has listened and names it with
`--accept-qc <unit_key,...>` (recorded with the film / bundle / reel). Only keys on the current
suspect list are accepted, so an acceptance never covers a later regeneration. Otherwise
voice just those units again, never accept unheard:
`job narration --root <dir> --rates <rates.json> --redo-units <job_id>:<unit_key>[,<unit_key>...]`
(`<job_id>` is the imported film narration job, or the chunk that holds the units; the refusal
prints the exact command). It builds `<job_id>-u<k>` with only those units and the source job's
own text, voice description, generation settings, batch and model, forecast, cap-checked and
reserved like any job (Colab, or `modal-request <id> --colab-units 0`). Its `import` measures each
new take against the source job's median: a take that passes supplies that unit to film,
bundle-audio and preview in place of the old one (record event `narration/unit_replaced`; the
source job stays the current narration, the old take stays on disk, and films or bundles built
before are no longer current); a take still suspect is recorded (`narration/unit_redo_suspect`)
and the unit keeps its take and its flag. `status` lists both. `retire <redo job>` reverts the
unit to the take used before it.
