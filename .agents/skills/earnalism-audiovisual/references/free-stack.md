# Free stack: models, licences, where they run

Zero additional spend beyond Modal's caps of $30 per UTC month and $6 per title (owner decision
of 26 November 2026). Heavy jobs run in the owner's existing Colab Pro account, started by the owner, or
(narration, stills, music only) on Modal via `eav modal-run`, executing the same built notebook
with the same pinned models, voices and licences; Wan reel clips run only in Colab. Everything
else runs in Claude's container (CPU, ffmpeg).

| Stage | Model / asset | Licence | Where | Pin |
|---|---|---|---|---|
| Narration | Indic Parler-TTS `ai4bharat/indic-parler-tts` | Apache-2.0 | Colab or Modal GPU (`job narration`), batched (pinned `batch`, default 8), bf16/fp16 + SDPA | revision `7b527af5ee8ed1f9a28d80b19703ed9bb8ba10ca` |
| Stills | FLUX.1-schnell `black-forest-labs/FLUX.1-schnell` | Apache-2.0 | Colab or Modal GPU (`job stills`), 4 steps, guidance 0 | revision resolved and recorded by the notebook |
| Score cues (optional) | ACE-Step `ACE-Step/ACE-Step-v1-3.5B` | Apache-2.0 | Colab or Modal GPU (`job music`), instrumental only | revision, seed, prompt and output hashes recorded |
| Score (default) | VCSL piano/harp samples via `editorial_score.py` | CC0 | container | `earnalism-video/software/assets/music/vcsl-piano-harp-v1` |
| Reel motion | Wan 2.2 TI2V-5B (existing `wan22` builder) | Apache-2.0 | Colab L4 only (never Modal), profile `l4-balanced-v2` (512×896, 24 steps) | model revision pinned in `wan22/batch.py` |
| Film motion, mix, assembly, QC | ffmpeg, NumPy, Pillow | LGPL/GPL tools, BSD, HPND | container | `eav.film`, `eav.mix`, `eav.reel`, `eav.qc` |

## Forbidden

- **MusicGen**: CC-BY-NC weights; output cannot be used commercially. `build_job`
  refuses any spec naming it.
- **FLUX.1-dev**: non-commercial licence. Refused the same way.
- **Paid generators and credit-spending connectors**: Kling, ElevenLabs (voice or music),
  Suno, Runway, Adobe/Canva generative credits, Veo, Luma, HeyGen and the like. Not for a
  test, not "just the hook". The one permitted spend is Modal GPU time inside its $30 UTC-month and $6 per-title caps.

When the owner asks for a forbidden tool, say why in one sentence and offer the licensed
equivalent (MusicGen → ACE-Step cues or the VCSL score; FLUX.1-dev → FLUX.1-schnell).
Changing the stack is a design deviation that needs the owner's explicit approval and a
licence that permits commercial output.

## Colab and Modal settings

Modal runs the notebook's own code cells with `RUN = True` and the Drive paths shimmed; the job
folder it leaves is what `import` expects from Colab. `modal-run` refuses `reel_clips`. When the
session cannot reach Modal, the run goes through the `modal-jobs` GitHub Actions workflow
(`modal-request` → workflow → `modal-fetch` from the private R2 bucket → `import`; see
[compute budget](compute-budget.md#through-github-actions-request-workflow-fetch-import)).

- One notebook per job, inert: first cell `RUN = False`; every later cell refuses to run
  until the owner sets `RUN = True`.
- **Hard stop** (narration, stills, music): `DEADLINE_SECONDS` = the forecast seconds the
  ledger reserved, counted from the clock cell. An item starts only if it (and the
  manifest) can finish before it, and a timer unassigns the runtime at it. A stopped or
  short run writes `manifest.json` with `status: INCOMPLETE`, which `import` refuses;
  re-run the job to resume it (finished items are kept, checked against this job's inputs.zip; the
  total across sessions stays within the reserved seconds; on Modal from this session:
  `modal-request` again), or end it with `close --units <CU Colab shows>` (a job that ran on Modal settles its Modal rows in USD plus its Colab CU: `modal-run --colab-units` records the Colab CU before the move, `--units` any Colab work after it).
- **Package versions**: the notebooks still `pip install` parler-tts and ACE-Step from
  git and diffusers/transformers unpinned. Every output manifest records the resolved
  versions (and VCS commits) under `packages`, and `import` refuses a manifest without
  them. Exact pins follow the owner's first successful run: copy those versions into
  the templates before the next build.
- Inputs travel as one zip whose sha256 is checked in Colab; outputs land in
  `/content/drive/MyDrive/earnalism-audiovisual/<title>/<job_id>/` with `manifest.json`
  (sha256 of every output and the model info).
- Reel clips use the `wan22` batch notebook and return as its export archive. That
  notebook has no `RUN` flag: the owner enables `RUN_BATCH`, `VERIFY_INPUTS`,
  `BEGIN_ALLOCATION`, `SETUP_BATCH`, `GENERATE_BATCH`, `EXPORT_AND_DOWNLOAD` in order
  and writes `/content/wan22-batch-authority.json` (reel-recipe.md). Claude never
  writes that file.
- Upscaling: lanczos to 1080×1920 plus mild unsharp in `eav.reel.assemble`; no new
  upscaler model or licence. The hook shot may use the 704×1280 detail profile when the
  forecast fits.
- Generator audio from Wan is always muted.

## Network

This container cannot reach Hugging Face or Instagram. Downloads and GPU work happen in
Colab or Modal; Claude works on imported, hash-verified outputs.
