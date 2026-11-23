# Reel recipe: Squint-grade story reels

Benchmark: the viewer experience of @watchsquint reels, adapted from nature cycles to
**stories**. One or two reels per title, 1080×1920, exactly 60 s (100–125 spoken words)
or 120 s (200–245). Each reel is its own 9:16 composition, never a crop of the film.

## Why Squint reels spread (what we copy)

- **A claim on frame 1 that sounds wrong but is true.** The voice starts on the first
  frame with no intro, logo or "did you know". The picture shows the claim in the same
  second. That second decides the scroll.
- **One subject in one continuous world.** Same people, same place, same light family,
  shot after shot, as if one camera stayed there. Continuity makes AI footage feel like
  cinema instead of a slideshow.
- **Time moves forward every ~5 s.** Each shot is the next step of the story. Novelty
  keeps the thumb still; the steady rhythm never feels frantic.
- **A loop.** The story opens at its most striking moment, runs its arc, and the last line
  and last image lead back into the first. Replays feel like continuation.
- **Calm narration.** One warm, unhurried narrator, wonder without hype, short natural
  pauses; a quiet bed audible only between sentences.
- **A clean frame.** No subtitles, stickers or logos. The image is the hero.
- **The share trigger.** A line people can quote, and an honest local connection
  (a Bengali place, word or custom) when the book has one.

## From a book to a reel arc

| Squint (nature) | Earnalism (stories) |
|---|---|
| strangest life stage | the book's most striking moment: a reveal, a reversal, an image |
| the life cycle | the story's arc from that moment back to it |
| "This flower drowns itself on purpose." | "This giant built a wall against children." (The Selfish Giant: true to the book, ≤ 8 words) |
| one creature, one pond | one protagonist, one setting, one light family |
| local name for the plant | the Bengali title, place or custom in the story |

## Script (`reel N --script reel-N.json`)

```json
{"length": 60, "language": "bn", "hook": "<≤ 8 words>",
 "lines": ["<hook, again>", "<line>", "...", "<loop close>"], "loop_close": "<loop close>"}
```

- `lines[0]` is the hook and `lines[-1]` the loop close: both are spoken.
- Shape: hook → explain the hook (2 sentences) → the arc, one sentence per shot →
  optional local tie-in → loop close that re-enters the hook moment.
- Reels may condense, but **every claim is true to the book**. For a public-domain text,
  use the book's own sentences wherever possible. No invented scenes, no spoilers the
  book does not support, no call to action in the voice.
- Short declarative sentences, present tense, concrete verbs, one idea each. Bengali is
  written in Bengali, not translated from an English draft.
- Write five hooks, keep the truest, shortest and most visual. No question marks.
- `validate_script` enforces length, word budget and hook length; once the reel
  narration is imported it also checks the **measured** narration fits the length ± 3 s.
- Lines are paced like Squint: 400 ms between lines.

## Order of work (R20: timing is measured, never assumed)

1. `reel N --script reel-N.json`: script and caption. No shots yet.
2. The owner approves the script; then `job narration --reel N` → Colab → `import`.
3. `reel N --plan-shots`: measures the imported narration and plans
   `ceil(narration / 5.0417 s)` shots, one real Wan clip each (121 frames at 24 fps).
   Only the last shot is trimmed (picture ends 0.5 s after the last word, at least
   1.5 s), never stretched; each shot carries the line spoken at its midpoint, from the
   measured line timings. If the measured narration does not fit the length ± 3 s, it
   stops (exit 5): rewrite the script's words, `reel N --script` again (allowed after a
   misfit) and build new reel narration. Example: 60 s of speech → 12 shots; 120 s → 24.
4. Keyframes: `job stills --reel N` with one prompt per shot of `shots.json` (key = shot id).
5. Clips: `job reel_clips --reel N` once per batch of **at most 5 shots** (next section);
   each batch is one Wan job, forecast and reserved in full.
6. `reel N --score <bed> --score-route ...` assembles from every imported batch, in
   `shots.json` order, once every planned shot has a clip.

### The plan is bound to its narration (R27)

`--plan-shots` records the narration job it measured and the sha256 of `shots.json`.
From then on `reel_clips` batches and `reel N` use exactly that narration and that file:
they refuse if `shots.json` changed, if that narration job ended, or if a newer reel
narration was imported. `job narration --reel N` is refused once shots are planned.

**Re-voicing a reel** (a new take of its narration) therefore means:
1. `supersede` (never ran) or `close` (ran, with the CU Colab shows) every `reel_clips`
   batch of the current plan. Imported clips cannot be retired: re-voice as a new reel
   number instead.
2. `reel N --script <script>` (the same or a revised script) retires the old plan.
3. Build and import the new reel narration, run a fresh `reel N --plan-shots`, build the
   keyframes and the clip batches again from the new `shots.json`.

## Pictures

1. Keyframes (`job stills --reel N`): one FLUX still per shot from the title's world
   bible, 768×1344 portrait. Shot 1 literally shows the hook. Re-anchor identity every
   2–3 shots by repeating the character sheet and reusing anchor stills.
2. Motion (`job reel_clips --reel N`): Wan 2.2 image-to-video, `l4-balanced-v2`
   (512×896, 24 steps). Motion comes from the subject (a hand, cloth, water, light), the
   camera stays locked-off or pushes in slowly. Prompts name the motion and the negatives
   (no text, no morphing faces, no extra limbs, no cuts).
3. Takes chain last frame to first; generator audio is muted.
4. **Loop close**: Wan cannot target an end frame, so the loop closes in the edit with a
   designed match-cut or a short dissolve into frame 1 where the action resolves back into
   the hook image. QC checks that the join reads as continuous, not pixel-identical.

## Clips spec (`job reel_clips --reel N --spec clips.json`, one per batch)

Example shape (replace the evidence values with the actual journal entries):

```json
{"art_dir": "<title root>/stills/<reel-N stills job_id>",
 "prior_attempt_evidence": {"run_ids": ["diwali-wan22-pilot-v2", "diwali-wan22-pilot-v3"],
                            "profile": "l4-balanced-v2", "observed_step_seconds": 11.4,
                            "completed_clips": 2, "source": "earnalism-video/software/WAN22_COLAB.md"},
 "shots": [{"id": "shot-01", "image": "reel-1-shot-01.png", "seed": 4101,
            "prompt": "<what moves and how; camera locked-off; negatives>"}]}
```

- `art_dir`: the folder holding the imported keyframe stills (`<root>/stills/<job_id>/`
  after `import`). Relative paths resolve against the spec file's folder.
- `prior_attempt_evidence` (required by the `wan22` batch contract, non-empty): the
  retained provenance that qualifies the `l4-balanced-v2` profile for this run. It names
  the earlier Wan runs this one builds on (their run ids, observed s/step, completed and
  failed clips), copied from the Wan journals recorded in
  `earnalism-video/software/WAN22_COLAB.md`. For a recovery of a failed reel clip it
  names that job id and its import receipt instead. It is evidence, never invented
  numbers.
- `shots`: the next **at most 5** uncovered shots of `reels/reel-N/shots.json` (the CLI's
  `Next:` line names them). A batch must fit one Wan job: 2700 s wall at the measured
  ~500 s per clip, and an owner authority of at most 5 CU. Ids not in `shots.json`, or
  already in another active batch, are refused.
  - `id`: the shot's id from `shots.json` (`shot-01`, `shot-02`, ...).
  - `image`: the keyframe's basename inside `art_dir` (hashed into the job).
  - `seed`: an integer, kept in the record.
  - `prompt`: the subject's motion (10–3000 characters); no end frame can be set.
- The profile is fixed by the CLI to `l4-balanced-v2` (512×896, 121 frames, 24 fps,
  24 steps, guidance 5). The spec cannot change it, and takes are 1 (one start per shot).
- No `compute` block and no `wall_seconds`: the forecast is the batch's shot count × the
  measured `clip_s` × 1.15 (rates.json), and the Wan wall is bound to that forecast
  (600–2700 s). A `compute` block that disagrees with the shots is refused (R21).

## Running a batch in Colab (the owner; R22)

The Wan batch notebook (`Earnalism_Wan22_Warm_Batch.ipynb` in `jobs/<job_id>/`) has **no
`RUN` flag**. Its config cell holds independent flags, all `False`; the owner sets each to
`True` only after the previous cell succeeded:

1. `RUN_BATCH`: writes the bound software and job into `/content/earnalism-<job_id>`.
2. Upload `wan22-batch-inputs.zip` with Colab Files as `/content/wan22-batch-inputs.zip`;
   `VERIFY_INPUTS` checks its sha256 and every source image hash.
3. **The owner writes and signs** `/content/wan22-batch-authority.json` for this exact job.
   Claude never writes, edits, drafts or fills in this file:
   ```json
   {"schema": "earnalism.wan22-batch-authority.v1", "owner_authorized": true,
    "job_sha256": "<sha256 of jobs/<job_id>/job.json; the CLI's Next: line prints it>",
    "evidence_ref": "<the owner's own approval record for this batch>",
    "observed_units_per_hour": <the rate Colab shows for this allocation>,
    "approved_compute_units": <at most 5, and at least 2 x that rate x wall_seconds / 3600>,
    "free_runtime_confirmed": false,
    "allocation_started_at": <unix time this allocation started>}
   ```
   `batch.py` refuses anything else (a different job hash, an expired allocation, more
   than 5 CU or less than twice the wall at the observed rate).
4. `BEGIN_ALLOCATION`: binds the authority and the job's wall (the forecast, ≤ 2700 s),
   arms the runtime unassign guard and runs the hardware preflight.
5. `SETUP_BATCH`, then `GENERATE_BATCH` (leave `RESUME_UNATTEMPTED` False).
6. `EXPORT_AND_DOWNLOAD`: prints `export-receipt.json` (with `archive_sha256`) and
   downloads the archive. Then locally: `import <job_id> --from <archive.zip>
   --archive-sha256 <archive_sha256> --units <CU shown in Colab>`.
7. After the import verified, `LOCAL_IMPORT_VERIFIED` and `DISCONNECT_RUNTIME`.

A batch that ran but cannot be imported (partial export, crash, lost download) is ended
with `close <job_id> --units <CU shown in Colab> --reason "..."`; its shots stay
uncovered, and rebuilding them is a new batch the owner decides on.

## Sound

Reel narration is its own narration job (`job narration --reel N`), same voice and
preset, 400 ms between lines. The hook is spoken from 0.0–0.2 s (`qc` measures the
onset on the reel narration and fails `hook_onset` otherwise). Bed: a quiet score cue,
no drums or vocals. Master: −14 LUFS, true peak ≤ −1 dBTP. Narration is never trimmed:
the shots are planned from it, so the picture always covers it.

## On-screen text

Only "AI-generated visuals", small, in the safe area, for the first 3 s (India's 2026 IT
Rules disclosure). Nothing else is burned in.

## Caption (written by `reel N --script`)

Title-case hook plus one emoji, then the spoken script, then about five hashtags that
always include `#earnalism #learnalism #theearnalism`. No engagement bait.

## Review the reel

Contact sheet at one frame per second: anatomy, identity drift, stray text, colour jumps,
and the last frame flowing into the first. Fix by regenerating the failing shot only.
