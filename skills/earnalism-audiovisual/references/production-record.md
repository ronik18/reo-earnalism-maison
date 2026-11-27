# Production record

One title root, one record, one writer. `record.json` (schema
`earnalism.audiovisual_record.v1`) is written atomically by `eav.record.Record`.

## Title root layout

```
<root>/record.json          source binding, artifacts (path, sha256, bytes, meta), events
<root>/source.json          the exact Maison export (edition, revision, content_sha256)
<root>/plan.json            scene plan + the voice preset used
<root>/jobs/<job_id>/       inert Colab bundle: notebook, inputs zip, build-manifest.json
<root>/narration|stills|music/<job_id>/   verified Colab outputs (or sliced ElevenLabs takes)
<root>/jobs/<job_id>/take-manifest.json   import-take: takes/, scripts/ and every sha256
<root>/reel_clips/<job_id>/ verified Wan clips + import receipt
<root>/film/film-NN/        narration.wav, timing.json (+provenance), .srt, mix.wav, film-NN.mp4
<root>/reels/reel-N/        script.json, caption.txt, narration.wav, shots.json (planned from the
                            measured narration by --plan-shots), reel-N.mp4
<root>/specs/world-bible.json   the title's world bible (plan-shots --bible default)
<root>/film/film-NN/shots/  <scene>.input.json (planner input, Claude + reviewer), <scene>.json (plan with
                            approval + input sha256), AV script (two columns)
<root>/film/film-NN/voice/<scene>.wav   re-timed scene narration (retime); beside each take
                            <take-stem>.voicecheck.json, plus voicecheck-profile.json
<root>/film/film-NN/audio/<scene>.mix.wav + .mix.json   per-scene cue and mix (stems, peak, margin, fx)
<root>/film/film-NN/shots-cache/, clip-picks.json   per-shot renders keyed by hash; Wan take picks
<root>/stills/<job_id>/<key>--cN.png + gate.json    candidates with their gate results; picks/ and
                            picks/gate-overrides.json (single stills; reasons recorded)
<root>/film_clips/<job_id>/ Wan clips <key>.mp4, <key>.last.png, depth maps (*.depth.png), sfx files + licences
<root>/../title-caps.json   per-title lifetime caps (beside the ledger; default 60 CU)
<root>/gate-calibration.json  from approved stills; makes needs_review blocking at pick
<root>/qc/                  report.json, contact sheets
<root>/maison/              audiovisual-clearance-evidence.draft.json
<root>/../allowance-ledger.json   shared CU ledger (all titles)
```

## What must be in it before release

- **Source**: edition id, revision id, content_sha256, export sha256, rights at export.
- **Voice**: model repo and revision, preset key and the exact description, clause if any.
  ElevenLabs narration (`import-take`): engine, model (`eleven_v3`), voice name and id,
  credits used (on the job, never the CU ledger, which records the job at 0 CU), the tagged
  scripts and source takes with their sha256, the cut of every join and which joins were
  estimated, voice style `continuous`.
- **Every generator output**: job id, model and revision (resolved at run time for FLUX and
  ACE-Step), seeds and prompts (inside the inputs zip), output hashes, forecast and actual CU.
- **Score**: route (VCSL editorial or ACE-Step cues), licence, cue hashes.
- **Measured timing**: `timing.json` with `provenance` = {method `eav.film.narration_track`,
  measured_with `ffprobe`, WAV sha256s, narration job id}.
- **Renditions**: film and reel hashes, durations, loudness, true peak, loop score.
- **Review**: QC report, owner review result, everything not reviewed marked `unassessed`.
- **Paper edit (R11)**: for every scene, the approved shot plan: approver, independent reviewer, time and
  the sha256 of the planner input the approval is bound to (an edit afterwards voids it).
- **Gates**: each candidate's `gate.json` (models and resolved revisions, licences read, scores), every
  `pick` with its overrides and reasons, and the calibration file once present.
- **Voice (cinematic)**: model (Eleven v4 id as given), voice id, passages with tagged scripts and takes,
  credits, `voicecheck` profile and per-take results, which takes were redone and why.
- **Sound**: per sound file its Commons page, licence and categories checked, or the CC0 dedication of
  synthesis (`sfx/README.md`).
- **Licences**: Apache-2.0 (Parler, FLUX.1-schnell, Wan 2.2 TI2V-5B, ACE-Step, CLIPSeg, Depth Anything V2 Small, MediaPipe, OWLv2, DINOv2-small), MIT (Whisper), CC0 (VCSL, CC0 sfx), CreativeML Open RAIL++-M (SDXL inpainting, for retouched stills; `model-licences.md`), ElevenLabs Creator plan commercial licence (narration).

Job endings are events too: `import/accepted`, `job/superseded` (never ran, 0 CU),
`job/closed` (ran, not imported, actual CU) and their pending forms `job/superseding`,
`job/closing` while one is under way. Reel planning adds `reel/scripted`,
`reel/narration_misfit` and `reel/shots_planned`. The R2 exchange
(`references/colab-exchange.md`) adds `job/exchange_uploaded`, `job/exchange_staged` and
`job/exchange_collected`: object keys, hashes and expiry only, never a signed URL.

Events are append-only. Failed and held attempts stay in the record; never delete or
rewrite them to make the history look clean.
