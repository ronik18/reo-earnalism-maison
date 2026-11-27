# Earnalism Cinematic Film Upgrade: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the pilot-v3 production method (beat-locked shots, depth glides, selective Wan motion, Eleven v4 passages with re-timed pauses, per-scene cues, ambience, and QC gates) the permanent `eav` standard, with tests.

**Architecture:** The spike scripts in `/tmp/claude-0/-home-user-reo-earnalism-maison/d619a5d1-fba8-5cb0-a0f4-7eaa7034c807/scratchpad/motion_pilot/` become `eav` modules:
- `glide3.py` → `eav/glide.py`
- `retime.py` → `eav/retime.py`
- `mix3.py` → `eav/cue.py`
- `compose3.py` → `eav/film.py assemble_shots`
- `build3.py`'s Wan cell → the `film_clips` job template

New pure modules:
- `eav/shotplan.py`: two-column AV script and rules R1–R3, R11.
- `eav/voicecheck.py`: the redo gate.

`qc.py` gains the edit, audio and safety gates (R1, R5, R10); `mix.py` gains the audiobook master. Each module is used from `cli.py` through new subcommands (`plan-shots`, `glide`, `retime`, `voicecheck`, `cue`, `film --shots`). The skill text in `SKILL.md` and `references/` is rewritten to the new standard. Everything is mirrored byte-identically into `.agents/skills/earnalism-audiovisual/`.

**Tech stack:** Python 3.13, numpy, opencv-python-headless 5.1.0.95 (already pinned in `requirements-touchup.txt`, Apache-2.0), ffmpeg/ffprobe, unittest/pytest. Colab templates: diffusers 0.37.0, Wan-AI/Wan2.2-TI2V-5B-Diffusers, Depth Anything V2 Small, MediaPipe (Apache-2.0), OWLv2 (Apache-2.0).

**Spec:** `docs/superpowers/specs/2026-11-27-earnalism-cinematic-film-design.md`. It amends `docs/superpowers/specs/2026-11-23-earnalism-audiovisual-design.md`.

## Global Constraints

- Every change under `skills/earnalism-audiovisual/` is copied byte-identically to `.agents/skills/earnalism-audiovisual/`. `tests/test_skill_files.py::test_mirror_identical` must pass, so run pytest with `-p no:cacheprovider`.
- Licences allowed: Apache-2.0, MIT, CC0, and OpenRAIL++ outputs. Depth Anything V2 **Small** only; Base and Large are non-commercial. No BSD-3 model without owner approval.
- Film master: 24 fps, 1920×1080, H.264 yuv420p faststart, −16 LUFS ±1, true peak ≤ −1.5 dBTP.
- Audiobook master: −18 LUFS ±1, true peak ≤ −2 dBTP after encoding, LRA 4–8 LU, mono 64 kbps, encoded once from PCM.
- Music under the film voice: about 17 dB below during speech; ducking with 80 ms attack, 400 ms hold, 800 ms release.
- Pause re-timing:
  - comma 0.4–0.55 s; । or ? 0.8–1.0 s; an emotional ! before a turn 1.4–1.6 s; scene change 2.0 s;
  - পরিচ্ছেদ heading: 2.5–3 s before, 1.5 s after;
  - each pause varied ±15%;
  - room tone at −62 to −68 dBFS, never digital zero;
  - joins crossfaded over 30–50 ms.
- Shots: count = max(ceil(narration s / 6), beats); 4–8 s each, up to 12 s only with a performed action; never more than 6 s without new visual information (R1).
- Captions (R5): at most 2 lines, at most 42 characters per line, 1–7 s per cue, at most 15 characters per second for Bengali.
- Title cap: default 60 CU lifetime; বিচারক 100 CU (owner, 27 Nov); month cap 100 CU.
- Book words are never changed. Audio tags are performance direction only and are stripped before any text check.
- Named minors (e.g. Hemshashi, 14) appear only in dignified close-ups.
- No model downloads or network fetches from this container. Model work and CC0 fetching happen inside Colab templates.

## Review Focus

1. **Bengali text in captions.**
   - Conjuncts and old spellings (পূর্ব্বে) must never be split mid-grapheme when a cue wraps at 42 characters.
   - Expected: cues split at spaces or punctuation only.
   - Test in Task 8: `test_caption_wrap_keeps_bengali_graphemes`.
2. **Pans close to the source edge.**
   - Overscan must grow with the move, so no frame ever samples outside the image, even for a 300 px pan on a 1344×768 still.
   - Test in Task 2: `test_pan_never_samples_outside_source`.
3. **A take with silence already at its ends, or with no internal pauses.**
   - Re-timing must not create negative-length segments or drop words.
   - Expected: duration only grows by the inserted pauses.
   - Test in Task 3: `test_retime_no_pauses_is_identity`.
4. **Peak silence when the cut falls in the last 0.4 s of the scene.**
   - The cue must not write past the buffer, and the fade-out stays intact.
   - Test in Task 7: `test_peak_silence_at_scene_end_is_clipped`.
5. **Re-running a film_clips job after a partial Colab run.**
   - Finished clips are kept and skipped; only missing keys are generated.
   - Test in Task 6: `test_film_clips_resume_skips_finished_keys`.

---

### Task 1: Per-title compute caps

**Files:**
- Modify: `skills/earnalism-audiovisual/software/eav/budget.py`, lines 14–15 and 108–125
- Create: `production/audiovisual/title-caps.json`, content `{"bicharak": 100.0}`
- Test: `skills/earnalism-audiovisual/software/tests/test_budget.py`

**Interfaces:**
- Produces: `title_cap(ledger_path: Path, title: str) -> float`. It reads `title-caps.json` next to the ledger; the default is `TITLE_CAP` (60.0). `Ledger.reserve` uses it.

- [ ] Step 1: write the failing tests.
  - `test_title_cap_override_allows_up_to_100`: reserving 95 CU for `bicharak` with a caps file of `{"bicharak": 100}` passes; 101 raises `BudgetExceeded`.
  - `test_title_cap_default_60_without_file`: with no caps file, 61 CU raises.
  - `test_title_caps_file_rejects_non_numbers`: a non-numeric value raises `ValueError`.
- [ ] Step 2: run `cd skills/earnalism-audiovisual/software && python3 -m pytest -q -p no:cacheprovider tests/test_budget.py`. Expected: the 3 new tests FAIL.
- [ ] Step 3: implement `title_cap` and use it in `Ledger.reserve`. Keep the error text "title cap {cap:g} units exceeded for {title!r}".
- [ ] Step 4: run the same command. Expected: PASS.
- [ ] Step 5: copy to `.agents`, create `title-caps.json`, then commit `eav: configurable per-title compute caps (bicharak 100 CU, owner 27 Nov)`.

### Task 2: Layered depth glide (`eav/glide.py`, `eav glide`)

**Files:**
- Create: `skills/earnalism-audiovisual/software/eav/glide.py`, ported from the spike's `glide3.py`.
- Modify: `skills/earnalism-audiovisual/software/eav/cli.py`, adding the `glide` subparser and `cmd_glide`.
- Test: `skills/earnalism-audiovisual/software/tests/test_glide.py`

**Interfaces:**
- Produces:
  - `render(image: Path, depth: Path | None, out: Path, seconds: float, *, zoom: float = 0.12, pan_x: float = 0.0, pan_y: float = 0.0, near_gain: float = 1.2, zoom0: float = 1.0, ease: str = "both", flat: bool = False, sweep: str | None = None, drain: bool = False, fps: int = 24) -> dict`
    - `ease` is one of both, in, out or none.
    - `sweep` is "down-left", "down-right" or None.
    - Returns `{"frames": int, "base_overscan": float}`.
  - `load_depth(path) -> np.ndarray` reads either a 16-bit PNG or an `.npy` file and returns float32 values in 0..1.
  - CLI: `eav glide <image> <depth|-> <out.mp4> --seconds S [--zoom --pan-x --pan-y --ease --flat --sweep --drain]`.
- Keep from the spike, exactly:
  - guided filter r=16, eps=1e-3;
  - Otsu near/far split;
  - near mask opened with a 5×5 kernel;
  - alpha blur σ=1.5;
  - inpaint grow 13×13;
  - Telea radius 7 at half resolution;
  - base overscan = 1.03 + max(2·|pan_x|·near_gain/W, 2·|pan_y|·near_gain/H);
  - smootherstep easing ("in" = 2·s(t/2), "out" = 2·s(0.5+t/2)−1).
- Sweep amplitude: 0.14 with tint (0.97, 1.0, 1.03).
- Drain: from warm (0.86, 0.98, 1.16) to cold grey ×0.9 using smootherstep(t).

- [ ] Step 1: write the failing tests. Use a synthetic 1344×768 gradient still with a depth ramp; `seconds=1.0`.
  - `test_frame_count_matches_seconds_at_24fps`: the result's frames == 24 and ffprobe `nb_frames` == 24.
  - `test_pan_never_samples_outside_source`: with pan_x=300, `base_overscan` ≥ 1.03 + 2·300·1.2/1920, and the last frame has no pure-reflection band (no column equals its mirror column ±0 for 20 px at the edge).
  - `test_ease_out_ends_at_rest`: the mean abs frame difference over the last 2 frames is less than 0.25× that over frames 10–11.
  - `test_ease_in_leaves_moving`: the difference over the last 2 frames is more than 0.5× the mid-clip difference.
  - `test_flat_mode_has_no_parallax`: with `flat=True`, the frame equals a pure centre zoom of the still (PSNR > 40 dB against a cv2 resize-crop reference).
  - `test_drain_ends_greyer`: the last frame's saturation is below 0.5× the first frame's.
- [ ] Step 2: run `python3 -m pytest -q -p no:cacheprovider tests/test_glide.py`. Expected: FAIL (module missing).
- [ ] Step 3: port `render` and `load_depth`, then add `cmd_glide` to the CLI. Write to an ffmpeg pipe, libx264 crf 15, yuv420p, `-r 24`.
- [ ] Step 4: run the same command. Expected: PASS.
- [ ] Step 5: mirror, then commit `eav: layered depth glide (24 fps, ease modes, flat, sweep, drain)`.

### Task 3: Pause re-timing (`eav/retime.py`, `eav retime`)

**Files:**
- Create: `skills/earnalism-audiovisual/software/eav/retime.py`
- Modify: `cli.py`, adding the `retime` subcommand
- Test: `tests/test_retime.py`

**Interfaces:**
- Produces:
  - `plan_pauses(text: str, pauses: list[tuple[float, float]], rng_seed: int) -> list[tuple[float, float, float]]`. It maps detected pauses, in order, to the punctuation in `text` and returns (start, end, target_s) using the Global Constraints ranges with ±15% jitter. A pause with no matching punctuation keeps its length.
  - `retime(src: Path, dst: Path, plan: list[tuple[float, float, float]], cuts: list[float]) -> dict`, returning `{"cuts": [...new...], "duration": float}`.
  - `room_tone(x: np.ndarray, n: int) -> np.ndarray`. It loops the quietest 0.25 s of the take with 30 ms crossfades, level-matched to −62…−68 dBFS.
  - `detect_pauses(path: Path, threshold_db: float = -38, min_s: float = 0.18) -> list[tuple[float, float]]`
- Joins use a 30–50 ms equal-power crossfade, so there are no sample steps over −50 dBFS.

- [ ] Step 1: write the failing tests. Build a synthetic take with `tests/_media.py`: 220 Hz "speech" bursts separated by 0.2 s and 0.5 s gaps.
  - `test_room_tone_never_digital_zero`: the output's minimum 20 ms RMS is above −80 dBFS, and no run of zero samples is longer than 50 ms.
  - `test_targets_follow_punctuation`: for the text "এক, দুই। তিন!" with 3 pauses, the targets fall in [0.34, 0.63], [0.68, 1.15] and [1.19, 1.84] (the ±15% bands).
  - `test_cut_mapping_moves_with_inserted_time`: a cut at the middle of pause 2 lands at the middle of the new pause 2 (±10 ms).
  - `test_retime_no_pauses_is_identity`: with an empty plan, the output duration equals the input ±1 ms (Review Focus 3).
  - `test_no_click_at_joins`: the largest sample-to-sample step at each join is under −50 dBFS.
- [ ] Step 2: run the tests. Expected: FAIL.
- [ ] Step 3: implement, porting the spike's `retime.py` with an added `plan_pauses` and crossfades.
- [ ] Step 4: run the tests. Expected: PASS.
- [ ] Step 5: mirror, then commit `eav: pause re-timing by punctuation with room tone`.

### Task 4: Voice redo gate (`eav/voicecheck.py`, `eav voicecheck`)

**Files:**
- Create: `eav/voicecheck.py`
- Modify: `cli.py`, adding the `voicecheck` subcommand that writes `voicecheck.json` per take
- Test: `tests/test_voicecheck.py`

**Interfaces:**
- Produces:
  - `profile(takes: list[Path]) -> dict`, the book's running medians: median pitch, rate, brightness, spectral-jump rate, click rate.
  - `check(take: Path, expected_s: float, prof: dict, prev_tail: Path | None = None) -> dict`, returning `{"pass": bool, "failures": [str, ...], "metrics": {...}}`.
- Failure codes and thresholds (from the spec, sections 4 and 9):

  | Code | Fails when |
  |---|---|
  | `duration` | outside ±12% of expected |
  | `pitch_median` | more than ±1.5 semitones from the profile |
  | `pitch_spread` | under 3.0 semitones |
  | `monotone` | 2-s windows with spread under 1.5 semitones make up more than 20% of the take |
  | `no_breath` | a run over 9 s without a pause ≥ 0.15 s |
  | `tail` | last 50 ms above −50 dBFS |
  | `brightness` | more than ±2 dB from the profile |
  | `jumps` | spectral-jump rate more than 1.5× the profile |
  | `clicks` | more than 0.2 per s of speech |
  | `digital_zero` | a zero run over 50 ms |
  | `join` | against `prev_tail`: more than 1.5 LU or ±1.5 semitones |
  | `true_peak` | true peak at or above −0.1 dBFS |
- Use the numpy YIN pitch tracker from the 26 Nov voice review (`/tmp/claude-0/-home-user-reo-earnalism-maison/d619a5d1-fba8-5cb0-a0f4-7eaa7034c807/scratchpad/review/voice/analyze.py`); port only the functions needed.

- [ ] Step 1: write the failing tests on synthetic audio (sine glides for pitch, gaps for pauses).
  - `test_flat_tone_fails_pitch_spread_and_monotone`
  - `test_varied_glide_passes_pitch`
  - `test_abrupt_tail_fails_tail`: the take ends on a full-level sine.
  - `test_long_run_fails_no_breath`: 10 s with no gap.
  - `test_zero_gap_fails_digital_zero`
  - `test_duration_outside_12_percent_fails`
  - `test_clean_take_passes_all`
- [ ] Step 2: run the tests. Expected: FAIL.
- [ ] Step 3: implement `profile` and `check`.
- [ ] Step 4: run the tests. Expected: PASS.
- [ ] Step 5: mirror, then commit `eav: automatic narration redo gate`.

### Task 5: Paper edit and shot plan (`eav/shotplan.py`, `eav plan-shots`)

**Files:**
- Create: `eav/shotplan.py`
- Modify: `cli.py`, adding `plan-shots --film N --scene ID [--approve]`. It writes `film/film-NN/shots/<scene>.json` and `<scene>.av.md`.
- Test: `tests/test_shotplan.py`

**Interfaces:**
- Produces:
  - `beats(scene_text: str, timing: list[dict]) -> list[dict]`: clause groups with start and end times, split at punctuation-aligned pauses.
  - `plan(scene: dict, timing: list[dict], bible: dict) -> dict`, returning `{"scene_id", "spine", "shots": [{"n", "start", "end", "framing", "camera": {"move", "zoom", "pan_x", "ease"}, "motion": "wan|glide|static", "wan_res": "1280x704|896x512|null", "subject", "bible_refs": [...], "sound": {"vo", "sfx": [...], "music"}, "layer": "present|memory|imagined", "transition_in": "cut|dissolve|match"}], "peak": {"shot": n, "at": s}, "compute": {"stills": int, "wan_clips": int, "cu": float}}`.
  - `validate(shotplan: dict) -> list[str]`, returning violated rule codes:
    - R1: any span over 6 s without a new shot or a Wan beat;
    - R2: shots < ceil(seconds / 6), or a shot over 8 s without motion "wan", or over 12 s at all;
    - R3: no peak; a peak outside 70–85% of the scene; a peak shot under 4 s; or no planted shot before it (a `plants` reference);
    - R7/R8: soft warnings;
    - R11: `approved` missing on job build.
  - `av_markdown(shotplan) -> str`: the two-column AV script (time | audio | visual).
- `job film_clips` and `job stills` refuse a scene whose `shots/<scene>.json` lacks `"approved": {"by": ..., "at": ..., "reviewer": ...}` (Claude plus an independent reviewer, owner decision 3).

- [ ] Step 1: write the failing tests, using the scene-14 text and v4 timing from `production/audiovisual/bicharak` as a fixture copied into `tests/fixtures/scene14.json`.
  - `test_shot_count_at_least_seconds_over_6`
  - `test_validate_flags_r1_gap`: a hand-built plan with a 7 s glide-only shot.
  - `test_validate_flags_r3_peak_without_plant`
  - `test_av_markdown_has_two_columns_per_shot`
  - `test_job_refuses_unapproved_scene`
- [ ] Step 2: run the tests. Expected: FAIL.
- [ ] Step 3: implement. The shot subject and framing come from the planner's input file, written by Claude and the reviewer. The code only validates and lays out; it does not invent content.
- [ ] Step 4: run the tests. Expected: PASS.
- [ ] Step 5: mirror, then commit `eav: paper edit (two-column AV script) and shot rules R1-R3, R11`.

### Task 6: `film_clips` job kind (Wan beats and depth maps in Colab)

**Files:**
- Modify: `eav/colab_jobs.py`, adding `"film_clips"` to `KINDS`, the item validation and the forecast.
- Create: `eav/templates/film_clips_cell.py.txt`, from the spike's `WAN_CELL` plus the depth cell (see `build3.py`).
- Modify: `production/audiovisual/rates.json`, adding `film_clips`: `clip_s_hd` 900 (L4) / 215 (A100), `clip_s_sd` 435, `units_per_hour_l4` 2.4, `units_per_hour_a100` 4.5, `source` "MEASURED 26–27 Nov pilots".
- Test: `tests/test_colab_jobs.py`

**Interfaces:**
- Consumes: the Task 5 shot plan (`motion == "wan"` shots, `wan_res`).
- Produces: the job item shape `{"key", "image", "width", "height", "seed", "prompt", "continue_from": key|None}`. Outputs per key: `<key>.mp4` (quality=10), `<key>.last.png`, `<key>.last-depth.png`. Per still: `<image-stem>.depth.png`, 16-bit.
- The template keeps, from the spike:
  - the licence allowlist check for both repos;
  - `MIN_VRAM_GIB` 21;
  - `may_start` with per-resolution time estimates;
  - near-lossless export;
  - the negative prompt list from the spec, section 3;
  - a journal `done.json` in the Drive folder. A rerun skips keys whose mp4 sha is recorded (Review Focus 5).

- [ ] Step 1: write the failing tests.
  - `test_film_clips_kind_builds_valid_notebook`: every code cell parses with `ast`.
  - `test_film_clips_forecast_uses_measured_rates`: 4 HD clips at L4 rates → (4·900·1.15 + setup) / 3600 · 2.4.
  - `test_film_clips_resume_skips_finished_keys`: exec the journal helper with a fake `done.json` and the keys list, and get only the missing keys back.
  - `test_film_clips_negative_prompt_lists_hand_and_eye_terms`
  - `test_film_clips_refuses_depth_base_or_large`
- [ ] Step 2: run the tests. Expected: FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: run the tests. Expected: PASS.
- [ ] Step 5: mirror, then commit `eav: film_clips job kind (Wan beats, depth maps, resume journal)`.

### Task 7: Scene cue and film mix (`eav/cue.py`, `eav cue`)

**Files:**
- Create: `eav/cue.py`, ported from `mix3.py`.
- Modify: `cli.py`, adding `cue --scene ID --stems <music job> --drone K --solo K --phrase K`, and `cue --pick` (measurement-based choice).
- Test: `tests/test_cue.py`

**Interfaces:**
- Produces:
  - `pick_stems(stems_dir: Path, tonic: str) -> dict` returns `{"drone": key, "solo": key, "phrase": key}`. It prefers the stated tonic in the chroma top-2, the lowest onset rate, the lowest pulse autocorrelation and the least energy below 120 Hz.
  - `scene_mix(voice: Path, cuts: list[float], peak_at: float, stems: dict, ambience: list[dict], foley: list[dict], out: Path, total: float) -> dict` returns `{"voice_over_music_db": float, "lufs": float, "true_peak": float}`.
- Values from the spec:
  - high-pass the music at 90 Hz (two 2-pole stages);
  - 0.4 s of music silence at `peak_at`;
  - stereo output;
  - −16 LUFS, true peak ≤ −1.5 dBTP;
  - voice-over-music in speech 16–18 dB, achieved by RMS-normalising the stems to −22/−19/−20 dBFS before ducking.

- [ ] Step 1: write the failing tests with synthetic stems (sine drone at D, plucked-noise solo, chord phrase).
  - `test_pick_prefers_tonic_and_low_pulse`
  - `test_music_silent_at_peak`: the RMS of the music-only bus over [peak, peak+0.4] is below −80 dBFS.
  - `test_peak_silence_at_scene_end_is_clipped` (Review Focus 4)
  - `test_voice_over_music_in_range_16_to_18`
  - `test_output_is_stereo_and_meets_loudness`: −16 ±1 LUFS, TP ≤ −1.5.
- [ ] Step 2: run the tests. Expected: FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: run the tests. Expected: PASS.
- [ ] Step 5: mirror, then commit `eav: per-scene cue from stems with peak silence and smooth ducking`.

### Task 8: Shot-based film assembly, captions and cards (`eav/film.py`)

**Files:**
- Modify: `eav/film.py`, adding `assemble_shots`, `captions` and `cards`. Keep `assemble` for old films.
- Modify: `cli.py`, so `cmd_film` gains `--shots`. That makes it read `shots/<scene>.json` for every scene, render each shot through glide or Wan and cache by hash.
- Test: `tests/test_film.py`

**Interfaces:**
- Consumes: Task 2 `glide.render`, Task 5 shot plans, Task 6 clips, Task 7 `scene_mix`.
- Produces:
  - `render_shot(shot: dict, assets: dict, cache_dir: Path) -> Path`. The cache key is sha256 of (shot json, input file hashes, code version).
  - `assemble_shots(shot_clips: list[Path], lens: list[float], transitions: list[float], audio: Path, out: Path, fps: int = 24) -> dict`. Lengths are rounded to whole frames; a 1-frame xfade means a hard cut.
  - `captions(timing: list[dict], units: list[dict], lang: str) -> str`: WebVTT cues of at most 2 lines and 42 characters per line, 1–7 s, at most 15 characters per second for `bn`. Splits happen only at spaces or punctuation.
  - `cards(title: str, author: str, voice: str, out_dir: Path) -> dict`: a title card PNG ("বিচারক — রবীন্দ্রনাথ ঠাকুর") and a credits PNG with the author, narration voice, and "Illustrations and narration are AI-generated / ছবি ও কণ্ঠ এআই-নির্মিত", in Maison fonts. The approved logo lockup and END follow.
  - Captions are muxed as a `mov_text` track; `--burn` gives a burned-in rendition.

- [ ] Step 1: write the failing tests.
  - `test_assemble_shots_frame_exact_lengths`: three 1-s test clips with a 0.5-s dissolve and a hard cut; the total frame count equals the sum minus the overlaps.
  - `test_caption_cue_limits`: no cue has more than 2 lines or 42 characters per line; durations are 1–7 s; characters per second ≤ 15 for bn.
  - `test_caption_wrap_keeps_bengali_graphemes`: Review Focus 1; every line passes a check that it never ends with ্ (hasanta) and starts with no dependent vowel sign.
  - `test_render_shot_cache_hit_skips_render`
  - `test_cards_contain_ai_disclosure_text`: checks the cards metadata JSON.
- [ ] Step 2: run the tests. Expected: FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: run the tests. Expected: PASS.
- [ ] Step 5: mirror, then commit `eav: shot-based 24 fps film assembly, captions track, title and credit cards`.

### Task 9: QC gates for edit, audio and safety (`eav/qc.py`)

**Files:**
- Modify: `eav/qc.py` and `cli.py cmd_qc`, which writes the gates into the existing qc report items.
- Test: `tests/test_qc.py`

**Interfaces:**
- Produces:
  - `new_info_gaps(video: Path, threshold: float) -> list[tuple[float, float]]`: R1, spans over 6 s whose content similarity stays above the threshold after zoom-compensated alignment (ORB/ECC).
  - `hold_hashes(shot_plan_dir: Path) -> list[str]`: scenes whose stills share a file hash.
  - `black_bars(video) -> list[float]`
  - `frame_hitches(video) -> list[float]`: a single-frame luma step more than 2× the neighbouring steps inside a dissolve.
  - `flashes(video) -> dict`: R10, at most 3 per second, with luminance jumps over 25% only at planned cuts.
  - `audio_gates(mix: Path, voice: Path) -> dict`: voice-over-music margin, any digital zero over 50 ms, loudness and true peak.

- [ ] Step 1: write the failing tests on synthetic videos: a static 7-s still; a still with black rows; a flashing clip; a dissolve with a 1-frame jump.
  - `test_static_7s_flags_r1`
  - `test_black_rows_flagged`
  - `test_flash_over_3_per_s_flagged`
  - `test_hitch_in_dissolve_flagged`
  - `test_digital_zero_flagged`
- [ ] Step 2: run the tests. Expected: FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: run the tests. Expected: PASS.
- [ ] Step 5: mirror, then commit `eav: QC gates R1, R5, R10, holds, black bars, hitches, audio`.

### Task 10: Audiobook master, chapters and sentence timing (`eav/mix.py`, `bundle-audio`)

**Files:**
- Modify: `eav/mix.py`, adding `master_audiobook`.
- Modify: `cli.py cmd_bundle_audio`, adding `--profile audiobook` (the default for new bundles), chapter markers and sentence timing.
- Create: `docs/interface-notes/2026-11-27-audio-bundle-sentences-chapters.md`, the note to root and the backend lane about the bundle contract change (no code in their lanes).
- Test: `tests/test_mix.py`, `tests/test_cli.py`

**Interfaces:**
- Produces:
  - `master_audiobook(narration: Path, cues: dict, out: Path) -> dict`: −18 LUFS ±1, TP ≤ −2 dBTP after a mono 64 kbps encode (measured on the encoded file), LRA 4–8 LU.
    - Music only for the intro, outro and part changes; any bed sits at least 24 LU under the voice with a 6 dB duck and 1.5 s release.
    - Opens with the title and author units; ends with 3 s of tail, "সমাপ্ত" and room tone.
  - The bundle gains:
    - `chapters`: `[{"title": "প্রথম পরিচ্ছেদ", "start_ms"}, ...]`;
    - `sentences`: `[{"anchor_id", "sentence_index", "start_ms", "end_ms"}]`, from the per-passage timing (passage boundaries plus pauses mapped to sentence ends).

- [ ] Step 1: write the failing tests.
  - `test_audiobook_master_meets_targets_after_encode`
  - `test_bed_at_least_24lu_under_voice`
  - `test_bundle_has_chapters_and_sentence_timing`
  - `test_no_score_pumping_in_pauses`: the bed level in pauses is within 3 dB of its level under speech.
- [ ] Step 2: run the tests. Expected: FAIL.
- [ ] Step 3: implement, and write the interface note.
- [ ] Step 4: run the tests. Expected: PASS.
- [ ] Step 5: mirror, then commit `eav: audiobook master, chapter markers, sentence timing (interface note to root)`.

### Task 11: Character and period gate for stills (Colab) plus the CC0 sound fetch

**Files:**
- Modify: `eav/templates/stills_cell.py.txt`, adding a gate cell after the stills. It runs MediaPipe Face Landmarker, MediaPipe Hand Landmarker, OWLv2 (labels: "gas cylinder", "air conditioner", "electric cable", "spotlight", "modern eyeglasses", "plastic") and CLIP similarity to the anchor still. Each licence is checked against the allowlist at run time. It writes `<key>.gate.json`.
- Modify: `eav/cli.py cmd_pick`, which refuses a candidate whose gate failed unless `--override "<reason>"` is given (recorded).
- Create: `eav/templates/sfx_cell.py.txt`. This is an optional cell for `film_clips` jobs that searches Wikimedia Commons (no key needed), keeps only CC0 or public-domain files (licence read per file), and writes `sfx/<name>.<ext>` plus `sfx/licences.json` (title, page URL, licence, author).
- Test: `tests/test_colab_jobs.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `gate.json` = `{"eyes": int, "hands_detached": bool, "anachronisms": [label...], "anchor_similarity": float, "pass": bool, "needs_review": bool}`. An unclear model result sets `needs_review`, never `pass`.

- [ ] Step 1: write the failing tests.
  - `test_stills_notebook_has_gate_cell_and_allowlist`
  - `test_pick_refuses_failed_gate_without_override`
  - `test_sfx_cell_keeps_only_cc0_or_pd`: exec the filter function on sample metadata.
- [ ] Step 2: run the tests. Expected: FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: run the tests. Expected: PASS.
- [ ] Step 5: mirror, then commit `eav: still gates (eyes, hands, anachronisms, character lock) and CC0 sound fetch`.

### Task 12: Skill text, references and pressure tests

**Files:**
- Modify: `skills/earnalism-audiovisual/SKILL.md`, setting the stage flow to: plan-shots → stills+gates → film_clips → voice (v4 passages, retime, voicecheck) → cue → film --shots → qc → owner review.
- Rewrite: `references/film-recipe.md`, covering the spec's rules R1–R11, the grammar, the layers and the reference scene.
- Rewrite: `references/earnalism-voice.md`, covering v4, passages, tags, pauses and the redo gate. Keep the 24 Nov owner decision text.
- Modify: `references/free-stack.md`, adding Wan film profile rates, depth (Small only), MediaPipe, OWLv2, CLIP, and Whisper MIT.
- Modify: `references/compute-budget.md`, adding per-title caps, measured rates and the per-film forecast (about 25–34 CU on A100).
- Modify: `references/production-record.md` and `references/model-licences.md`.
- Modify: `references/pressure-tests.md`, adding three scenarios with expected agent behaviour:
  - a "hold" request → regenerate, not hold;
  - a 9 s glide-only shot → split;
  - music borrowed from another scene → refuse.
- Test: `tests/test_skill_files.py`

- [ ] Step 1: write the failing tests.
  - `test_film_recipe_states_rules_r1_to_r11`
  - `test_voice_reference_names_v4_and_redo_gate`
  - `test_free_stack_excludes_depth_base_large`
  - `test_skill_md_stage_order`
- [ ] Step 2: run the tests. Expected: FAIL.
- [ ] Step 3: edit the text.
- [ ] Step 4: run the full suite, `python3 -m pytest -q -p no:cacheprovider tests`. Expected: all pass, the mirror included.
- [ ] Step 5: commit `earnalism-audiovisual: skill text and references for the cinematic standard`.

## Gap tasks added 27 Nov (spec §3 and §4 requirements no earlier task built)

The Task 12 review found three spec requirements with no code: Eleven v4 passage import, the Whisper word check and the per-clip motion gate. AGENTS.md says to "fix gaps toward that baseline", so they are added here and must be done before the final review.

### Task 13: Eleven v4 passages, imported and joined (`import-take`, `eav/passages.py`)

**Files:**
- Modify: `cli.py`.
  - `import-take` accepts the owner-chosen v4 model id, read from the title's voice settings, alongside `eleven_v3`.
  - It accepts per-passage takes `<scene>-p<NN>.txt` and `.mp3` for one scene.
- Create: `eav/passages.py`: `split_passages(scene_text) -> list[str]` and `join_passages(takes: list[Path], out: Path) -> dict`.
- Test: `tests/test_passages.py` and `tests/test_cli.py`.

**Interfaces:**
- Produces: `film/film-NN/voice/<scene>.wav`, the path `cue` already reads.
- Each passage runs `retime` then `voicecheck`. A failed passage is listed for redo, never joined.

- [ ] Step 1: write the failing tests.
  - `test_split_passages_15_to_30s_at_sentence_or_paragraph_ends`: estimate length with the measured characters-per-second.
  - `test_passages_reproduce_scene_text_exactly`: joining the passages gives the source text back.
  - `test_import_take_accepts_v4_per_passage_takes`
  - `test_failed_passage_blocks_the_join`
  - `test_join_uses_room_tone_and_10ms_crossfade_no_digital_zero`
- [ ] Step 2: run the tests. Expected: FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: run the tests. Expected: PASS.
- [ ] Step 5: mirror, then commit `eav: Eleven v4 passages imported, checked and joined per scene`.

### Task 14: Whisper word check (`voicecheck` code `words`)

**Files:**
- Modify: `eav/voicecheck.py`.
- Create: `eav/templates/words_cell.py.txt`, a Colab cell for when a local CPU run is not possible.
- Test: `tests/test_voicecheck.py`.

**Interfaces:**
- `check(..., transcript: str | None, source: str | None)` adds the failure code `words` when the character error rate exceeds the book profile's accepted-take median plus a margin.
- The CER is computed on normalised Bengali text: NFC, punctuation stripped, whitespace collapsed.
- The Whisper model is the MIT-licensed `openai/whisper-*`. Its licence is checked at run time.

- [ ] Step 1: write the failing tests.
  - `test_cer_normalises_bengali_and_ignores_punctuation`
  - `test_words_fails_on_dropped_sentence`
  - `test_words_passes_on_match`
  - `test_no_transcript_means_check_not_run_not_pass`
- [ ] Steps 2–4: RED, then implement, then GREEN.
- [ ] Step 5: mirror, then commit `eav: Whisper word check in the narration redo gate`.

### Task 15: Per-clip motion gate (`eav/motiongate.py`, run on `film_clips` import)

**Files:**
- Create: `eav/motiongate.py`: `check_clip(mp4) -> {"near_duplicate_runs", "diff_spikes", "contact_sheet", "pass", "needs_review"}`.
- Modify: `eav/importer.py` so the `film_clips` import writes `<key>.motion.json` and a contact sheet of every 4th frame.
- Modify: `cli.py`: `film --shots` refuses a Wan take whose motion gate failed, unless a recorded override exists. This follows the Task 11 override pattern.
- Test: `tests/test_motiongate.py`.

- [ ] Step 1: write the failing tests on synthetic clips.
  - `test_periodic_near_duplicate_frames_flagged`: a clip that repeats frames.
  - `test_difference_spike_flagged`: a one-frame jump.
  - `test_smooth_clip_passes`
  - `test_contact_sheet_every_4_frames`
  - `test_film_refuses_failed_take_without_override`
- [ ] Steps 2–4: RED, then implement, then GREEN.
- [ ] Step 5: mirror, then commit `eav: per-clip motion gate on film_clips import`.

## After the plan (not code tasks)

- Build scene 14 v4 with the new commands as the acceptance test. Get the owner's approval, then re-render বিচারক (December, A100 preferred), then The Selfish Giant.
- The Read/Listen UX (spec sections 9–10) is a separate plan for the frontend and backend lanes. The owner approved it on 27 Nov.
