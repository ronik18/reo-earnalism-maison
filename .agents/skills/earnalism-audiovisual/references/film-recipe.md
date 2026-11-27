# Film recipe: the cinematic audiobook film

Landscape 1920×1080 at **24 fps** for Maison review and YouTube. The full text, unchanged, read in the
Earnalism Voice over a hand-made animated short of the story: one picture per phrase group, a camera
that always moves, real animation only where the text names an action, a cue written for each scene
and sound under every picture. It never claims character acting: it is illustrated cinema.

Authority: `docs/superpowers/specs/2026-11-27-earnalism-cinematic-film-design.md` (approved 27 Nov
2026; it wins over `2026-11-23-earnalism-audiovisual-design.md` for the film, the narration and the
score). The owner rated the first বিচারক film 6/10: too static, narration still mechanical. This
recipe is the standard that fixes both. The spec says what; this page says which command does it.

**Stage order for a film (per scene, as the CLI's `Next:` line walks it):** voice (v4 passages, each
retimed and `voicecheck`ed inside `import-take`) → `scene-timing` → `plan-shots` (approved) → stills +
gates → `pick` → `film_clips` (the Wan shots and the glide stills' depth maps) → the scene's own `job music`
→ `cue` → then `film --shots` → `qc` → owner review. The paper edit needs the measured narration, so the
voice comes first.

## 1. Plan (`plan`)

- Scenes of 30–90 s at natural boundaries (paragraph ends; a heading opens a scene). A paragraph
  longer than 90 s splits at sentence boundaries; a single sentence longer than 90 s stays one scene
  and is flagged `over_90s_sentence`.
- Narration over about 40 minutes: a chapter-by-chapter **series**, one film per unit, sharing one
  world bible, voice and score palette.
- Read the flags `plan` prints. A flagged scene is reviewed, not silently re-split.
- The old "one keyframe per 8–15 s" is gone: the shot plan decides the picture count (R2, below).

## 2. World bible (before any still)

Write it once per title (`<root>/specs/world-bible.json`) and reuse it in every prompt:

- **Period and place**: era, region, architecture, clothing, objects that must be right.
- **Palette and light**: 3–5 colours, one light family.
- **Lens and look**: the house style ([visual-style.md](visual-style.md)); the job builder appends it
  to every stills prompt, so never write a second style.
- **Character sheets** for every recurring person, parents included: one fixed line (age, face,
  hair, clothing, one distinguishing detail such as eye colour, mole, jewellery, sari border),
  repeated word for word in every prompt. Named minors (Hem, 14) appear only in dignified close-ups;
  "daughters" in general are drawn as grown young women unless the text requires a child.
- **Anchor stills** per person, generated first and reviewed; the character-lock gate compares
  against them (R6).
- **Review list** (checked on imported stills, never written into a prompt: FLUX.1-schnell draws
  what a negative names): text, letters, logos, watermarks, extra fingers, modern objects.

## 3. The paper edit: `plan-shots` (R11, before anything is generated)

Each scene's **two-column AV script** (time | audio | visual), shot list and compute estimate is
approved before any stills, clips or cues are built. Claude and an independent reviewer approve each
scene; the owner approves the reference scene and each finished film (owner decision 3, 27 Nov).

1. Narration for the scene is imported and re-timed (section 5). Then `scene-timing --film N --scene <id>`
   measures it: each retimed passage's pauses are mapped in order to its punctuation (`retime.clauses`), placed
   on the scene by the join's recorded offsets, and written to `film/film-NN/shots/<scene>.timing.json`
   (`timing` `[{start, end, text}]`, `length_s`, `lead_in_s`, `tail_s`). A passage whose pause count does
   not match its punctuation stops with both counts (tune `--min-pause`/`--threshold-db`, or time it by ear
   into the input's `timing`); nothing is guessed.
2. Write the planner input `film/film-NN/shots/<scene>.input.json`: `spine` (one sentence),
   `fidelity` (the reviewer's R7 note), `motifs` (R8), `shots` (`beats: [first, last]`, `subject`, `framing`,
   `motion` `wan|glide|static`, `layer` `present|memory|imagined`, `transition_in` `cut|dissolve|match`,
   `bible_refs`, `camera` for glides, `wan_res` `1280x704|896x512` for Wan, `actions` for a Wan shot over 6 s,
   `sound`, `plants`) and `peak {shot, at}`. Without its own `timing` the input uses the `scene-timing` file
   (its `length_s` too: the last shot runs into the tail, captions end with the words), and the approval
   records that file's sha256 as well. A glide's `camera` may carry `zoom0`, `pan_y`, `near_gain`, `flat`,
   `sweep`, `drain`; the plan passes them through, type-checked.
3. `python3 -m eav.cli plan-shots --root R --film N --scene <id> [--bible world-bible.json]` writes
   `<scene>.json` and the AV script, prints rule codes, and exits 1 while a hard rule (R1–R3) fails.
4. Approve: `plan-shots … --approve --by Claude --reviewer <name>`. The reviewer must be a different
   person; the approval records the **sha256 of the input file**, so editing the input afterwards
   voids it. A job or `cue` built for a scene whose plan is not approved is refused.

Cut points are punctuation boundaries, plus measured breaths of at least 0.15 s inside long clauses.
Cuts fall in the middle of the pause between beats, about 0.3 s before the key noun or verb, never
mid-word. Coverage per scene: an establishing wide, a close-up of whoever perceives or acts, at least
one insert of a concrete noun the text names, imagined/remembered/future material bracketed by the
perceiver's face, a reaction on emotional verbs. Layers of time (present, memory, imagined) each get
a grade; dissolves only between layers; hard cuts or match cuts inside a layer; the last shot of a
scene matches the first light of the next.

## 4. The rules, R1–R11 (the owner's 27 Nov re-review): what the code enforces and what it does not

The middle column is the spec's standard. The right column names only the code that enforces it; anything
marked **reviewer only (not enforced)** is checked by Claude, the independent reviewer and the owner, and no
command claims it.

| Rule | Standard | Enforced by (and what is not) |
|---|---|---|
| **R1** New information | No stretch longer than 6 s without a new subject, action or composition. A camera glide alone adds none | `plan-shots`: a non-Wan shot over 6 s, and a Wan shot over 6 s with fewer `actions` than one per 6 s (each a continuation's own action); `qc new_info` (frame similarity on the film) |
| **R2** Shot density | At least one shot per 6 s of narration (shots = max(ceil(s/6), beats)); 4–8 s per shot, up to 12 s only for a performed action | `plan-shots`: shot count ceil(s/6), non-Wan over 8 s, any shot over 12 s. **Not enforced:** the 4 s minimum and the `beats` term (reviewer only) |
| **R3** Peak | One marked peak per scene at 70–85% of the way through, a planted preceding shot that motivates it, at least 4 s on screen, a mark in the sound (silence or a synced effect) | `plan-shots` (position, length, plant); `cue` silences the music there and `qc peak_silence` checks it |
| **R4** Sound matches picture | Every visible sound source is heard; day/night ambience matches; each scene ends with a J- or L-cut into the next | `qc sound_on_picture` (every sfx a shot lists has a placed entry over that shot); the join leaves a 2 s room-tone tail. **Not enforced:** day/night match and the J/L-cut itself (reviewer only) |
| **R5** Captions | On by default, muxed as a track (burned-in on request); ≤ 2 lines, ≤ 42 characters per line, 1–7 s per cue, ≤ 15 characters per second for Bengali | `film --shots` writes them within the limits; `qc captions` re-checks the written file |
| **R6** Character lock | Every on-screen person has a bible entry and an anchor still; automatic check of eye colour/count, mole, jewellery, sari border | `plan-shots` (bible refs exist); the still gate checks eye count, hands, anachronisms and DINOv2 similarity to the anchor. **Not enforced:** eye colour, mole, jewellery, sari border (reviewer only, at full size) |
| **R7** Fidelity | No frame contradicts the current or neighbouring scene's text (a "shut carriage" has no open window) | reviewer only: the `fidelity` note, `R7?` flag when absent |
| **R8** Motifs | Each scene reuses at least one earlier motif, changed (the empty bed, the birdcage, the slats) | reviewer only: `motifs`, `R8?` flag when absent |
| **R9** Opener, closer, disclosure | 0.5–1 s of breath before the first word; a title card; closing credits naming author, narration voice and "Illustrations and narration are AI-generated / ছবি ও কণ্ঠ এআই-নির্মিত" before the logo lockup | `import-take` joins each scene with a 0.85 s lead-in; `scene-timing` measures and warns outside 0.5–1 s; `film --shots --title --author --narrator` makes the cards |
| **R10** Audio and safety | Master −16 LUFS ±1, true peak ≤ −1.5 dBTP; ≤ 3 flashes a second; luminance jumps over 25% only on a deliberate cut | `film --shots` and `qc` (loudness, true peak, flashes against the planned cuts) |
| **R11** Paper edit first | Each scene's AV script, shot list and compute budget approved with a stopwatch pass before generation | `plan-shots --approve`; jobs declaring `"scene"`, `cue` and `film --shots` refuse unapproved scenes |

Layer grades (present, memory and imagined each with its own grade) are **not built**: nothing grades by
layer and Wan shots are not graded; the reviewer checks the light. The `?`-suffixed codes (`R7?`, `R8?`) are
reviewer flags, never refusals. Every enforced rule is a refusal: do not rewrite the plan's numbers to pass,
change the shot.

**No holds.** A picture that contradicts its words, including a still borrowed from a neighbouring
shot, is a failure. A failed still is regenerated or the shot re-planned, never filled with a
neighbour. `qc` (`hold_hashes`) flags a scene that reuses one still file within the scene with no animated beat between (it does not catch borrowing across scenes). (The CLI's `hold` command is the old pre-cinematic stopgap that shows a neighbouring still;
never use it on a cinematic film.)

## 5. Voice first (details: [earnalism-voice.md](earnalism-voice.md))

The standard is Eleven v4, one take per **passage** of 15–30 s: `split-passages film-NN` writes the
passages, then `import-take` (model id from the title's `voice.json`, `eleven_v4`) retimes each passage
(punctuation pauses matched by position, with real room tone; `--no-retime` keeps an already-retimed,
owner-endorsed take as it is, on record), runs `voicecheck` on it (a scene with a failed passage is listed for redo and not
joined; only the failures are redone, at most 3 different takes of a passage, then the tool holds it for the
owner; `--accept PID=reason` joins it on a recorded reason), and joins the scene over room tone with 40 ms
crossfades, a 0.85 s lead-in before the first word (R9) and a 2 s room-tone tail (R4). The uncalibrated
absolute voicecheck limits (no_breath, pitch spread, monotone, tail, clicks) warn with the measured value until
calibrated on accepted v4 takes; they never ask for a credit-spending redo. The voice goes to
`film/film-NN/voice/<scene>.wav`, which `scene-timing` and `cue` read. Still available: one `eleven_v3` take per scene via `import-take`
(then `retime`, `voicecheck`), or a pre-retimed scene wav placed there by hand (`scene-timing` times it as one
passage).

`scene-timing` matches each clause boundary to its pause **by position** (not by count): an unpunctuated
breath stays inside its clause (listed as `breaths` in `<scene>.timing.json`), and a boundary with no pause near
its words, or one whose pause lies far from them, stops with the clause named; nothing is guessed.

## 6. Stills and their gates (`job stills --film N --spec stills.json`)

```json
{"scene": "f01s014",
 "items": [{"key": "f01s014-3", "prompt": "<character lines first>. <what the text shows at this beat>. <period, palette, light>",
            "seed": 101, "width": 1344, "height": 768, "candidates": 3}]}
```

- **Composition-first prompts, character lines first.** The builder prefixes the house style, and
  FLUX.1-schnell's T5 encoder cuts at 256 tokens: whatever is last is silently dropped (stills-pilot5
  lost the veil, sari and age that way). `job stills` refuses an item whose house-style-first prompt
  is estimated over **180 tokens**; keep an item prompt to about 85–90 words. Prompts are positive-only
  (the builder refuses `no`, `not`, `without`, …).
- Three candidates per shot (`"candidates": 3`, up to 4): `<key>--c1..c3.png`; keys are
  `<scene_id>-<k>`. A spec carrying a top-level `"scene"` is shot-plan-driven and is refused until that
  scene's plan is approved (R11); a spec without it builds as a pilot or legacy round, so **every
  new-film job declares `"scene"`**.
- **Gates run in Colab next to the stills** (Apache-2.0 models, licence re-read from each Hub card before
  any download, declared `apache-2.0` for MediaPipe, which has no Hub card; a card that cannot be read means the model is not loaded and its checks become
  `needs_review`): MediaPipe Face/Hand Landmarker (eye count and both eyes visible; hand count,
  detached hands), OWLv2 open-vocabulary detection with eight labels (the six anachronism labels plus
  utility pole and modern high-rise building; gas cylinders, AC boxes, cables, modern glasses/belts,
  spotlights, letterbox bars), and DINOv2-small similarity of the person-box crop against the anchor
  still. CLIP is **not** used (its card puts any deployed use out of scope). Each candidate gets a
  `gate.json` and a contact sheet; an unclear result is `needs_review`, never a pass.
- **The film uses only picks.** For every glide and static shot `film --shots` takes the operator's recorded
  pick of a stills (or retouch, touchup, edit) job bound to that scene (`"scene"` in its spec), linked as
  `<scene>-<n>`. A shot with no pick stops the film; nothing falls back to an older still with the same key.
- `pick` refuses a candidate whose gate is a **certain fail**; `--override-fail KEY=reason` records a
  deliberate exception. `needs_review` is **advisory** (warned and recorded, not blocking) until
  `production/audiovisual/<title>/gate-calibration.json` exists (from approved stills); after that
  `--override KEY=reason` is required. Single stills use `picks/gate-overrides.json`. Gate seconds
  (`gate_s`, ESTIMATE: 300 s + 6 s per still) are part of the stills forecast; the gate is skipped
  (keys listed ungated) when the job runs short of time, so a paid run is never lost to it.
- After import look at every candidate at full size: anatomy, identity drift, stray text,
  continuity. Fixes: a different candidate, a crop or touch-up/retouch/edit; regenerate only when
  those fail.

## 7. Motion

- **Depth glide (`eav glide`, CPU, free).** Depth Anything V2 **Small** depth maps (computed by the
  `film_clips` job: for a scene it fills `depth_stills` in from the scene's picks, one `<scene>-<n>.png` per
  non-flat glide shot whose picked still has no map yet, so a glide uses the map of exactly its picked still;
  a scene with no Wan shot left gets a depth-only job), edge-aware (guided filter), two layers split by Otsu, Telea-inpainted occlusions,
  overscan derived from the move, ease `in|out|both|none` (so motion carries through dissolves),
  `--flat` single layer for faces and close-ups (no neck shear), optional `--sweep` of sunlight and
  `--drain` warm-to-cold. A **pull-back** (negative zoom) needs `zoom0` high enough that
  `zoom0 · (1 + min(0, zoom) · near_gain) ≥ 1`, or the shot is refused (no edge band); scene 14's
  pull-back needs `zoom0` of about 1.17 or more.
- **Animated beat (`job film_clips`, Wan 2.2 TI2V-5B).** Only for a named action, life in the frame
  or a climax gesture: about 25–35% of shots. 121 frames at **24 fps** (5.04 s), 24 steps,
  near-lossless, played at native 24 fps with no interpolation; `wan_res` 1280×704 for faces, hands
  and climax beats, 896×512 for environments. A continuation clip (`continue_from`) starts from the
  previous clip's last frame when an action must last longer than 5 s: every take's chain must cover its
  shot's render length (its span plus its transition halves; a chain of k clips plays 120 k + 1 frames) with a
  1-frame margin (so plan and assembly rounding never leave a chain short), or
  `job film_clips` refuses it, and `film --shots` refuses a chain shorter than its shot instead of freezing
  on the last frame. A Wan shot over 6 s also declares one `actions` entry per 6 s in the paper edit (R1).
  `job film_clips --film N --spec clips.json` items carry `key`, `shot` (the plan's Wan shot number;
  every Wan shot needs at least one item in an active job of the scene, several takes are allowed), `image` (a `.png` in `art_dir`)
  or `continue_from`, `prompt`, `seed`, `width`, `height`; an optional `sfx` map
  `{"<name>": "<search words>"}` fetches CC0 sound (below). The compute block is derived, never
  written. With a top-level `"scene"` the job is bound to that scene's approved plan: every item
  names a Wan shot of the plan at that shot's `wan_res`, and every Wan shot has an item; an
  unapproved plan is refused. The depth work is in the forecast (`depth_s`, ESTIMATE 90 s + 4 s per image).
- **Prompt rules for clips.** One concrete physical action; "static locked-off camera" (camera moves
  come from the glide); the builder's negative prompt lists detached or extra hands, floating objects,
  blink, closed eyes, morphing eyelids, transparent cloth and camera movement. Emotional close-ups of
  faces get the glide unless an HD take passes the face gate. Budget 2–3 seeds per action shot.
- **One session per job, resume reserved first.** A job's forecast must fit one Colab session (4200 s, the
  notebook's own hard stop): `job film_clips` splits a longer spec into several jobs (a chain stays in one
  job; the depth stills and the sound fetch ride in the first), each reserved within the caps. `done.json`
  in the Drive job folder records the sha256 of each finished clip and the sound stage runs **before** the
  clips, so a hard stop never discards finished work. A job a hard stop cut short (manifest `INCOMPLETE`) is
  resumed with `job film_clips --resume <job_id> --from <the partial download>`: the remaining items'
  forecast is reserved first as a ledger entry linked to the job, and the resume notebook's hard stop is
  that reservation; the job then imports (or closes) with the CU of all its sessions, settled together.
  Settling refuses actual units past the title or month cap: the owner holds. A100 is preferred when offered.
- Reel rules (≤ 5 clips, 2,700 s, a signed authority file) stay for reels only.

## 8. Score and sound

- **One cue per scene** from ACE-Step stems (`job music` with `"scene"`, each item's `"role"` `drone`,
  `solo` or `phrase`): instrumental, no percussion or vocals, three seeds per stem type. `cue` refuses a
  stems folder that is not an imported music job bound to that scene, and a job another scene's mix already
  used. `cue --scene <id> --pick --tonic <note> --stems <music job>` measures and saves the pick within each
  family (tonic, onset rate, pulse, low end; a stem's role is its item's `role`, else the word in its key);
  then `cue --film N --scene <id> --stems <job> --fx fx.json` writes `audio/<scene>.mix.wav` and `.mix.json`.
- The cue places stems at the plan's cut times, high-passed at 90 Hz, **music silent for 0.4 s on the
  peak** (recorded; `qc` requires the music bus below −80 dBFS there), ducked 80 ms attack / 400 ms
  hold / 800 ms release, scaled so voice sits **17 dB over the music** in speech (refused outside
  16–18 dB), stereo throughout, −16 LUFS, ≤ −1.5 dBTP. No fade on the scene's end: the film's last
  scene fades in assembly. **Never borrow another scene's cue or slice a stem to fill a gap**: a scene
  without its own cue is not mixed.
- **Ambience and foley in every scene** (`--fx`: `{ambience: [...], foley: [...]}` timed to the
  picture). Sources: CC0 or worldwide-public-domain recordings fetched in Colab by the `film_clips`
  sfx stage, or original synthesis dedicated to CC0 recorded in `sfx/README.md`. **Every fx file needs its
  licence record** in a `licences.json` beside it (the imported `film_clips/<job>/sfx/licences.json`, or for
  synthesis `{"<file>": {"title", "licence": "CC0-1.0", "author", "basis": {"rule": "cc0-synthesis"}}}`):
  `cue --fx` refuses a file without one (CC0 or author-released public domain only) and copies it into
  `mix.json`. The sfx stage runs
  first with an 8-minute budget, never fails the job, keeps a file only if a query keyword is a whole
  word in its title and its licence is CC0 or public domain **by the author's own release** (Commons
  categories checked); country-limited or age-based PD (PD-US, PD-old, PD-Art …), incomplete category
  lists and Commons "Public domain" labels without the author's release are refused (the 47-region
  policy needs worldwide status). Freesound is not used.

### Adoption: media the owner already picked (`adopt --spec adopt.json`, 0 CU)

Stills, Wan takes, depth maps and a music job that already exist are bound to one scene's **approved** shots
instead of being generated again. `adopt.json`:
`{"scene", "sources": {"<job id>": {"root": <title root>} | {"folder": <pilot job folder>}}, "stills": {"<scene>-<n>":
{"job", "file"} | {"file", "reason", "from"?}}, "clips": {"<n>": {"job", "takes": [take, continuation…], "art"?:
{"file", "reason"}}}, "depth": {"<scene>-<n>": {"job", "file": "<stem>.depth.png"}}, "music": {"job", "keys"?,
"roles"?}}`. A job not named in `sources` is one of this record. Every file is verified by sha256: against the
output sha256 eav recorded when it imported the job, or, for a pilot job folder eav never imported, against that
job's own outputs `manifest.json` (COMPLETE, `input_zip_sha256` equal to its `inputs.zip`). No manifest is ever
written or edited. A hand-copied file needs the operator's `reason`; its sha256 is recorded and its provenance
traced (byte-identical to a job's output or input image), or a declared `from` derivation is recorded as declared;
an untraced file's licence is recorded as unverified and warned. A take chain must continue as its job built it,
match the shot's `wan_res` and cover the shot with the 1-frame margin; a take without a recorded motion verdict
is gated on adoption, and a clear fail needs a reason in `picks/gate-overrides.json`. A depth map is adopted only
for the exact still it was made from (same image sha256; its job must record Depth Anything V2 Small, or its
own notebook name it); a glide still with no matching map still refuses at assembly. Licences and provenance go
into `jobs/<adopted job>/adoption.json`; the stills get a recorded pick. The same adoption again changes nothing.

## 9. Assembly (`film --film N --shots --logo … --end-card … --title T --author A --narrator V [--burn]`)

Every scene needs its **approved** plan (`film/film-NN/shots/<scene>.json`) and its scene mix. Each
shot renders by `eav.film.render_shot` (glide from its picked still `<scene>-<n>` and the depth map made of
exactly that still, the imported Wan clip chain, or a static still) into `film/film-NN/shots-cache`, keyed by the sha256 of the
shot, its input files and the code version, so a rerun re-renders only what changed (never a whole
film for one shot). A Wan shot with several takes needs `film/film-NN/clip-picks.json`
(`{"<scene>/<n>": "<take's last key>"}`). A still whose `gate.json` is a certain fail is refused
unless a pick/override records a reason.

`assemble_shots` joins at 24 fps with one xfade per transition (dissolve 0.8 s; a cut or match is a
one-frame xfade); frame-aligned scene mixes; the title card (with room tone under it, never digital
zero), the credits card (author, narration voice, AI disclosure, Maison fonts) and the approved END
last; the logo top-right; captions as WebVTT (`mov_text`) **and** SRT (`--burn` also writes
`<film>.burned.mp4`). Captions follow R5: a cue over 15 cps may start up to 0.3 s early and end up
to 1.0 s late, then merge with a neighbour if still too fast; **no merge crosses a chapter heading**
(a fast unit before a heading may extend up to 1.5 s into the chapter-break pause). Master −16 LUFS,
true peak ≤ **−1.5 dBTP**, 1.6 s end-of-picture fade.

One scene alone (a reference scene): `status --scene <ID>` walks only that scene's route, and `film --shots
--scene <ID>` assembles it into `film/film-NN/film-NN-<ID>.mp4` (its own `scene_film` artifact; `qc` checks it
with the film gates); the whole film's route and record are unchanged by it.

The pre-cinematic assembly (`film` without `--shots`: slow push-in per still, ducked score, SRT) still
exists for old films only: it is refused for a film that has any shot plan. Card and end fades run at
16 bits and the master keeps every small residual, so a fade advances every frame (`qc hitches`).

## 10. QC and review (`qc`)

`qc` on a `--shots` film runs the cinematic gates and **fails when any gate cannot run** (`not_run:<gate>`
is a failure, never a pass): R1 new-information gaps, R4 sound on picture, R5 captions, R10 flashes,
loudness and true peak, black bars, hold hashes, one-frame hitches inside dissolves, per-scene
voice-over-music margin (16–18 dB music-only, ≥ 15 dB over everything that is not voice), digital
zero on the **delivered** film (only the last 1.6 s fade tail is exempt) and silence at peaks.
It writes a contact sheet: look at it. Then the candidate-bound review, frame by frame (picture,
motion, sound): opening, every join, the climax and the full ending. The owner approves each finished
film; anything not reviewed stays `unassessed`.

**Per-clip motion gate (built: `eav/motiongate.py`, `motiongate` command).** Every imported `film_clips` take is
gated at import: periodic near-duplicate frames (stutter) and isolated difference spikes (an outlier frame or a
jump) beside it as `<key>.motion.json` (recorded with its sha256) and a contact sheet of every 4th frame. A clear
fail (`pass` false) blocks `film --shots` unless `picks/gate-overrides.json` records a reason for that take;
`needs_review` (borderline, nearly static, undecodable) is advisory: `film --shots` prints every such take,
records it in the film's meta and `qc` lists it in the report. A missing, unreadable or edited `motion.json`
never passes silently: the take is gated again on demand. Thresholds are uncalibrated (measured values are kept
for calibration). The standalone `motiongate <clips>` gates any folder without a record.

**How each gate treats "not run", "unclear" and a fail:**

| Gate | Not run | Unclear | Clear fail | Calibration |
|---|---|---|---|---|
| Still gate (Colab) | needs_review | needs_review: advisory until `gate-calibration.json`, then `--override` | blocks unless `--override-fail` / `gate-overrides.json` | presence of `gate-calibration.json` |
| Motion gate (import) | gated on demand by `film --shots` | needs_review: printed, recorded, listed by `qc` | blocks unless `gate-overrides.json` | uncalibrated |
| Voicecheck words | `pass: None`, joins, NOT RUN listed by `qc` | provisional ceiling: warning | redo | median of accepted takes |
| Voicecheck absolute limits | n/a | warning with the measured value | warning until calibrated (`calibrated_limits`), then redo; 3 takes, then the owner | owner-calibrated |
| Voicecheck relative and signal checks | n/a | n/a | redo; 3 takes, then the owner; `--accept PID=reason` | profile of the book |
| QC (film) | `not_run:<gate>` = fail | n/a | fail | — |

## 11. The reference scene: বিচারক scene 14 v4

The standard every scene is held to. **Spine:** Hem, sleepless in a shut carriage, realises that
morning will bring shame to her home. 55.5 s in 11 shots (about one per 4.7 s); the voice starts
0.85 s in. Hem's **own bed, empty** is planted early; sunlight later crawls onto the empty pillow
and motivates the peak: the mother drops the pot on a hard cut into silence.

Shots: the night lane; a daughter asleep; Hem's empty bed; Hem's close-up in the shut carriage with
slats of moonlight (animated: she turns into the light, one slow blink); the mother sweeping,
pausing toward Hem's door (animated); the paan-making place from scene 13 with Hem's place empty;
Hem's eye at the slat, match-cut to the sunrise wall; sunlight onto the empty pillow; the mother's
discovery (peak); neighbours gathering with murmur and a distant wail, colour draining, carriage
wheels bridging into scene 15. New material: 4 stills, 2–3 animated clips, own ambience (night
beds, broom, pot drop, crowd, wheels). The pilot files and the AV script are kept in
`production/audiovisual/bicharak/pilot/`; scene 14 v4 is built first with these commands as the
acceptance test and passes the owner before the next scene.

## 12. Audiobook and bundles

The audiobook has its own master, chapters and sentence timing (`bundle-audio`, default
`--profile audiobook`): see [publishing.md](publishing.md). `bundle-film` packages a `--shots` film.
