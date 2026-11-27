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

**Built (Task 13): Eleven v4 passages, imported, checked and joined.** The v4 model id is not hard-coded:
the title keeps it in its voice settings, `<root>/voice.json` = `{"model_id": "<the Eleven v4 model id the
owner chose>"}`, and `import-take` accepts that exact id (and `eleven_v3`); any other model stops. With the
v4 id, `import-take` takes **per-passage** files instead of one take per scene:

```
python3 -m eav.cli split-passages film-01 --root <root> --out <scripts dir> [--cps 13]
# tag each <scene>-p<NN>.txt, generate one take per passage, download as <scene>-p<NN>.mp3
python3 -m eav.cli import-take film-01 --root <root> --scripts <scripts dir> --audio <takes dir> \
  --engine elevenlabs --model <model_id of voice.json> --voice-id <id> --voice-name "<name>" \
  --credits <credits used> [--cps 13] [--profile voicecheck-profile.json]
```

`split-passages` cuts each scene at sentence (`eav.text.sentences`) or paragraph ends into passages of about
15–30 s (never mid-sentence; a sentence over 30 s stays whole; a paragraph or heading boundary stays a blank
line; passages joined give the scene text back exactly) and refuses to overwrite a file. The length is
estimated at `--cps` characters per second: the default 13 is a **documented estimate** (about 120 words/min,
the plan's default rate, at ~6.5 characters per Bengali word), not a measurement, because no real v4 take is
on record yet. `import-take` imports every scene whose `<scene>-p01.txt` is present, or only `--scene ID`;
a scene wav placed by hand blocks only that scene (it is skipped, or refused with `--scene`; never
overwritten). Per passage it checks the tagged script (words exactly the book's in order; at most one audio
tag per sentence; no passage but the last ending mid-sentence; a passage opening on `[softly]` only when
that is the mood carried from the passage before; a passage after one that ended in a mood tag must open
on a mood tag, the carried one or a deliberate new one; `[pause]` tags set no mood), runs `retime` (pauses by
the script's punctuation), then `voicecheck` against the film's profile
(`film/film-NN/voice/passages/voicecheck-profile.json`, measured on the first run and reused on every redo,
or `--profile`; the join check compares each passage with the one before it). The expected duration of a
passage is its characters divided by **the run's own median measured rate** (characters per second of the
run's retimed passages), so only a passage out of pace with its run (truncated, runaway) misses `duration`;
a run of fewer than 3 passages has no such rate: it uses `--cps` and reports `duration` as a warning, not a
failure (a uniformly mis-paced scene is then not caught on length; the other gates still apply). **A scene
with a failed passage is not joined**, with the passages and failure codes listed (the other scenes of the call
still are): regenerate only those passages from the same tagged script, download over the old
`<passage id>.mp3` and rerun the same call. **At most 3 different takes of a passage**: after a third failed
take the tool stops asking for regeneration and holds the passage for the owner, who listens to it and its
`voicecheck.json` values and either rewrites its tagged script or has it joined with
`--accept <passage id>="<reason>"` (recorded in the passage manifest and the `passages_checked` event; an
accepted passage is joined but never counted as a pass). **Credits:** every run, passing or failing, records a
`passages_checked` event with its `--credits`, so on a redo give the credits of that regeneration only (the
account sums the events against the 60,000 monthly limit). When a scene passes it is joined to
`film/film-NN/voice/<scene>.wav` (the file `cue` reads; `film --shots` and `cue` need no narration job): the
seam between passages is the take's own room tone (`eav.retime.room_tone`, −62 to −68 dBFS) sized by the
punctuation that ends the passage (`।` or `?` 0.8–1.0 s, `!` 1.4–1.6 s, before a heading 2.5–3.0 s, each
varied ±15% by a draw seeded with the passage id, as `retime` does), joined by 40 ms equal-power crossfades
(the binding 30–50 ms), the take edges beside it cut back to 80 ms of speech with room tone under them, so no
digital zero is left. The scene opens on room tone with its first word 0.85 s in (R9's 0.5–1 s breath) and
ends with 2 s of room tone after its last word (the room for R4's J/L-cut); the manifest records each
passage's offset on the scene, which `scene-timing` uses to place the measured clauses for `plan-shots`. Beside each wav
`<scene>.passages.json` records the model, the sha256 of `voice.json`, voice, credits and the sha256 of every
script, take and retimed passage; the record gets `passages_checked` and `passages_joined` events and
`scene_voice` and `passage_manifest` artifacts. `voice.json` may not name `eleven_v3` (that model is the
one-take route and never needs the file), and a malformed `voice.json` does not block that route. Passages
serve film scenes, not reels (a reel stays one `eleven_v3` take). **One-take-per-scene `eleven_v3` import is
unchanged** (the 24 Nov route below). Not certified: the judgement that a passage sounds natural stays
with `voicecheck` and the owner's ear.

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
| pitch spread | 10th–90th percentile at least 3.0 semitones (`pitch_spread`; uncalibrated: warning) |
| monotone | no more than 20% of 2 s windows with spread under 1.5 semitones (`monotone`; uncalibrated: warning) |
| breath | no stretch over 9 s without a pause of 0.15 s or more (`no_breath`; uncalibrated: warning) |
| tail | last 50 ms no louder than −50 dBFS (`tail`; uncalibrated: warning) |
| brightness | within ±2 dB of the book median (`brightness`) |
| spectral jumps | within 1.5× the profile, floored at 0.1 per speech second (`jumps`) |
| clicks | no more than 0.2 per second (`clicks`; uncalibrated: warning) |
| digital zero | no run over 50 ms (`digital_zero`) |
| join | with `--prev-tail`: within ±1.5 LU and ±1.5 semitones (`join`) |
| true peak | below −0.1 dBFS (`true_peak`) |

**Uncalibrated absolute limits are warnings (owner ruling, 27 Nov final review).** pitch spread, monotone, breath,
tail and clicks are fixed numbers that no accepted v4 take has calibrated: the owner-endorsed scene 14 v4 take
runs 9.012 s without a pause in a clause the book prints without one. Until the profile carries a calibrated
limit for a code (`"calibrated_limits": {"no_breath": 9.5, ...}` in `voicecheck-profile.json`, written only after
the owner has listened to accepted v4 takes), exceeding it is a WARNING printed with the measured value and the
limit (`warnings` and `warning_values` in the result), never a redo and never a credit-spending regeneration,
exactly like the words check's provisional ceiling. The profile-relative checks, duration, join, digital zero and
true peak stay redos.

One narration feeds both the film and the audiobook, so the stricter audiobook limits (joins 1.5 LU
and ±1.5 semitones, 30–50 ms crossfades) apply to both. Measurement is not listening: a PASS means
"not flagged", and the owner's review is the listening assessment (see Never).

**Word check (built, Task 14; failure code `words`).** A Whisper (MIT) transcript of each take is compared with
the book's untagged source text, to catch dropped, added or misread words that tags and punctuation hide.
`import-take` still refuses a script whose words differ from the book; this checks the *audio* against it.

- *Transcript.* Run `software/eav/templates/words_cell.py.txt` in a free Colab runtime over the downloaded takes
  (not the retimed ones). It is a stand-alone cell, not a job kind (no ledger units, no forecast), and reads
  the model card's licence at run time (`mit` or `apache-2.0` only). It writes `transcripts.json`: per take stem,
  the sha256 of the take file and the text, plus the model repo, revision and licence.
- *Compare.* One take per scene: `eav voicecheck <take...> --expected S --transcripts transcripts.json
  --sources <folder of <take-stem>.txt, the untagged book text>`. Passages (`import-take --transcripts
  transcripts.json`, keyed by passage id; the source is the untagged passage text). Both write the result
  into `<stem>.voicecheck.json` (`metrics.words`: cer, threshold, provisional, model).
- *Measure.* Character error rate (Levenshtein distance / source length) after normalising both texts: Unicode
  NFC, lower case, Bengali digits to ASCII, ZWNJ/ZWJ and all punctuation (`।`, `॥`, quotes, dashes) removed,
  whitespace collapsed.
- *Threshold.* `words` fails (REDO) when the CER exceeds the median CER of the book's accepted takes plus
  0.05 (`voicecheck-profile.json`: `words_cer_median`, `words_cer_n`, `words_cers` by take). Accepted means a
  take that passed every check with its words checked and within the limit: failing, warned and not-run takes
  never enter the median, and a redo's newly accepted take replaces its own entry. Until three accepted takes
  carry a transcript, the absolute ceiling 0.15 is uncalibrated, so exceeding it is only a WARNING (`warnings:
  ["words"]`, `provisional`, printed with the CER): listen to that take, it is not a redo. Both numbers are
  estimates; re-tune after the first real takes.
- *Not run is not a pass.* A take with no transcript, no source text, or a transcript made for different file
  bytes is recorded as `metrics.words.run: false` and `"not_run": ["words"]`, `pass` is `null` (never `true`),
  and the CLI prints that the word check was not run. It is not a REDO either. Do not claim a word check for a
  take that has no `words` result with `run: true`.
- *Which file.* The sha256 is of the file bytes the cell read. Transcribe exactly the files you later pass to
  `voicecheck` (or put in `import-take --audio`): the ElevenLabs mp3 as downloaded, with no conversion or
  re-export. A transcript of other bytes is not applied and the CLI warns "made for different file bytes". The
  standalone `--sources` text may carry audio tags: they are stripped before the CER.
- *Limit.* Whisper's Bengali is imperfect: a `words` failure is a prompt to listen to that take, a clean
  result does not replace the owner's listening review.

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
passage import is built (Task 13, see "Current standard"); the route above stays as written for
`eleven_v3`, one take per scene. In either case a take's own pauses are re-set by `retime`.

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
