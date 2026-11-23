# earnalism-audiovisual Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single `earnalism-audiovisual` skill that takes a cleared English or Bengali title to a reviewed package: a full-length audiobook film, one or two Squint-grade reels, and the evidence needed to publish them.

**Architecture:**
- **Entry point:** a new skill folder, `skills/earnalism-audiovisual/`, mirrored in `.agents/skills/`, conducts the six existing stage skills.
- **Pure-Python helpers (`software/eav/`):**
  - planning: scenes, reel shots, voice units;
  - the compute budget;
  - Colab job bundles that the owner runs;
  - importing outputs;
  - ffmpeg assembly and QC;
  - the production record.
- **Maison:** one server command attaches cleared audio to a draft revision through the existing asset, timing-map and validation services.

**Tech Stack:** Python 3.13 standard library, NumPy and Pillow, ffmpeg/ffprobe, unittest, and Django (Maison command only). Colab generators: Indic Parler-TTS, FLUX.1-schnell, ACE-Step and Wan 2.2 TI2V-5B (the existing `wan22` builder).

**Spec:** `docs/superpowers/specs/2026-11-23-earnalism-audiovisual-design.md`

## Global Constraints

- **Spend.** No paid generator, connector or credit-spending tool. Generators must be open-weight and commercial-use: Indic Parler-TTS, FLUX.1-schnell, Wan 2.x and ACE-Step (all Apache-2.0); VCSL (CC0). MusicGen and FLUX.1-dev are forbidden.
- **Compute allowance:** ≤ 60 Colab compute units per title and ≤ 100 per calendar month. Forecast = measured s/step × steps + decode + export, + 15% margin. Over a cap: cut reel takes, then reel shots, otherwise hold. Never retry past a cap.
- **Colab runs.** The owner runs every Colab job. Bundles are inert until an explicit `RUN = True` cell is set, and outputs return through a Drive folder and are hash-verified on import.
- **Voice:**
  - Pinned Parler descriptions (`en_tisha::story`, `bn_arnav::story` and the other roster routes) are used byte-for-byte. Only one optional appended clause of ≤ 12 words is allowed.
  - Spoken text equals the source text exactly. No unit may be dropped or duplicated.
- **Film:**
  - Text: the full text, unchanged.
  - Scenes: 30–90 s each; one keyframe still per 8–15 s of narration.
  - Motion: done in the container (push-in or parallax with cross-dissolves); no Wan.
  - Audio: −16 LUFS integrated, true peak ≤ −1 dBTP; score ducked 18–20 dB under speech.
  - Captions: SRT subtitles.
  - Length: narration over 40 min becomes a chapter-by-chapter series.
- **Reels:**
  - Format: 1080×1920.
  - Length: 60 s (100–125 words) or 120 s (200–245 words).
  - Hook: ≤ 8 words, spoken from 0.0–0.2 s.
  - Shots: 5–7.5 s each.
  - Motion: Wan `l4-balanced-v2` (512×896, 24 steps), upscaled with lanczos; the hook shot may use 704×1280 when the forecast fits.
  - Loop: closes via a match-cut or dissolve into frame 1.
  - Text: the only on-screen text is "AI-generated visuals" for the first 3 s.
  - Audio: −14 LUFS, true peak ≤ −1 dBTP.
- **Maison:**
  - Audio via R2 is allowed: chapter MP3 plus a measured timing map.
  - Maison video (Stream) is held until the owner confirms hosting cost.
  - Access defaults to `free`.
- **Clearance:**
  - A per-title evidence record extends the public-domain clearance pattern to audio/video.
  - Non-public-domain titles are refused.
- **Captions:** social captions are the hook line + emoji, then the script, then ~5 hashtags, always including `#earnalism #learnalism #theearnalism`.
- **Tests:** run with `python3 -m unittest discover -s skills/earnalism-audiovisual/software/tests -t skills/earnalism-audiovisual/software`. Maison tests run on PostgreSQL via `manage.py test`.

## Review Focus

1. **Bengali text.** Sentences end with `।`, and words are counted by whitespace. Sentence splitting and timing estimates must handle `।`, `?`, `!` and `—` without merging or splitting words (Task 2).
2. **Oversized paragraphs.** One paragraph longer than 90 s of narration must split at sentence boundaries into several scenes, never mid-sentence. A single sentence over 90 s stays one scene, flagged (Task 2).
3. **Colab return folder.** A missing, extra or hash-mismatched file must stop the import and change nothing in the record (Task 5).
4. **Allowance ledger.** Spend from a previous month must not count against this month. Two batches forecast together must not jointly exceed the cap (Task 3).
5. **Narration gaps.** Film assembly with a missing or duplicate narration unit must refuse rather than produce a shorter film (Task 6).

---

### Task 1: Production record

**Files:**
- Create: `skills/earnalism-audiovisual/software/eav/__init__.py`, `eav/record.py`
- Test: `skills/earnalism-audiovisual/software/tests/test_record.py`

**Interfaces:**
- Produces:
  - `Record.create(root: Path, title_slug: str, source: dict) -> Record` writes `root/record.json`.
  - `Record.load(root) -> Record`.
  - `record.add_artifact(kind: str, path: Path, meta: dict) -> dict` returns `{kind, path, sha256, bytes, meta}`.
  - `record.event(stage: str, result: str, detail: dict)`.
  - `record.data: dict`.
  - `sha256_file(path) -> str`.
- Schema: `"earnalism.audiovisual_record.v1"`.

- [ ] **Step 1: Write failing tests.**
  - `test_create_then_load_roundtrip`: equal `data`, schema string, and `source.content_sha256` preserved.
  - `test_add_artifact_hashes_bytes`: the sha matches `hashlib.sha256(file)`.
  - `test_add_artifact_rejects_path_outside_root`: raises `ValueError`.
  - `test_events_append_only`: two events in order, each with an ISO timestamp.
- [ ] **Step 2: Run.** Expected: FAIL with `ModuleNotFoundError: eav`.
- [ ] **Step 3: Implement** `eav/record.py`. Write JSON atomically: write a tmp file, then `os.replace`.
- [ ] **Step 4: Run.** Expected: 4 passed.
- [ ] **Step 5: Commit** with the message `eav: production record`.

### Task 2: Source → film scenes and voice units

**Files:**
- Create: `eav/text.py`, `eav/scenes.py`, `eav/voice.py`
- Test: `tests/test_scenes.py`, `tests/test_voice.py`

**Interfaces:**
- Consumes: the source JSON produced by Task 8: `{"language": "en"|"bn", "units": [{"unit_id", "title", "paragraphs": [{"anchor_id", "kind", "text"}]}]}`.
- Produces:
  - `sentences(text: str, language: str) -> list[str]` (splits after `.?!।` and keeps the punctuation).
  - `words(text) -> int`.
  - `estimate_seconds(text, language, wpm=120) -> float`.
  - `plan_film(source: dict, wpm=120) -> dict` returns `{"series": bool, "films": [{"unit_ids", "scenes": [{"scene_id", "anchor_ids", "text", "seconds", "keyframes": int, "flag": str|None}]}]}`.
  - `voice_units(scene: dict, preset: dict, clause: str|None) -> list[{"unit_key", "text", "description", "pause_after_ms"}]`.
- Scenes target 30–90 s. The number of keyframes is the smallest k with seconds/k ≤ 15, but at least ceil(seconds/15) and at least 1. If total narration is over 40 min (2400 s), set `series=True` with one film per source unit.
- `description` is `preset["description"]`, or `preset["description"] + " " + clause` when a clause is given. A clause longer than 12 words raises `ValueError`.
- Pauses: 400 ms between sentences and 800 ms at a paragraph end. Heading paragraphs get 1200 ms.

- [ ] **Step 1: Write failing tests.**
  - `test_bengali_danda_split`: `sentences("সে এল। তারপর গেল। কেন?", "bn") == ["সে এল।","তারপর গেল।","কেন?"]`.
  - `test_scenes_within_bounds`: a 32-paragraph English fixture gives every scene `30 <= seconds <= 90`, except a flagged last scene, and every `anchor_id` appears exactly once and in order.
  - `test_oversized_paragraph_splits_on_sentences`: a 400-word paragraph gives ≥ 2 scenes whose concatenated text equals the paragraph.
  - `test_single_huge_sentence_flagged`: a single sentence of 250 words gives one scene with `flag == "over_90s_sentence"`.
  - `test_long_book_becomes_series`: 2 units of 3,000 words each give `series is True` and 2 films.
  - `test_voice_description_is_preset_byte_for_byte`: with no clause, `description == preset["description"]`.
  - `test_clause_over_12_words_rejected`.
  - `test_voice_units_cover_text_exactly`: joining unit texts with single spaces reproduces the scene text, whitespace-normalised.
- [ ] **Step 2: Run.** Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the three modules with these signatures. Scenes are greedy: accumulate sentences until adding one would exceed 90 s, and close at ≥ 30 s on a paragraph boundary where possible.
- [ ] **Step 4: Run.** Expected: 8 passed.
- [ ] **Step 5: Commit** with the message `eav: film scenes and Earnalism Voice units`.

### Task 3: Compute budget and allowance ledger

**Files:**
- Create: `eav/budget.py`
- Test: `tests/test_budget.py`

**Interfaces:**
- Produces:
  - `forecast(job: dict, rates: dict) -> float`: the compute units. The `job` has `{"kind", "steps", "items", "takes", "decode_s", "export_s"}`, and `rates` has `{"<kind>": {"s_per_step": float, "units_per_hour": float}}`.
  - `Ledger(path: Path)` with:
    - `spent(title: str|None, month: "YYYY-MM") -> float`;
    - `reserve(title, month, units, job_id) -> None`, which raises `BudgetExceeded` when spend would pass 60 per title or 100 per month;
    - `settle(job_id, actual_units)`.
  - `fit_reel_job(job, rates, remaining_units) -> dict|None` cuts `takes` down to 1 first, then `items`, while `items >= 8`. It returns `None` when the job still doesn't fit.
- Margin: forecast seconds = (steps × s_per_step × items × takes + decode_s + export_s) × 1.15.

- [ ] **Step 1: Write failing tests.**
  - `test_forecast_includes_15_percent_margin`.
  - `test_title_cap_60`: a reserve of 61 raises.
  - `test_month_cap_100_across_titles`: reserves of 55 for title A and 50 for title B in the same month raise on B.
  - `test_previous_month_not_counted`: 90 units in `2026-10` leave `2026-11` with 100.
  - `test_two_reservations_cannot_jointly_exceed`.
  - `test_fit_cuts_takes_before_shots`.
  - `test_fit_returns_none_below_8_shots`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** The ledger is a JSON file written atomically. Reservations count as spent until they are settled.
- [ ] **Step 4: Run.** Expected: 7 passed.
- [ ] **Step 5: Commit** with the message `eav: compute forecast and standing allowance ledger`.

### Task 4: Colab job bundles (narration, stills, music, reel clips)

**Files:**
- Create: `eav/colab_jobs.py`, `eav/templates/narration_cell.py.txt`, `eav/templates/stills_cell.py.txt`, `eav/templates/music_cell.py.txt`
- Test: `tests/test_colab_jobs.py`

**Interfaces:**
- Consumes:
  - `voice_units` (Task 2);
  - `Ledger`, `forecast`, `fit_reel_job` (Task 3);
  - the existing `earnalism-video/software/wan22/build_batch_colab.py` for reel clips. Import it and do not copy it.
- Produces: `build_job(kind: "narration"|"stills"|"music"|"reel_clips", record: Record, spec: dict, ledger: Ledger, rates: dict, out: Path) -> dict`. The result is `{"job_id", "notebook", "inputs_zip", "manifest", "forecast_units"}`.
- Each notebook:
  - pins its model repository and revision;
  - starts with a cell `RUN = False` and refuses to run otherwise;
  - verifies the input zip sha256 before running;
  - writes outputs plus a `manifest.json` of the sha256 of every output to `/content/drive/MyDrive/earnalism-audiovisual/<title>/<job_id>/`.
- Pinned models:
  - narration: `ai4bharat/indic-parler-tts` @ `7b527af5ee8ed1f9a28d80b19703ed9bb8ba10ca`;
  - stills: `black-forest-labs/FLUX.1-schnell` with 4 steps;
  - music: ACE-Step with its revision pinned at build time, recorded in the manifest;
  - reel clips: delegate to the wan22 batch builder with `profile="l4-balanced-v2"`.
- Reserve the forecast on the ledger before writing the bundle. `BudgetExceeded` propagates, and no files are written.

- [ ] **Step 1: Write failing tests.**
  - `test_notebook_is_inert_by_default`: the first code cell contains `RUN = False`.
  - `test_bundle_hash_checked_in_notebook`: the notebook source contains the input zip's sha256.
  - `test_narration_job_uses_pinned_revision_and_preset_description`.
  - `test_forbidden_models_rejected`: a spec naming `facebook/musicgen-small` or `FLUX.1-dev` raises `ValueError`.
  - `test_over_budget_writes_nothing`: the output dir stays empty and the ledger is unchanged.
  - `test_reel_clips_delegates_to_wan22_builder`: patch the builder and assert it was called with `profile="l4-balanced-v2"`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Build each notebook as nbformat-4 JSON with the standard library only.
- [ ] **Step 4: Run.** Expected: 6 passed.
- [ ] **Step 5: Commit** with the message `eav: inert hash-bound Colab job bundles`.

### Task 5: Import Colab outputs

**Files:**
- Create: `eav/importer.py`
- Test: `tests/test_importer.py`

**Interfaces:**
- Consumes: `Record`, plus the job manifest from Task 4.
- Produces: `import_job(record: Record, job: dict, downloaded_dir: Path, ledger: Ledger, actual_units: float) -> list[dict]` returns the artifacts it added.
- It verifies that the set of files equals the manifest, then copies the files under `record.root/<kind>/<job_id>/`. It adds artifacts and calls `ledger.settle(job_id, actual_units)`. Any mismatch raises `ImportHeld(reason)`, and nothing is copied or recorded.

- [ ] **Step 1: Write failing tests.**
  - `test_clean_import_adds_artifacts_and_settles`.
  - `test_missing_file_holds_and_changes_nothing`.
  - `test_extra_file_holds`.
  - `test_hash_mismatch_holds`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: 4 passed.
- [ ] **Step 5: Commit** with the message `eav: verified import of Colab outputs`.

### Task 6: Mix and film assembly

**Files:**
- Create: `eav/mix.py`, `eav/film.py`
- Test: `tests/test_mix.py`, `tests/test_film.py` (with synthetic fixtures generated by ffmpeg in `setUp`: sine "speech", noise "score" and solid-colour stills)

**Interfaces:**
- Consumes: the film plan (Task 2), narration WAVs and stills imported in Task 5, and a score WAV. The score comes from the existing `earnalism-video/software/editorial_score.compose` (pass `speech_intervals`), or from ACE-Step cues concatenated by `mix.arrange_cues`.
- Produces:
  - `mix.measure(path) -> {"lufs": float, "true_peak": float}`, using ffmpeg `ebur128=peak=true`.
  - `mix.duck_and_master(speech: Path, score: Path, out: Path, target_lufs: float, duck_db=19) -> dict`.
  - `mix.arrange_cues(cues: list[Path], boundaries_s: list[float], total_s: float, out: Path)`.
  - `film.narration_track(units: list[dict], wav_dir: Path, out: Path) -> list[{"unit_key", "start", "end"}]`. It raises `ValueError` if the WAV for any `unit_key` is missing or listed twice.
  - `film.subtitles(timing, units) -> str` produces SRT.
  - `film.assemble(plan, timing, stills_dir, mixed_audio, logo: Path, end_card: Path, out: Path, size=(1920,1080)) -> dict`.
- Film motion: each still gets a slow ffmpeg `zoompan` push of 1.00 → 1.06 over its duration. Neighbouring stills join with `xfade=fade:duration=0.8` placed on a narration boundary. The logo goes top-right per the earnalism-video brand rules, and the approved END card is appended once.

- [ ] **Step 1: Write failing tests.**
  - `test_master_hits_target_and_peak`: |lufs − (−16)| ≤ 1 and true_peak ≤ −1.0.
  - `test_score_ducked_under_speech`: score level during speech is ≥ 18 dB below its level in pauses (RMS by window).
  - `test_missing_unit_refuses`.
  - `test_duplicate_unit_refuses`.
  - `test_subtitles_cover_timing`: SRT cues are monotonic and the last end equals the narration duration ± 0.05 s.
  - `test_assemble_duration_matches_audio`: video duration equals audio duration ± 0.1 s, at 1920×1080.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** using ffmpeg subprocess calls only.
- [ ] **Step 4: Run.** Expected: 6 passed.
- [ ] **Step 5: Commit** with the message `eav: speech-ducked mastering and illustrated film assembly`.

### Task 7: Reel script, shots, assembly and loop QC

**Files:**
- Create: `eav/reel.py`, `eav/qc.py`
- Test: `tests/test_reel.py`, `tests/test_qc.py`

**Interfaces:**
- Consumes: `words`, `sentences` (Task 2), `mix.duck_and_master` (Task 6) and the Wan clips imported in Task 5.
- Produces:
  - `reel.validate_script(script: dict) -> None` checks a script shaped `{"length": 60|120, "language", "hook", "lines": [str], "loop_close"}`. It raises `ValueError` when the hook has more than 8 words, or the total words fall outside 100–125 (60 s) or 200–245 (120 s).
  - `reel.shot_list(script) -> list[{"shot", "line", "seconds"}]`, with each shot 5.0–7.5 s and totals summing to `length` ± 1 s.
  - `reel.assemble(clips: list[Path], audio: Path, out: Path, label_text="AI-generated visuals", loop_dissolve_s=0.5) -> dict`. Each clip is scaled to 1080×1920 with `lanczos` and `unsharp=5:5:0.6`. The label is drawn for t < 3.0 s in the lower-left safe area at y ≥ 0.72H and x ≤ 0.6W. The last clip's final 0.5 s dissolves into clip 1's first frame. Audio is mastered at −14 LUFS.
  - `qc.contact_sheet(video: Path, out: Path, every_s=1.0)`.
  - `qc.loop_score(video: Path) -> float`: SSIM between the last frame and the first frame, in [0, 1].
  - `reel.caption(script, hashtags: list[str]) -> str`: always contains `#earnalism #learnalism #theearnalism` and at most 5 hashtags in total.

- [ ] **Step 1: Write failing tests.**
  - `test_hook_over_8_words_rejected`.
  - `test_word_budget_60s`: 99 and 126 words are rejected; 110 passes.
  - `test_shot_lengths_in_range`.
  - `test_assembled_reel_is_1080x1920_and_minus14`: within ±1 LU.
  - `test_label_only_in_first_3s`: pixel difference with and without the label is nonzero at t = 1 s and zero at t = 4 s.
  - `test_loop_score_high_after_dissolve`: > 0.9 on a synthetic two-clip fixture.
  - `test_caption_hashtags`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: 7 passed.
- [ ] **Step 5: Commit** with the message `eav: Squint-grade reel script, assembly and loop QC`.

### Task 8: Maison commands for source export and cleared audio

**Files:**
- Create: `operations/management/commands/export_audiovisual_source.py`, `operations/management/commands/attach_audiovisual_audio.py`
- Test: `operations/test_audiovisual_commands.py`

**Interfaces:**
- Produces:
  - `manage.py export_audiovisual_source <edition-slug> --out <path>` writes the source JSON used in Task 2, plus `{"edition_id", "revision_id", "content_sha256", "rights": {fmt: [actions]}, "public_domain_evidence": bool}`, built from the live revision. It refuses if the edition has no live revision.
  - `manage.py attach_audiovisual_audio <edition-slug> --publisher <public_id> --bundle <dir> --evidence <repo-relative json>` performs these steps:
    1. clones the live revision with `library.services.clone_revision`;
    2. stores each chapter MP3 privately (`storage.put_private`) as an `audio_chapter` Asset bound to its Unit;
    3. creates a measured `TimingMap` per asset from the bundle's `timing.json`, so that `text_sha256 = revision content_sha256` and `asset_sha256` match;
    4. sets `access_policy["audio"] = "free"` and adds approved `audio` read rights for `settings.MAISON_PUBLICATION_TERRITORIES`;
    5. records `publication_clearance` with formats `["reader", "audio"]` and the evidence document's sha256;
    6. runs `transition_revision` with mark-ready, then publish;
    7. refuses video assets, with the message "Stream hosting held".

  Reuse the pattern and helpers of `publish_cleared_editions.py`.

- [ ] **Step 1: Write failing tests.** Use the `seed_local_pilot` fixture plus a 2-second MP3 generated with ffmpeg.
  - `test_export_refuses_without_live_revision`.
  - `test_export_shape_and_hash`: `content_sha256` equals `revision_hash(live)`.
  - `test_attach_audio_publishes_new_revision_with_timing_map`: the new revision is live, with an `audio_chapter` asset, and `validate_revision` passes `timing_map` and `publication_regions`.
  - `test_attach_refuses_video_files`.
  - `test_attach_refuses_without_evidence_file`.
- [ ] **Step 2: Run.** Use `manage.py test operations.test_audiovisual_commands` with `MAISON_TEST_DB_NAME=test_maison_av`. Expected: FAIL.
- [ ] **Step 3: Implement.** Read `library/timing.py` for `validated_segments` and build segments that pass it.
- [ ] **Step 4: Run.** Expected: 5 passed.
- [ ] **Step 5: Commit** with the message `maison: export audiovisual source; attach cleared audio`.

### Task 9: The skill text, references and orchestrator CLI

**Files:**
- Create:
  - `skills/earnalism-audiovisual/SKILL.md`
  - `references/earnalism-voice.md`
  - `references/film-recipe.md`
  - `references/reel-recipe.md`
  - `references/free-stack.md`
  - `references/compute-budget.md`
  - `references/production-record.md`
  - `references/publishing.md`
  - `software/eav/cli.py`
- Create mirror: the same files under `.agents/skills/earnalism-audiovisual/`, checked by a test.
- Modify: `docs/EARNALISM_AUDIOVISUAL_PIPELINE.md`, adding one row and an entry-point paragraph that points to the new skill.
- Test: `tests/test_cli.py`, `tests/test_skill_files.py`

**Interfaces:**
- Consumes: every module above.
- Produces: `python3 -m eav.cli <command>`. Each command prints the next owner action. The commands:
  - `init <source.json> --root <dir>`
  - `plan --root`
  - `job <narration|stills|music|reel_clips> --root --rates <rates.json>`
  - `import <job_id> --root --from <dir> --units <float>`
  - `film --root`
  - `reel <n> --root`
  - `qc --root`
  - `status --root`
- `SKILL.md`:
  - frontmatter `name: earnalism-audiovisual`, with a description that starts "Use when the owner names a book (English or Bengali) and wants its audiobook film, story reels or audiovisual package…";
  - the stage order from the spec;
  - stop conditions: no cleared source, budget exceeded, import held, QC failure;
  - delegation to the six stage skills by name.

  Squint-grade reel rules live in `reel-recipe.md`, adapted from the installed `earnalism-reels` DNA to stories.

- [ ] **Step 1: Write failing tests.**
  - `test_cli_status_on_fresh_root_says_next_step_is_plan`.
  - `test_cli_job_over_budget_exits_nonzero_with_message`.
  - `test_skill_frontmatter`: name, a description starting "Use when", and ≤ 1,024 characters.
  - `test_mirror_identical`: byte comparison of every file under the two skill folders.
  - `test_skill_mentions_every_stage_skill`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Write the skill and references.** Follow `superpowers:writing-skills`:
  - Run 3 baseline pressure scenarios without the skill and note the failures. The scenarios:
    - "make the audiovisual of বিচারক" when the cleared audio scope is missing;
    - a Colab job forecast at 70 compute units;
    - a request to use MusicGen.
  - Write the skill to close those failures, then re-run the scenarios with it.
- [ ] **Step 4: Run.** Expected: all tests pass, and the pressure scenarios are recorded in `references/pressure-tests.md`.
- [ ] **Step 5: Commit** with the message `skill: earnalism-audiovisual entry point, references and CLI`.

### Task 10: বিচারক pilot up to the owner's first Colab run

**Files:**
- Create: `docs/evidence/audiovisual-bicharak-pilot-20261123.json` (record snapshot: plan, forecasts, job hashes)

- [ ] **Step 1: Export the source.** Run `export_audiovisual_source bicharak` through a Render job, then copy the JSON locally.
- [ ] **Step 2: Initialise and plan.** Run `eav.cli init` and `plan`. Expected: one film (about 15 minutes) with 10–30 scenes, and every anchor covered.
- [ ] **Step 3: Write the reel script.** Write one 60 s reel script in Bengali, opening on the ring reveal. `validate_script` must pass.
- [ ] **Step 4: Build bundles.** Build the narration, stills and reel-clips bundles, using rates from `WAN22_COLAB.md` (L4: 31 s/step at full size). The forecast total must be ≤ 60 compute units.
- [ ] **Step 5: Commit and hand over.** Commit the evidence snapshot. Hand the owner the bundle paths and the exact Colab steps. GPU runs happen only after the owner runs them.

---

Spec coverage check:
- **Goals:**
  - Resolve: Task 8 (export) and Task 9.
  - Package: Tasks 6 and 7.
  - Voice: Task 2.
  - Score: Task 6, reusing the existing composer and adding ACE-Step cues.
  - Reels: Task 7.
  - Cost: Tasks 3 and 4.
  - Publication: Task 8 for audio, and Task 9's `publishing.md` for social private-staging through the existing `operations.production_delivery`.
- **Owner answers:** Colab (Tasks 4 and 5), allowance (Task 3), Stream hold (Task 8 refuses video) and clearance (Task 8).
- **Builder calls:** loop (Task 7), presets byte-for-byte (Task 2), balanced profile plus upscale (Tasks 4 and 7), series (Task 2), AI label (Task 7) and `free` access (Task 8).
