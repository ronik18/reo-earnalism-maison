# The Earnalism Voice

One recognisable narrator per language, in every film and reel: one chosen voice per title, driven by a
direction method, never a different voice per scene.

## Current standard (owner, 26 and 27 November 2026): Eleven v4, passages, redo only failures

The owner rated the first বিচারক film's narration 6/10, "mechanical/robotic texture in specific
areas ... make it fully natural human, dramatically expressive and story-telling". The narration
standard now is:

1. **Model: Eleven v4** (owner choice, 26 Nov), the title's owner-picked voice (বিচারক: "Subhajit –
   Grounded Bengali Storyteller", `j5PhP1QJv2DvlhRv3mEv`; The Selfish Giant: "Sakshi – Warm Bedtime
   Storyteller", `XdbTvfQSkW1sgZYKdZdF`). Credits only, within the 24 Nov limits below.
2. **One take per passage of 15–30 s**, split at sentence or paragraph ends, never mid-sentence, a
   tagged script and take per passage. At most **one audio tag per sentence**; carry the previous
   passage's mood tag across the join; **never open a passage on a bare `[softly]`** (start on the
   words, or on a tag that sets a mood the whole passage keeps). Tags describe delivery only, never
   action or sound.

**Not yet built (planned: Task 13): passage import and Eleven v4 import** (passage import and v4 import are both missing). Today `import-take`
accepts only `--engine elevenlabs --model eleven_v3` (anything else stops) and requires exactly one
tagged script `<scene_id>.txt` and one take per scene of the target in one call; no command joins
passages into a scene wav. **Working route today:** (a) one `eleven_v3` take per scene through
`import-take`, as in the 24 Nov route below, then `retime` and `voicecheck` on it; or (b) as the
scene-14 pilot does, a pre-retimed scene wav placed by hand at `film/film-NN/voice/<scene>.wav`,
which `cue` reads. Do not pass a v4 model id to `import-take`, and never claim v4 or passages were
imported.

3. **One take, redo only the failures** (owner choice, 26 Nov; best-of-three costs 45k credits per film
   and was rejected). Budget about 15,000–20,000 credits per 20-minute film (v4 costs about one
   credit per character: a 47 s Bengali scene take is about 656). A failed passage is regenerated from
   the same tagged script (or a corrected one) as a new generation within the monthly 60,000 credits
   (a plan resets on the 23rd), never "retried" blindly.
4. **Pauses are re-timed by punctuation (`retime`)** and filled with real room tone.
5. **The redo gate (`voicecheck`)** decides which takes are redone; the owner's ear decides the film.

### `retime`: pauses by punctuation, room tone, no digital zero

```
python3 -m eav.cli retime <take.wav> <out.wav> --text <script.txt> [--seed N] [--cuts t1,t2,...]
```

Finds the take's own pauses (silencedetect), maps them in order to the punctuation of the script text
(audio tags are ignored; a run of marks counts once, as its strongest) and sets each to a seeded
target: comma `,` `;` `—` 0.40–0.55 s; `।` or `?` 0.8–1.0 s; an emotional `!` before a turn
1.4–1.6 s; scene break 2.0 s; a পরিচ্ছেদ heading 2.5–3.0 s before and 1.5 s after. Each length is
varied ±15%. Each pause keeps 40 ms of the original at both sides, the middle is the take's **own room
tone** (level-matched −62 to −68 dBFS; a synthetic −65 dBFS floor if the take has none), joins are
40 ms equal-power crossfades. **Digital zero is never allowed.** `--cuts` maps old-timeline cut
times (e.g. unit boundaries) into the new timeline. The measured, re-timed timing then feeds
`plan-shots` and captions.

### `voicecheck`: the automatic redo gate

```
python3 -m eav.cli voicecheck take1.wav take2.wav ... --expected 47.2,52.0 [--profile voicecheck-profile.json] [--prev-tail prev.wav] [--out DIR]
```

Without `--profile` it measures the book's running medians from the given takes and **saves
`voicecheck-profile.json`**; **every redo run must pass `--profile`** (otherwise the redone takes
would redefine "normal"). It writes `<take-stem>.voicecheck.json` beside each take (or in `--out`)
and prints PASS or `REDO <codes>` per take (the saved profile is measured from all the takes given, failing takes included, and same-named takes from different folders share one result file under `--out`); **it exits 1 if any take fails**, and the `Next:` line says
to regenerate only those and rerun with the profile. Checks (codes in brackets):

| Check | Limit |
|---|---|
| duration | within ±12% of expected (`duration`) |
| median pitch | within ±1.5 semitones of the book median (`pitch_median`) |
| pitch spread | 10th–90th percentile at least 3.0 semitones (`pitch_spread`) |
| monotone | no more than 20% of 2 s windows with spread under 1.5 semitones (`monotone`) |
| breath | no stretch over 9 s without a pause of 0.15 s or more (`no_breath`) |
| tail | last 50 ms no louder than −50 dBFS (`tail`) |
| brightness | within ±2 dB of the book median (`brightness`) |
| spectral jumps | within 1.5× the profile, floored at 0.1 per speech second (`jumps`) |
| clicks | no more than 0.2 per second (`clicks`) |
| digital zero | no run over 50 ms (`digital_zero`) |
| join | with `--prev-tail`: within ±1.5 LU and ±1.5 semitones (`join`) |
| true peak | below −0.1 dBFS (`true_peak`) |

One narration feeds both the film and the audiobook, so the stricter audiobook limits (joins 1.5 LU
and ±1.5 semitones, 30–50 ms crossfades) apply to both. Measurement is not listening: a PASS means
"not flagged", and the owner's review is the listening assessment (see Never).

**Word check (not yet built; planned: Task 14).** The spec adds a Whisper (MIT) character-error check, run in Colab
against the source and read relative to the accepted takes, to catch dropped or changed words that
tags and punctuation hide. No `eav` command runs it yet: until one exists, `import-take` (which
refuses a script whose words differ from the book once tags are removed) is the only word gate, and
the reviewer listens for dropped words. Do not claim a Whisper check was run; the Whisper check is not yet built (Task 14).

## Parler route (legacy; kept for audition and Parler-only titles)

Everything from here to the owner decision is the Indic Parler-TTS route of 24 Nov. It is not the
production narration of a cinematic film.

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
- **Owner picks (24 Nov 2026).** বিচারক: "Subhajit – Grounded Bengali Storyteller"
  (`j5PhP1QJv2DvlhRv3mEv`). The Selfish Giant: "Sakshi – Warm Bedtime Storyteller"
  (`XdbTvfQSkW1sgZYKdZdF`). Another title or voice needs a new audition and pick.

### The ElevenLabs route, end to end

1. **Units first.** `job narration --root <root> --rates <rates.json> --film N --list-units`
   (builds nothing) prints the plan's sentence units; a scene's text is its units joined by
   one space. A reel's text is its script lines (`reels/reel-N/script.json`).
2. **One tagged script per scene**, `<scene_id>.txt` (a reel: one script `reel-N.txt` for the
   whole reel). It is the scene's exact text with Eleven v3 audio tags between the words.
   Direction rules: a tag describes *delivery* (`[softly]`, `[sad]`, `[warmly]`,
   `[trembling voice]`, `[whispers]`, `[pause]`, `[long pause]`), never action, sound effects
   or stage directions (`[the giant walks in]` is forbidden); tag only where the delivery
   changes, from the context map, not on every sentence; tags never replace punctuation and
   never touch the words. Put a tag between spaces or against punctuation
   (`garden [pause].`, `“[whispers] Who`), never inside a word. Square brackets that are part
   of the book text stay exactly where they are.
3. **Generate one take per scene** with the owner-picked voice, `model eleven_v3`,
   generations 1 (never a second generation as a "retry": each one spends credits), the whole
   tagged script in one call. Check the month stays within 60,000 credits first.
4. **Download** each take as `<scene_id>.mp3` (a reel: `reel-N.mp3`) into one folder, and
   note the credits the generations used (account usage before and after).
5. **Import:**

   ```
   python3 -m eav.cli import-take film-01 --root <root> --scripts <scripts dir> \
     --audio <takes dir> --engine elevenlabs --model eleven_v3 \
     --voice-id <voice id> --voice-name "<voice name>" --credits <credits used>
   ```

   (`reel-N` instead of `film-NN` for a reel.) It refuses a missing script or take, a script
   whose words differ from the book in any character once tags are removed, an unknown
   target, a target whose Colab narration job is still open (supersede or close it first) and a
   reel whose shots are already planned. It slices each take at its own silences into
   `narration/<job_id>/<unit_key>.wav` (`eav.take.slice_take`: for each join the silence
   nearest the character-proportional time, monotonic, one cut per silence, at its midpoint;
   joined, the WAVs are the decoded take sample for sample). A join with no usable silence is
   cut at the quietest 20 ms within ±400 ms and listed as **estimated** (listen there first).
   It keeps the takes and scripts in `jobs/<job_id>/` with `take-manifest.json` (sha256 of
   every WAV, take and script) and files a narration job: engine, model, voice, voice id,
   credits, estimated joins, imported, 0 Colab CU on the ledger.
6. **Then as usual:** `film --film N ...` or `reel N --plan-shots` picks it as the latest
   narration of the target. Its voice style is `continuous`: the takes carry their own
   pauses, so no pause is added inside a scene or between reel lines, and only 1200 ms
   between two scenes of a film. Timing and subtitles stay per sentence.

A take that sounds wrong is regenerated from the same tagged script and imported again as a
new job (the newer import wins); never edit or trim a take by hand.

**27 Nov 2026 amendment (cinematic standard).** The decision above stays; the owner's standard is
now Eleven v4, passages of 15–30 s, and `voicecheck` with only failures regenerated. The v4 and
passage import is not yet built (planned: Task 13, see "Current standard"): until it lands the route
above works as written with `eleven_v3`, one take per scene. In either case a take's own pauses are
re-set by `retime`.

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
