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
The model stays Indic Parler-TTS at that revision: another model needs the owner's approval
and a licence review.

## What changed on 24 November 2026, and why

The owner heard the narration as "mechanical and robotic, lacking natural human expressive
story-telling". Three causes, all from how we drove Parler (model card
`ai4bharat/indic-parler-tts`):

1. **We asked for flat delivery.** Both story presets say "slightly expressive intonation,
   in a relaxed, even manner ... calm". Parler obeys its description.
2. **Every sentence reset.** One generation per sentence, each with the same description,
   so every sentence started from a neutral contour.
3. **We ignored the controls Parler has.** Emotion words (Command, Anger, Narration,
   Conversation, Disgust, Fear, Happy, Neutral, News, Sad, Surprise; documented for Bengali,
   unverified for English until auditioned), the recommended speakers (Bengali Arjun,
   Aditi; English Thoma, Mary), "very clear audio", and punctuation, which carries prosody.

The fix is the **storyteller style** plus **storyteller presets chosen by audition**.

## Storyteller presets (candidates until the owner picks)

`references/storyteller-voices.json` (skill-local; the go-live roster is not edited):
Bengali `arjun::storyteller`, `aditi::storyteller`, `arnav::storyteller`; English
`thoma::storyteller`, `mary::storyteller`, `tisha::storyteller`. Each asks for an
expressive, captivating storyteller: highly expressive, animated intonation with natural
rises and falls, a varied pace that slows for tender or tense moments, warm and intimate,
very clear audio, close up, no background noise. Same `temperature: 0.91` as the story presets,
so an audition compares descriptions only.

Every entry is `"status": "CANDIDATE — owner audition required"`. `job narration --voice
<preset_key>` refuses any entry whose status is not exactly `OWNER_SELECTED`; production keeps
the story preset until the owner picks. Only the owner's selection changes a status.

## Audition: the required step before any voice change

This amends the old "never re-audition" rule (owner, 24 Nov 2026). A voice change is always:
audition → owner listens → owner selects → the entry is marked `OWNER_SELECTED`.

```
python3 -m eav.cli job narration --root <title root> --rates <rates.json> --audition audition.json
```

`audition.json` (passages ≤ 80 words each, supplied by the operator, e.g. from the book):

```json
{"passages": {"narration": "...", "dialogue": "...", "emotional": "..."},
 "candidates": ["arjun::storyteller", "aditi::storyteller"],
 "directions": {"emotional-001": {"emotion": "Sad", "clause": "slower, close to tears"}}}
```

`candidates` defaults to every storyteller preset of the title language; `directions` is
optional (keys are passage unit keys, `<passage>-NNN`). One Colab narration job renders the
three passages in every candidate (storyteller style) plus `control` (the current story preset,
rendered exactly as production does today). Files are `<variant>__<unit_key>.wav`, e.g.
`mary-storyteller__dialogue-001.wav`. It runs, exchanges (`exchange-stage` / `exchange-collect`)
and imports like any narration job, under target `audition`: it is never film or reel narration,
and film narration is still a separate job. Present the imported files to the owner by variant;
the owner's choice, not a waveform or ASR score, decides.

## The performance we want

Warm, intimate storyteller. Unhurried (about 115–130 wpm) but alive: the pitch rises and
falls with meaning, the pace slows for tender or tense moments and moves on in action. Quiet
wonder. Drops pitch and slows slightly for reveals. A brief held breath before a turn.
Dialogue coloured by small shifts of pace and intensity, never by character impersonation.

## How we get it (only controls Parler really has)

1. **Description.** The preset, plus at most one appended clause of ≤ 12 words
   (`--clause`). Example clause: "slightly slower, hushed, for the reveal". The CLI rejects
   longer clauses.
2. **Storyteller style** (`job narration --expressive`; opt-in, recorded in `job.json`
   `voice_style` and the record's job event; jobs without it behave exactly as before):
   - **Grouping.** Consecutive short sentences of one paragraph and one speaker turn are one
     voice unit (≤ 28 words, ≤ 18 s estimated), so Parler carries one contour across them.
     Never across paragraphs, headings, reel lines or a narration/quoted-speech turn; a
     sentence is never split. Unit texts joined by one space are exactly the book's text
     (tested); unit keys stay `<scene_id>-NNN`, and film timing, subtitles and Maison
     audio follow the job's own units.
   - **Direction.** Each unit's description is the preset, then
     `<Speaker> speaks in a <emotion> tone.`, then one clause. Default emotion: `conversation`
     for quoted speech, `narration` otherwise. A title may carry directions written from the
     context map (`--directions <root>/directions/film-01.json`):
     `{"<unit_key>": {"emotion": "Fear", "clause": "hushed, trembling, slower"}}`. Unknown unit
     keys, emotions outside the model's list, clauses over 12 words and any other field are
     refused. Get the keys first with `job narration --expressive --list-units` (builds
     nothing). Direct sparingly: the context, not a single word, decides.
   - **Pauses** (below).
3. **Pauses in the edit, once.** Colab writes dry per-unit WAVs with no added silence;
   `eav.film.narration_track` is the only place pauses are inserted, so measured unit ends
   are speech ends. Default style: 400 ms between sentences, 800 ms at a paragraph end,
   1200 ms after a heading. Storyteller style, within paragraphs: 400 ms between units,
   550 ms after `?`/`!`, 600 ms at a dialogue turn, 700 ms after an ellipsis or dash (the
   held breath), 800 ms at a paragraph end, 1500 ms at a scene end; the longest applicable
   wins. In a reel, 400 ms between lines in either style (Squint pacing). Silence is never
   added anywhere else, and a held breath is never written as spoken text.
4. **Context.** Read the whole work first and keep the context map from
   `earnalism-audiobook-go-live/references/narrative-performance.md`: who speaks, what
   turns, where the reveal lands, how it ends. A suspenseful word does not make a calm
   paragraph frightening.

## Owner decision, 24 November 2026: ElevenLabs narration

The owner approved ElevenLabs (Eleven v3, his Creator plan, whose paid tier carries the
commercial licence for generated audio) as the narration engine for these and future books,
after the free Parler storyteller audition fell short of a natural, dramatic storytelling voice.

- **Credits only, never money.** Use only the plan's included credits; at most 60,000 credits in a
  calendar month without asking again; no top-ups, no overage, no usage-based billing.
- **Words are the book's, exactly.** Eleven v3 audio tags (`[softly]`, `[sad]`, `[whispers]`,
  `[trembling voice]`, `[pause]` …) are inserted between the words as performance direction;
  no word is added, dropped, changed or reordered, and tags are stripped before any text check.
- **Voice by audition.** Library storyteller voices are auditioned on the same passages; the owner
  picks one per language. The pick is recorded here before narration.
- **Audio is fetched from `elevenlabsusercontent.com`** (allowed in this environment) and imported
  with its sha256 like every other output.

## Never

- Add, drop, repeat or reorder words. Stage directions are never spoken.
- Change voice without an audition and the owner's selection; clone or retrain voices;
  use a candidate preset for production narration.
- Claim a listening result from a waveform, ASR score or a successful run. Owner review
  of the first package (or of an audition) is the listening assessment; other dimensions stay
  `unassessed`.

## Dry first, then measure

Narration is generated dry, imported (hash-verified), frozen, and only then measured
(`film.narration_track`, ffprobe durations). Score and pictures follow measured timing;
they never move a word.
