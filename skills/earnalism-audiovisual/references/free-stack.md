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
| Film motion, mix, assembly, QC | ffmpeg, NumPy, Pillow | LGPL/GPL tools, BSD, HPND | container | `eav.film`, `eav.mix`, `eav.reel`, `eav.qc` |

## Forbidden

- **MusicGen**: CC-BY-NC weights; output cannot be used commercially. `build_job`
  refuses any spec naming it.
- **FLUX.1-dev**: non-commercial licence. Refused the same way.
- **Paid generators and credit-spending connectors**: Kling, ElevenLabs (voice or music),
  Suno, Runway, Adobe/Canva generative credits, Veo, Luma, HeyGen and the like. Not for a
  test, not "just the hook".

When the owner asks for a forbidden tool, say why in one sentence and offer the licensed
equivalent (MusicGen → ACE-Step cues or the VCSL score; FLUX.1-dev → FLUX.1-schnell).
Changing the stack is a design deviation that needs the owner's explicit approval and a
licence that permits commercial output.

## Colab settings

- One notebook per job, inert: first cell `RUN = False`; every later cell refuses to run
  until the owner sets `RUN = True`.
- Inputs travel as one zip whose sha256 is checked in Colab; outputs land in
  `/content/drive/MyDrive/earnalism-audiovisual/<title>/<job_id>/` with `manifest.json`
  (sha256 of every output and the model info).
- Reel clips use the `wan22` batch notebook and return as its export archive.
- Upscaling: lanczos to 1080×1920 plus mild unsharp in `eav.reel.assemble`; no new
  upscaler model or licence. The hook shot may use the 704×1280 detail profile when the
  forecast fits.
- Generator audio from Wan is always muted.

## Network

This container cannot reach Hugging Face or Instagram. Downloads and GPU work happen in
Colab; Claude works on imported, hash-verified outputs.
