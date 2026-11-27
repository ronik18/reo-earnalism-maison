# বিচারক scene 14 v5: acceptance test of the fixed `earnalism-audiovisual` skill (eav commands only)

Built 27 Nov 2026 in a scratch title root, `pilot/v5/root`. Everything ran locally. No Colab or GPU job was
built, staged or run, no ElevenLabs generation happened, and nothing was spent. No signed URL or `exchange.json`
was written. The source clips, stills, the v4 take, the real record (`../../record.json`), `film/film-01/` and the
shared allowance ledger were not touched; the scratch ledger was never written (no job was reserved). No skill code
was changed. No fallback driver was written.

**Result: BLOCKED before the first GPU job. There is no film and `eav qc` has nothing to check.**
`scene14-v5.mp4` and `scene14-v5.burned.mp4` do not exist.

The eav route ran through the voice import, the clause timing and the paper edit (`plan-shots`: 12 shots, R1–R3
pass). It stops at two points the operator may not cross alone:

1. **R11 approval.** The paper edit needs Claude plus an independent reviewer (and, for the reference scene, the
   owner). No independent reviewer was available to this run, and no approval was recorded.
2. **The first GPU job.** The approved picks cannot enter the scene's cinematic flow (G1). Every shot needs media
   from new, scene-bound GPU jobs (forecasts below). By the hard limits, this run stops there.

Even without the blocks, the imported narration is degraded (G3) and the v4 model id is unrecorded (G2). The voice
must be re-imported before any approval.

## Outputs (this folder; gitignored media)

| File | What |
|---|---|
| `root/` | Scratch title root: `record.json`, `plan.json`, `voice.json` (placeholder id, G2), `film/film-01/voice/f01s014.{wav,passages.json}`, `voice/passages/` (retimed passage, voicecheck, profile), `shots/f01s014.{input.json,json,av.md,timing.json}` |
| `take-scripts/f01s014-p01.txt` | The scene's untagged text, exactly the plan's (one passage) |
| `takes/f01s014-p01.wav` | Byte copy of `pilot/voice/v2/v4-retimed.wav` (sha256 `b644a867…`) |
| `passages/` | `split-passages` output for all of film-01 (41 untagged passage scripts) |
| `motion/` | Standalone `motiongate` verdicts and contact sheets of the five picked Wan takes |

## Paper edit (`plan-shots`, not approved)

Scene 55.171 s: a 0.85 s lead-in, speech from 0.85 s to 53.171 s, and a 2.0 s tail.

| n | start–end (s) | len | picked media | motion | layer | in | narration |
|---|---|---|---|---|---|---|---|
| 1 | 0.00–2.52 | 2.52 | night lane (still) | glide push 0.16, ease in | present | cut | মনে হইতে লাগিল, |
| 2 | 2.52–8.38 | 5.86 | daughter asleep (still) | glide push 0.12 | imagined | dissolve | পৃথিবীতে … নিমগ্ন। |
| 3 | 8.38–12.31 | 3.93 | Hem's empty bed, **PLANT** (still) | glide push 0.10 | imagined | cut | সেই আপনার ঘরে … মধ্যে |
| 4 | 12.31–16.73 | 4.42 | **12a** (motion-pilot4), Hem turns into the moonlight | Wan 1280×704 | present | dissolve | নিস্তব্ধ … তাহা |
| 5 | 16.73–20.09 | 3.37 | v6 `f01s014-7` (7-c1, corrected eye) | glide flat 0.15, ease out | present | cut | ইতিপূর্ব্বে … নাই! |
| 6 | 20.09–23.77 | 3.68 | **new still needed**: a grown daughter of the lane wakes at dawn | glide push 0.10 | imagined | dissolve | ঘরের মেয়েরা … উঠিবে, |
| 7 | 23.77–27.06 | 3.29 | **14w** (motion-pilot6), paan place, Hem's place empty | Wan 1280×704 | imagined | cut | নিঃসঙ্কোচে … হইবে, |
| 8 | 27.06–30.83 | 3.77 | **new still needed**: Hem in the slat of moonlight | glide flat 0.08, ease out | present | dissolve | আর গৃহচ্যুতা … রাত্রি |
| 9 | 30.83–35.76 | 4.92 | sunrise wall (still) | glide push 0.10, sweep down-left, ease in | imagined | **match** | কোন্‌খানে … প্রভাতে |
| 10 | 35.76–45.28 | 9.53 | **door beat 13q→13r** (motion-pilot6), veiled mother, 2 declared actions | Wan 1280×704, chain of 2 (241 frames for 230 needed) | imagined | cut | তাহাদের … পতিত হইবে |
| 11 | 45.28–49.44 | 4.15 | **9p** (motion-pilot6), pot drop: **PEAK** at 45.65 s (82.7 %), plants 3 and 10 | Wan 1280×704 | imagined | cut | তখন সেখানে সহসা … পড়িবে, |
| 12 | 49.44–55.17 | 5.74 | neighbours (still) | glide pull −0.12, zoom0 1.17, drain, ease out | imagined | cut | কি লাঞ্ছনা … উঠিবে! |

- **Shots:** 12 (the spec says 11, see G8). Four of them are Wan shots with five clips, which is 33 % of the shots.
- **Planning estimate:** "5 Wan clip(s), about 3.0 CU" (G9).
- **R7 and R8:** no soft flags. The fidelity note and the motifs are declared.

## Commands run

All `eav` commands ran from `skills/earnalism-audiovisual/software` as `python3 -m eav.cli …`.
`B` = `production/audiovisual/bicharak`, `V` = `B/pilot/v5` and `R` = `V/root`.

1. `init B/source.json --root R --ledger V/allowance-ledger.json --slug bicharak`: exit 0.
2. `plan --root R`: exit 0. It produced 19 scenes, and scene f01s014 is identical to the real `plan.json`.
3. `status --root R`: exit 0. `Next:` asks for `voice.json`.
4. Wrote `R/voice.json` = `{"model_id": "unrecorded-eleven-v4"}`. This is a deliberate placeholder: no Eleven v4
   model id is recorded anywhere (G2).
5. `split-passages film-01 --root R --out V/passages`: exit 0. It splits f01s014 into two passages, but the take on
   file is one 51.9 s scene take (G4).
6. Copied `v4-retimed.wav` to `V/takes/f01s014-p01.wav` (byte copy), and wrote the scene text unchanged to
   `V/take-scripts/f01s014-p01.txt`.
7. `import-take film-01 --root R --scene f01s014 --scripts V/take-scripts --audio V/takes --engine elevenlabs
   --model unrecorded-eleven-v4 --voice-id j5PhP1QJv2DvlhRv3mEv --voice-name "Subhajit – Grounded Bengali
   Storyteller" --credits 0`: exit 0.
   - Voicecheck WARNING `no_breath` 9.0122 against the uncalibrated limit 9. This is a warning, not a redo, so
     `--accept` was not needed.
   - `duration` is a warning (a run of one passage). The word check was NOT RUN (no transcript).
   - Joined to `film/film-01/voice/f01s014.wav`: 55.171 s, lead-in 0.85 s, tail 2.0 s.
   - **The re-retime moved the take's pauses (G3).** 0 credits.
8. `scene-timing --root R --film 1 --scene f01s014`: exit 2, "11 pause(s) of at least 0.3 s for 7 clause
   boundaries".
9. `scene-timing … --min-pause 0.35` and `… --min-pause 0.4`: exit 2 (10 pauses each).
10. `scene-timing … --min-pause 0.45`: exit 0 and wrote `f01s014.timing.json`. **Its mapping is wrong (G5),** so the
    file is not used.
11. Following that command's own `Next:` ("or time this scene's clauses by ear into the planner input's
    `timing`"), wrote `shots/f01s014.input.json`, Claude-authored, with 14 timing entries:
    - Times are measured pauses of the joined wav: `retime.detect_pauses` at −38 dB/0.15 s, plus the in-clause
      breaths at 12.22, 15.82 and 47.02 s at −34 dB.
    - Word placement at the three unpunctuated breaths is **estimated** (no ASR), and agrees with the v4 pilot's
      clause split within 0.4 s.
    - `length_s` is 55.171.
12. `plan-shots --root R --film 1 --scene f01s014 --bible B/specs/world-bible.json`: exit 0, "12 shots, 55.2 s, 5
    Wan clip(s), about 3.0 CU; rules R1-R3 pass, ready for approval".
13. `motiongate <13q> <13r> <14w> <9p> <motion-pilot4 12a> --out V/motion`: exit 0.
    - 13q and 14w pass.
    - 13r, 9p and 12a are REVIEW (spikes classed as motion). None fails.
14. Looked at the 13q/13r/9p/14w contact sheets. Shot 10's subject and `actions` were corrected to what the takes
    show: she pauses with the broom, then turns her head toward the door. She does not walk to it.
15. Re-ran step 12 with the corrected input: exit 0, the same result. The plan is **not approved** (G7).
16. `status --root R`: exit 0. `Next:` asks for scene **f01s001**'s voice (G6).
17. `film --root R --film 1 --shots --logo <production-lockup.png> --end-card <standard-intro landscape.mp4> --title
    বিচারক --author "রবীন্দ্রনাথ ঠাকুর" --narrator "Subhajit – Grounded Bengali Storyteller" --burn`: exit **2**,
    "scene f01s001 has no shot plan" (G6).
18. `qc --root R`: "STOP: nothing assembled yet".

The following were **not run**: approval, `job stills`, `pick`, `job film_clips`, `job music`, `cue`, a real
`film --shots`, `qc` on a film and frame extraction. Each comes after a block.

## GPU stop point (not built, staged or run)

The next eav step after approval is the scene-bound `job stills`. Then come `pick`, `film_clips` (Wan clips plus
depth), `music`, `cue`, `film --shots` and `qc`.

Forecasts come from `production/audiovisual/rates.json` through `eav.budget.forecast` (arithmetic only; no job
was built):

| # | Job | Contents | Forecast |
|---|---|---|---|
| 1 | **`job stills --spec` (`"scene": "f01s014"`)**, the first stop | 8 glide shots (1, 2, 3, 5, 6, 8, 9, 12) × 3 candidates = 24 stills, gated | **1.47 CU** (2721 s at 1.94 CU/h) |
| 2 | `job film_clips` (Wan) | 5 HD clips: shot 4, shot 7, shot 10 (2-clip chain), shot 11 | L4 6195 s is over the 4200 s session limit, so it splits 3 + 2 clips: 2.75 + 2.06 = **4.81 CU**. On an A100: **2.82 CU** |
| 3 | `job film_clips` (depth only, after the pick) | 6 non-flat glide picks (1, 2, 3, 6, 9, 12) | **0.76 CU** |
| 4 | `job music` (`"scene"`, roles) | drone / solo / phrase × 3 seeds | about **1.6 CU** (music-pilot3b, a job of the same kind, forecast 1.60) |

The total is about **8.6 CU on L4**. Most of it would regenerate media the owner has already picked (12a, 13q→13r,
9p, 14w, and the v6 stills), because of G1. Only shots 6 and 8 need genuinely new stills.

## Measurements (scene voice, `film/film-01/voice/f01s014.wav`)

- **Length:** 55.171 s. The first word lands at 0.85 s (R9: 0.5–1 s) and speech ends at 53.171 s, leaving a
  2.0 s tail.
- **Voicecheck:** pass `null`. Warnings: `no_breath` 9.0122 against 9 (uncalibrated) and `duration` (expected
  46.15 s from the 13 cps estimate). Words: not run.
- **Pauses at −34 dB, original take → re-retimed passage (G3):**

  | Place in the text | Original take | After re-retime |
  |---|---|---|
  | after "তাহা" (no punctuation) | 15.42–15.80 (0.38 s) | 15.35–16.87 (**1.51 s**) |
  | after "নাই!" | 18.04–19.67 (**1.63 s**) | 19.11–19.56 (**0.46 s**) |
  | after "রাত্রি" (no punctuation) | 30.18–30.44 (0.26 s) | 29.84–30.30 (0.46 s) |
  | after "প্রভাত হইবে," | 31.91–32.59 (0.68 s) | 31.77–33.17 (**1.39 s**) |

## QC result

**Not run: there is no film** (`qc`: "nothing assembled yet"). The gates (loudness, true_peak, new_info, holds,
black_bars, hitches, flashes, sound_on_picture, captions, margin, peak_silence, digital_zero) are all **not run**.
Nothing is assessed; listening and frame review are **unassessed**.

## Acceptance findings

- **G1 (blocker, command gap): the already-imported, owner-picked pilot media cannot enter a scene's cinematic flow
  without new GPU jobs.**
  - The eav jobs `stills-pilot4..7-f01s014`, `motion-pilot6-f01s014` and `music-pilot3b-f01s014` in the real record
    were built without a spec `"scene"`. Their `job_target` events have no `scene`, and the motion-pilot6 items
    have no `"shot"`.
  - `_scene_picks` takes only picks of jobs with `scene == sid` (`eav/cli.py:917-934`).
  - `film.pick_wan_clips` takes only items with `shot == n` (`eav/film.py:471`).
  - `_depth_maps` reads only a job's `depth_stills` (`eav/cli.py:949-957`); motion-pilot6 has none.
  - So even in the real root, `film --shots` stops with "have no picked still" or "no film_clips item for shot n".
  - In a scratch root the jobs are absent altogether, and importing their outputs needs a manifest with the scratch
    job's `job_id` and `input_zip_sha256` (`eav/importer.py:138-145`). No manifest was forged.
  - The v6 art picks (`pilot/v6/art/f01s014-{7,9,13,14}.png`) are hand-copied files and have no recorded pick.
    `f01s014-13` is also a hand OpenCV touch-up made outside `eav touchup` (`pilot/v5/stills/README.md`).
  - **Needs a decision:** either an adoption path (bind an imported job's items to a scene and shots, and record
    picks of its existing candidates; a code change, not a one-liner), or about 8.6 CU of regeneration (above).
- **G2 (blocker, record gap): no Eleven v4 model id is on record.**
  - `voice.json` is absent in the title root, and no file in the repo names the v4 model.
  - `import-take` needs it (`eav/cli.py:1372-1387`). This run used the placeholder `unrecorded-eleven-v4`, so the
    scratch record's model field is a placeholder, not a fact.
  - The owner must supply the id that generated `v4-retimed.wav`.
- **G3 (defect, narration damaged): `import-take` re-retimes a take, and `retime.plan_pauses` maps every detected
  pause in text order to the punctuation marks, including unpunctuated breaths** (`eav/retime.py:131-144`, called
  at `eav/cli.py:1475-1477`).
  - The owner-endorsed take is already retimed. Re-retiming it moved the dramatic 1.63 s pause after "নাই!" into the
    middle of the sentence after "তাহা" (1.51 s), shrank the "নাই!" pause to 0.46 s, and doubled the comma pause
    after "প্রভাত হইবে," (0.68 → 1.39 s). See the table above.
  - The same in-order mapping will mis-time any real v4 take with an in-clause breath.
  - Two things are needed:
    1. a retime that skips breaths it cannot match to punctuation (a code fix, not a one-liner);
    2. the raw downloaded v4 take, or an import option for a take that is already retimed.
  - The source transcript is unchanged. Only its pauses moved.
- **G4 (route mismatch, warning only):** the v4 take is one 51.9 s scene take, but `split-passages` cuts the scene
  into two passages.
  - Cutting the audio by hand would be a hand-patch, so it was imported as one 46 s-of-speech passage.
  - `import-take` does not hold a passage to 15–30 s.
  - With a run of one passage, `duration` is only a warning, and the voicecheck profile is measured from this one
    take. The profile saved in the scratch root is therefore uncalibrated.
- **G5 (defect): `scene-timing` checks only the pause count, never the positions** (`eav/cli.py:3540-3556`).
  - At `--min-pause 0.45` the count matched (7), but the mapping took the in-clause breath at 44.92 s and missed the
    0.45 s comma pause at 26.83 s.
  - Clauses 6–8 were therefore mislabelled. For example, "এবং সেই … পড়িবে," was timed as 3.4 s, when it runs about
    15 s. The command wrote the file and exited 0 without a warning.
  - Partly caused by G3, which made comma pauses shorter than a breath.
  - The timing was hand-entered through the documented `"timing"` path, and its word placement is estimated.
- **G6 (command gap, F6 still open): there is no per-scene route.**
  - `status` / `Next:` walks the film from f01s001 (`eav/cli.py:665-677`, `680+`). After every scene-14 step it
    points back to scene 1.
  - `film --shots` has no `--scene` and stops on "scene f01s001 has no shot plan" (`eav/cli.py:1998-2017`).
  - A reference-scene build cannot follow `Next:` or assemble without restricting `plan.json`, which v4 did by hand.
- **G7 (process stop): R11 approval needs an independent reviewer, and none was available.** The reference scene
  also needs the owner. The plan stays NOT APPROVED, and no approval string was invented (compare v4's F16).
- **G8 (plan, F1 carries over): 12 shots, not the spec's 11.**
  - With this narration, shots 5+6 (6.9 s) and 8+9 (8.7 s) cannot merge as glides under R1.
  - The door beat replaces the old shot 10 as ruled. The spec's "sunlight onto the empty pillow" shot is still
    absent (the planted payoff is the empty bed, shot 3).
- **G9 (estimate, F15 partly open): the `plan-shots` compute** reports "5 Wan clips, about 3.0 CU". It counts the
  chain now, but it ignores takes that already exist and uses 0.6 CU per clip. The job forecast from `rates.json`
  is 4.13 CU on L4 for the same five clips.
- **G10 (F3 still open, not exercised): standalone `glide`** has no `--zoom0` or `--near-gain` (parser at
  `eav/cli.py:3725-3736`).
- **G11 (minor, scratch only): the scratch root shows a lifetime cap of 60, not 100.** `title-caps.json` sits only
  beside the real ledger (`eav/budget.py:59-71`). Forecasts above are unaffected.
- **G12 (picture risk): the door beat (13q→13r) is nearly static.** In its contact sheets the mother stands with the
  broom and only turns her head.
  - `plan-shots` passes the shot on its two declared actions.
  - `qc new_info` measures frame similarity, and may fail shot 10 (9.5 s) as it failed v4's sweeping shot.
  - Worth checking before spending on regeneration.
- **G13 (review, not failure): the motion gate flags 13r, 9p and 12a as REVIEW**, with spikes classed as motion:
  - 9p at frames 10–17 and 111–113;
  - 12a at frames 21–31 and 63–80, the blink and turn known from pilot calibration;
  - 13r at frame 115.

  13q and 14w pass. The thresholds are uncalibrated.

## Remaining owner-review items

1. **Approve the scene 14 paper edit** (the AV table above, `root/film/film-01/shots/f01s014.av.md`), or rule on
   the 12-shot count (G8). An independent reviewer is also needed (G7).
2. **Choose between regenerating about 8.6 CU** of already-picked media through scene-bound jobs, and asking for an
   eav adoption path for the imported pilot jobs (G1).
3. **Supply the Eleven v4 model id**, and the raw downloaded v4 take if it exists (G2, G3). Until the retime fix
   lands (G3), the imported scene voice misplaces the "নাই!" held breath.
4. **Picture checks:**
   - 13q/13r: the door beat is nearly static (G12).
   - 9p: the pot drop is REVIEW in the motion gate.
   - 12a and the 7-c1 eye still: confirm the eye colour matches.
   - The contact sheets show one consistent veiled mother (white sari, red border, head covered) across 13q, 13r,
     9p and 14w.
5. **New stills for shots 6 and 8** have no existing material.
6. **Listening and frame review stay unassessed.** No film exists.
