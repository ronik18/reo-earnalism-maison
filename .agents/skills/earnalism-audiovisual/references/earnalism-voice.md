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
   scene plan keeps paragraphs and turns together.
3. **Pauses in the edit, once.** Colab writes dry per-unit WAVs with no added silence;
   `eav.film.narration_track` is the only place pauses are inserted, so measured unit ends
   are speech ends. 400 ms between sentences, 800 ms at a paragraph end,
   1200 ms after a heading; in a reel, 400 ms between lines (Squint pacing). Silence is
   never added anywhere else, and a held breath is never written as spoken text.
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
