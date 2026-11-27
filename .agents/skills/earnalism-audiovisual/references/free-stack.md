# Free stack: models, licences, where they run

Zero additional spend. Everything heavy runs in the owner's existing Colab Pro account,
started by the owner; everything else runs in Claude's container (CPU, ffmpeg).

| Stage | Model / asset | Licence | Where | Pin |
|---|---|---|---|---|
| Narration | Indic Parler-TTS `ai4bharat/indic-parler-tts` | Apache-2.0 | Colab GPU (`job narration`) | revision `7b527af5ee8ed1f9a28d80b19703ed9bb8ba10ca` |
| Stills | FLUX.1-schnell `black-forest-labs/FLUX.1-schnell` | Apache-2.0 | Colab GPU (`job stills`), 4 steps, guidance 0 | revision resolved and recorded by the notebook |
| Score cues (optional) | ACE-Step `ACE-Step/ACE-Step-v1-3.5B` | Apache-2.0 | Colab GPU (`job music`), instrumental only | revision, seed, prompt and output hashes recorded |
| Score (default) | VCSL piano/harp samples via `editorial_score.py` | CC0 | container | `earnalism-video/software/assets/music/vcsl-piano-harp-v1` |
| Reel motion | Wan 2.2 TI2V-5B (existing `wan22` builder) | Apache-2.0 | Colab L4, profile `l4-balanced-v2` (512×896, 24 steps) | model revision pinned in `wan22/batch.py` |
| Retouch (inpainting) | SDXL Inpainting 0.1 `diffusers/stable-diffusion-xl-1.0-inpainting-0.1` | CreativeML Open RAIL++-M (2023-07-26), see `model-licences.md` | Colab GPU (`job retouch`) | revision resolved and recorded by the notebook |
| Retouch masks | CLIPSeg `CIDAS/clipseg-rd64-refined` | Apache-2.0 | Colab GPU (`job retouch`) | revision resolved and recorded by the notebook |
| Edit (instruction edits with reference images) | Qwen-Image-Edit-2511 `Qwen/Qwen-Image-Edit-2511` (~20.4B, `QwenImageEditPlusPipeline`) | Apache-2.0, see `model-licences.md` | Colab GPU (`job edit`): A100 80 GB bf16, A100 40 GB 8-bit, L4 4-bit NF4 (sensitive modules kept bf16 when quantized); model CPU offload; VAE decode float32 | revision resolved and recorded by the notebook; `diffusers==0.37.0` (first release whose transformer accepts the model's `zero_cond_t`) |
| Touch-up (box repaint) | OpenCV `opencv-python-headless` (inpaint Telea/NS, colour, fill, clone) | Apache-2.0 | container CPU (`eav touchup`) | `software/requirements-touchup.txt` |
| Film animated beats (cinematic film) | Wan 2.2 TI2V-5B `Wan-AI/Wan2.2-TI2V-5B-Diffusers` | Apache-2.0 | Colab (`job film_clips`): 121 frames at 24 fps, 24 steps, guidance 5, **1280×704 (HD)** for faces/hands/climax or **896×512 (SD)** for environments; L4 (≥ 21 GB) or A100 | `diffusers==0.37.0`; card licence re-read before download; rates below |
| Depth for the glide | Depth Anything V2 **Small** `depth-anything/Depth-Anything-V2-Small-hf` | Apache-2.0 | Colab (same `film_clips` run): 16-bit depth PNG per still and per clip's last frame | **Small only.** Base and Large are non-commercial and excluded; the notebook refuses any other repo |
| Face and hand gate | MediaPipe Face Landmarker and Hand Landmarker | Apache-2.0 (declared in the notebook; no Hub card) | Colab, in the stills job (eye count and both eyes visible; hand count, detached hands) | files downloaded at run time |
| Anachronism gate | OWLv2 `google/owlv2-base-patch16-ensemble` | Apache-2.0 | Colab, stills job; 8 labels | licence read from the card; unreadable card = not loaded |
| Character-lock gate | DINOv2-small `facebook/dinov2-small` (cosine of the person-box crop against the anchor still) | Apache-2.0 | Colab, stills job | threshold uncalibrated until `gate-calibration.json`. **CLIP is excluded**: its card carries no licence and puts any deployed use out of scope |
| Narration (current standard) | Eleven v4, owner-picked voice | ElevenLabs Creator plan commercial licence (owner decision 24 Nov 2026) | ElevenLabs, included credits only (`references/earnalism-voice.md`) | model id and voice id recorded on the job |
| Narration word check | Whisper `openai/whisper-large-v3-turbo` | MIT (card read at run time) | Colab cell `words_cell.py.txt` (free runtime, not a job kind, no ledger units) writes `transcripts.json`; `eav voicecheck --transcripts` and `import-take --transcripts` compare it locally | none |
| Sound effects | Wikimedia Commons recordings, CC0 or public domain by the author's own worldwide release; original synthesis dedicated to CC0 | CC0 / PD | fetched in Colab by the `film_clips` sfx cell; licence and page recorded per file | country-limited or age-based PD refused |
| Voice redo gate, glide, retime, cue, sfx mixing | NumPy, OpenCV, ffmpeg | BSD / Apache-2.0 / LGPL | container CPU (`eav voicecheck`, `glide`, `retime`, `cue`) | none |
| Film motion, mix, assembly, QC | ffmpeg, NumPy, Pillow | LGPL/GPL tools, BSD, HPND | container | `eav.film`, `eav.mix`, `eav.reel`, `eav.qc` |

## Forbidden

- **MusicGen**: CC-BY-NC weights; output cannot be used commercially. `build_job`
  refuses any spec naming it.
- **FLUX.1-dev**: non-commercial licence. Refused the same way.
- **Paid generators and credit-spending connectors**: Kling, ElevenLabs music, ElevenLabs voice beyond
  the owner-approved narration route (below),
  Suno, Runway, Adobe/Canva generative credits, Veo, Luma, HeyGen and the like. Not for a
  test, not "just the hook".

The one exception is ElevenLabs narration (Eleven v4, previously v3) within the Creator plan's
included credits (owner decisions 24 and 26 Nov 2026, `references/earnalism-voice.md`). Excluded
models, with the reason: Depth Anything V2 Base and Large (non-commercial), CLIP (card puts deployed
use out of scope), MusicGen (CC-BY-NC), FLUX.1-dev (non-commercial), Real-ESRGAN and other BSD-3
models (need owner approval; not used), Freesound (needs a key).

When the owner asks for a forbidden tool, say why in one sentence and offer the licensed
equivalent (MusicGen → ACE-Step cues or the VCSL score; FLUX.1-dev → FLUX.1-schnell).
Changing the stack is a design deviation that needs the owner's explicit approval and a
licence that permits commercial output.

## Colab settings

- One notebook per job, inert: first cell `RUN = False`; every later cell refuses to run
  until the owner sets `RUN = True`.
- **Hard stop** (narration, stills, music): `DEADLINE_SECONDS` = the forecast seconds the
  ledger reserved, counted from the clock cell. An item starts only if it (and the
  manifest) can finish before it, and a timer unassigns the runtime at it. A stopped or
  short run writes `manifest.json` with `status: INCOMPLETE`, which `import` refuses;
  end that job with `close --units <CU Colab shows>`.
- **Edit pin**: the edit notebook installs `diffusers==0.37.0` before the clock and refuses to
  continue (before any weights download) if `QwenImageEditPlusPipeline` or the transformer's
  `zero_cond_t` option is missing. 0.36.0 has the pipeline but silently drops `zero_cond_t`.
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

## Film profile rates (measured 26–27 Nov pilots)

| Job | Rate |
|---|---|
| Wan HD 1280×704, L4 | about 880–920 s per finished clip (`clip_s_hd` 900), 2.4 CU per hour |
| Wan HD 1280×704, A100 | about 212–215 s per clip (`clip_s_hd_a100` 215), 4.5 CU per hour |
| Wan SD 896×512, L4 | about 405–435 s per clip (`clip_s_sd` 435) (A100 SD unmeasured: forecast at the L4 figure) |
| Stills (FLUX.1-schnell, int8, L4) | about 10 s each (about 0.1 CU per 4-candidate job) |
| ACE-Step stems | about 13 s per 60 s stem on L4 |
| Colab session set-up | 5–8 minutes |

Details and the forecast formula: [compute-budget.md](compute-budget.md). Hard stops must leave time
for the manifest and the upload after the last cell.

## Network

This container cannot reach Hugging Face or Instagram. Downloads and GPU work happen in
Colab; Claude works on imported, hash-verified outputs.
