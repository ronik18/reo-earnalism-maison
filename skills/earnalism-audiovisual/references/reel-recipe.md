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
- **Time moves forward every 5–7.5 s.** Each shot is the next step of the story. Novelty
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
- `validate_script` enforces length, word budget and hook length; `shot_list` cuts
  ~6 s shots, each tied to the line spoken at its midpoint.

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

## Clips spec (`job reel_clips --reel N --spec clips.json`)

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
- `shots`: one entry per line of `reels/reel-N/shots.json`, in order.
  - `id`: lowercase letters, digits and hyphens, unique.
  - `image`: the keyframe's basename inside `art_dir` (hashed into the job).
  - `seed`: an integer, kept in the record.
  - `prompt`: the subject's motion (10–3000 characters); no end frame can be set.
- The profile is fixed by the CLI to `l4-balanced-v2` (512×896, 121 frames, 24 fps,
  24 steps, guidance 5). The spec cannot change it; to fit the budget, cut takes or shots.
- `compute` is optional: without it the CLI uses the measured `reel_clips` rates and
  counts the shots.

## Sound

Reel narration is its own narration job (`job narration --reel N`), same voice and
preset. The hook is spoken from 0.0–0.2 s. Bed: a quiet score cue, no drums or vocals.
Master: −14 LUFS, true peak ≤ −1 dBTP. Narration is never trimmed: if it is longer than
the clips, add or lengthen a shot.

## On-screen text

Only "AI-generated visuals", small, in the safe area, for the first 3 s (India's 2026 IT
Rules disclosure). Nothing else is burned in.

## Caption (written by `reel N --script`)

Title-case hook plus one emoji, then the spoken script, then about five hashtags that
always include `#earnalism #learnalism #theearnalism`. No engagement bait.

## Review the reel

Contact sheet at one frame per second: anatomy, identity drift, stray text, colour jumps,
and the last frame flowing into the first. Fix by regenerating the failing shot only.
