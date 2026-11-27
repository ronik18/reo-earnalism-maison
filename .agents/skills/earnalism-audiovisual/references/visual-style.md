# Earnalism house visual style (owner decision, 24 November 2026)

Every book's audiovisual uses one look: **2D animated feature-film illustration**, the style of
the বিচারক stills the owner chose as the reference (`f01s007-6`, `f01s012-2`, `f01s018-1`,
`f01s017-3`, `f01s007-2`, `stills-film-01-r5`). It is a creative-standard decision; changing it
needs the owner.

## What the look is

- Clean, confident line art; soft cel shading with gentle painterly gradients in the
  backgrounds; expressive faces with large luminous eyes; cinematic framing.
- One consistent character design per person for the whole film: the world bible's character
  line is repeated word for word, and the same seed family is reused per character.
- Motion: pre-cinematic films use a slow push-in on every still and a 0.8 s cross-dissolve on
  narration boundaries (`eav.film.assemble`). Cinematic films (`film --shots`) use depth glides, Wan
  beats and planned transitions: dissolves only between layers of time, hard or match cuts inside a
  layer ([film recipe](film-recipe.md)); no flashy wipes either way.

## How it is enforced

- `eav.colab_jobs.HOUSE_STYLE` is appended to every stills prompt by the job builder. Prompts
  carry only content: who, doing what the text says at that beat, period, place, palette, light.
- A prompt asking for another look (photoreal, photograph, oil-on-canvas, realism, watercolour,
  gouache, 3D render) is refused: describe the content instead.
- A prompt using a negative word (`no`, `not`, `without`, `never`, `none`, `nor`, `n't`) is
  refused at job build, house style included (see Prompt wording).
- The world bible's `lens_and_look` names the house style; it never adds a second style.

## Prompt wording: positive only

FLUX.1-schnell runs at guidance 0 with no negative prompt, so every word it reads is something
to draw: "no bindi" paints a bindi, "no beard" a beard, "no watermark" a watermark (the
full-size review of 134 stills traced most failures to this). Describe what *is* there:

- Hemshashi, a widow of the 1880s: "bare forehead, bare ears and wrists, plain undecorated
  white cotton sari" (never "no bindi, no jewellery, no border").
- Judge Mohit: "smooth clean-shaven face" (never "no beard").
- Palette words are colours, not light sources: "honey-gold light", never "candle gold" (a
  candle appears).
- Clean corners and edges are already in the house style; never write "no text" or "no
  watermark".

## Candidates, review and pick

A redone shot carries `"candidates": 3` in its stills spec item (1–4, default 1). The job makes
`<key>--c1.png` … `<key>--cN.png` from seeds `seed` … `seed+N-1`; the forecast counts every
image. After import a reviewer looks at each candidate at full size and records the best with
`pick --job <stills job> --choices picks.json` (`{"<key>": <candidate number>}`; a re-run
replaces the selection). `film` patches only picked candidates, as `<key>.png`, over the base
set; an unpicked candidates job adds nothing (reported as `unpicked`) and is never the base.

## Retouch: redraw only a small region of a chosen still

When a still is right except for a small culturally-default detail the story forbids (a bindi,
ear studs or a coloured sari border on Hemshashi; a beard on Judge Mohit; overhead wires in an
1880s lane), prompt wording will not remove it and a regenerated shot loses what was right.
Retouch it instead (owner decision 25 November 2026): an open inpainting model redraws only
masked regions; every pixel outside the mask stays the source's own.

- Models: `diffusers/stable-diffusion-xl-1.0-inpainting-0.1` (card licence `openrail++`) and
  `CIDAS/clipseg-rd64-refined` masks (`apache-2.0`), revisions resolved and recorded per run. The
  notebook reads both model cards' `license` field before any download and refuses anything
  outside `openrail++`, `apache-2.0`, `mit`. No other model, no paid service.
- Spec (`job retouch --root R --film N --spec retouch.json --rates rates.json [--job-id ID]`):

  ```json
  {"items": [{"key": "f01s007-4",
              "source": {"job": "stills-film-01-r9", "file": "f01s007-4--c2.png"},
              "regions": [{"find": "red dot on the forehead",
                           "prompt": "smooth bare forehead skin, same skin tone"},
                          {"find": "small gold earrings", "prompt": "bare earlobes, same skin tone"}],
              "prompt": "a young widow in a plain white cotton sari, 1880s courtyard",
              "seed": 123, "candidates": 3, "strength": 0.85}]}
  ```

  The source is a file of an imported stills job of that film, with the sha256 the record holds;
  `key` is that still's key; 1–6 regions; `strength` 0.5–1.0; `candidates` 1–4.
- `find` is a mask query: it names what to locate, so it may name the unwanted thing ("red dot on
  the forehead"). Every `prompt` (each region's and the scene's) is drawn, so it is positive-only
  like a stills prompt and the house style is appended: "smooth bare forehead skin", never "no
  bindi".
- Output: `<key>--c1.png` … `<key>--cN.png` (seeds `seed` … `seed+N-1`) at the source resolution,
  plus `<key>--mask.png`. Review the mask first: it must cover the detail and little else (a mask
  that missed shows the detail unchanged; the run records regions that found nothing as
  `empty_regions`). Then review each candidate at full size and `pick --job <retouch job>`
  exactly as for stills. `film` patches only the picked candidate over the base, as `<key>.png`;
  masks never enter the film; an unpicked retouch job adds nothing.

## Touch-up: repaint a small defect locally, in hand-placed boxes

When the forbidden detail is small and local (a bindi dot, ear or nose studs, bangles, a coloured
sari edge, a moustache on a cel-shaded face, wires or a pole against sky, corner text, out-of-season
fruit, a stray small object) and text-prompted masks keep missing it, touch it up locally (owner
decision 25 November 2026): OpenCV (`opencv-python-headless`, Apache-2.0) on the CPU, no model, no
Colab, no randomness. Install with `pip install -r software/requirements-touchup.txt`.

- Spec (`touchup --root R --film N --spec touchup.json --job-id ID`):

  ```json
  {"items": [{"key": "f01s007-4",
              "source": {"job": "retouch-film-01-r9", "file": "f01s007-4--c1.png"},
              "ops": [{"op": "inpaint", "box": [395, 305, 420, 335], "radius": 5},
                      {"op": "inpaint", "box": [600, 300, 660, 350], "radius": 3,
                       "mask": "color", "target": "#C8323C", "tol": 60},
                      {"op": "recolor", "box": [500, 510, 620, 768], "lightness": "shade",
                       "from": {"hue": [330, 30], "sat_min": 0.25}, "to": "#F4F1EA"},
                      {"op": "fill", "box": [0, 0, 1344, 120], "sample": [40, 60]},
                      {"op": "clone", "box": [960, 0, 1100, 300], "from": [-160, 0]}]}]}
  ```

  The source is a recorded file of an imported stills or retouch job of that film whose sha256
  matches the record; `key` is that still's key. Boxes are `[x0, y0, x1, y1]` in source pixels.
  `mask`: `box` (default), `ellipse` (inscribed), `color` (`target` + `tol` RGB distance,
  `grow` px) or `line` (`line` [x0, y0, x1, y1] + `width`: a stick, wire or pole). `feather` (default 3 px) blends each edit inside its box; every pixel outside all
  boxes stays byte-identical. Hues are degrees (h0 > h1 wraps through red), `sat_min` is chroma
  0-1. `recolor` keeps lightness; `"lightness": "shade"` lifts to the target and keeps folds.
- Output: `touchup/<ID>/<key>--c1.png` plus `<key>--mask.png`; the record holds the spec, the ops
  and the sha256 of every source and output. Open both at full size: the defect must be gone,
  the repair invisible (no smear, seam or colour patch) and faces intact. Then `pick --job <ID>`;
  `film` patches only the pick; masks never enter the film.
- Not for composition, scale, time of day, wrong characters or anatomy: regenerate those.
  Child characters: only restore the story's described dress and bare skin (model-licences.md).

## Edit: instruction-following repair of a held shot

When a shot is wrong in a way no mask or box fixes (a child widow given a bindi or jewellery, or
drawn too old or too young; a judge with a beard; the Giant at the wrong scale; snow inside a
room; fruit out of season; palms missing their reverent marks), hold it and edit it (owner
decision 25 November 2026, free test on Colab Pro within the caps): `Qwen/Qwen-Image-Edit-2511`
(Apache-2.0) follows a written instruction on the still, optionally guided by up to two reference
images (for example a correct still of the same character or setting).

- Spec (`job edit --root R --film N --spec edit.json --rates rates.json --job-id ID`):

  ```json
  {"items": [{"key": "f01s013-4",
              "source": {"job": "retouch-film-01-r2", "file": "f01s013-4--c1.png"},
              "refs": [{"job": "stills-film-01-r5", "file": "f01s007-6.png"}],
              "instruction": "Remove the red dot from her forehead and the gold studs from her ears; she is a fourteen-year-old widow in a plain white cotton sari",
              "negative": "bindi, jewellery, coloured sari border, adult face",
              "seed": 123, "candidates": 2, "steps": 40, "true_cfg_scale": 4.0}]}
  ```

  `source` is a recorded image of an imported stills, retouch or touchup job of that film whose
  sha256 matches the record, and `key` is its still's key. `refs` (0–2) are recorded images of any
  imported stills, retouch or touchup job of the title, sha256-checked the same way (review
  masks never count). `candidates` 1–4 (seeds `seed` … `seed+N-1`), `steps` 8–50 (default 40),
  `true_cfg_scale` 1–10 (default 4.0), `instruction` and `negative` at most 900 characters each.
  Optional top-level `"min_vram_gib"` (integer 0–80, default 0): the notebook's GPU cell stops
  before any download on a smaller GPU ("needs an A100 or larger: Runtime -> Change runtime type
  -> A100"); 30 requires at least an A100 40 GB (8-bit), 70 an A100 80 GB (bf16).
- **Wording exemption.** The positive-only rule (Prompt wording, above) does not apply to edits:
  the model reads a real negative prompt with true classifier-free guidance, and an edit
  instruction exists to name what to change, "remove the beard" included. Put what must not
  appear in `negative`. Another look ("photoreal", "watercolour", …) is still refused in the
  instruction (it is allowed in `negative`), and every instruction ends with the builder's "Keep
  everything else unchanged: the same 2D animated feature-film illustration style, …".
- Runs: the notebook checks the GPU, model access and the card licence (apache-2.0 only), installs
  the pinned diffusers and refuses one without `QwenImageEditPlusPipeline`, then loads the
  transformer by total VRAM: bf16 from 70 GiB (A100 80 GB), 8-bit LLM.int8 from 30 GiB (A100
  40 GB), else 4-bit NF4 (L4; the first NF4 run came out grainy and washed, so NF4 is the last
  resort). Both quantized loads keep `img_in`, `txt_in`, `time_text_embed`, `norm_out` and
  `proj_out` bf16 (names from diffusers 0.37.0's QwenImageTransformer2DModel). Text encoder bf16,
  model CPU offload, VAE decode in float32 (rules out decode banding). It edits at about one megapixel at the source's aspect ratio and
  writes `<key>--c1.png` … `<key>--cN.png` resized back to exactly the source's size; it prints the
  GPU, precision, the modules kept bf16 and seconds per image.
- Review each candidate at full size (faithfulness, identity against the refs, nothing else
  changed, the child-depiction rule of `model-licences.md`), then `pick --job <edit job>` exactly
  as for stills. `film` patches only the pick, as `<key>.png`.
- **Holds.** A held key whose film still is a picked edit is released: the film shows the edit,
  not a substitute, and records it under `released_by_edit`; other holds stay. An unpicked edit
  releases nothing, and a picked retouch or touch-up does not release a hold (`hold --clear` or a
  new `hold` does).

## What still needs a human look after import

The style does not fix content. Check every imported still at full size for:

- **Faithfulness to the text**: appearance, age and beauty as the author describes them
  (e.g. Tagore's Kshiroda at 38 is "গভীর প্রশান্ত প্রগাঢ় সুন্দর", not haggard).
- **Period dress and customs**: e.g. a Bengali widow of the 1880s wears a plain undecorated
  white sari with a bare forehead and bare wrists; check for modern suits, watches, cars or
  wine bars.
- **Anatomy and physics**: hands and fingers, people sitting on something, feet on the ground.
- **Stray lettering or watermarks**, even small ones in a corner.
- **Identity drift** between shots of the same character.

Regenerate only the failing stills as a small patch job with candidates, then pick (`film`
applies a later partial stills job, or a candidates job's picks, over the full set).

## Gate (character and period check of the stills)

Every `job stills` notebook runs a gate cell after the stills and writes `<key>.gate.json` per image:
`{eyes, hands_detached, anachronisms, anchor_similarity, pass, needs_review, notes}`. Checks:
- MediaPipe Face Landmarker: open eyes per face by eye aspect ratio (this measures openness, not a malformed
  eye). A frontal face without two open eyes is a certain fail, a profile with fewer a review.
- MediaPipe Hand Landmarker: a wrist outside every OWLv2 person/arm box and face box, grown 3% of the
  diagonal, is detached (fail). Nothing to judge against is a review. No hands detected is a valid result.
- OWLv2 labels gas cylinder, air conditioner, electric cable, spotlight, modern eyeglasses, plastic, utility
  pole, modern high-rise building: score >= 0.30 fail, 0.15-0.30 review.
- DINOv2-small (`facebook/dinov2-small`, Apache-2.0) cosine of the largest person-box crop to the character's
  anchor still; below 0.55 is a review. The figure is uncalibrated. (CLIP was dropped: its card puts any
  deployed use out of scope.)

A check that did not run (model error, licence refused, unreadable card) is `needs_review` with the reason in
`notes`, never `pass`. Licences are read from each Hub card at run time and must be apache-2.0 or mit; an
unreadable card means the model is not loaded, and a model loads only at the revision whose card was read.

The gate is clocked: it is skipped when the job is INCOMPLETE or the seconds left do not cover its set-up
(300 s), 6 s per still and the manifest reserve, and the forecast includes those seconds (`gate_s`, an ESTIMATE
in `rates.json`). Any failure inside the gate leaves the stills, manifest and upload alone; the manifest's
`model.gate` records the intent and lists `ungated` stills.

Anchor: a stills item may carry `"anchor": "<name>.png"`; the spec's `art_dir` holds that file and the builder
puts it in inputs.zip as `anchors/<name>.png` (candidates inherit it).

At `pick`: a certain fail (pass false, needs_review false) is refused unless `--override-fail KEY=reason`.
`needs_review` is advisory (warned and recorded in the pick as `advisories`) until the title has a
`gate-calibration.json` beside its record.json (written from approved stills; the gate's thresholds are
unmeasured until then); after it, a needs_review candidate needs `--override KEY=reason`. Both flags are
repeatable and per key; reasons are recorded in the pick and its event. A job whose gate was intended but left
no result for a candidate counts as needs_review. A job that was never gated picks as before. `film` refuses a
still whose gate.json is a certain fail unless a reason is recorded (a pick `--override-fail`, or
`picks/gate-overrides.json` `{"<key>": "<reason>"}` for a single image).

The builder refuses a stills prompt whose house-style-first text is over 180 on the calibrated token estimate
(FLUX's T5 cuts at 256 real tokens); the limit comes from the six recorded truncated jobs
(`tests/fixtures/t5_recorded_prompts.json`).

## Sound fetch (film_clips)

A film_clips spec with `"sfx": {"crows": "crows cawing morning", ...}` adds a cell before the Wan clips that
searches Wikimedia Commons (no key), keeps up to two files per name whose title holds a search word as a whole
word and whose rights are clear: CC0, or public domain by the author's own release (a PD-self / "Public domain
due to author's release" / "Self-published work" category, read with one `prop=categories` query per candidate title, hidden
categories included; a list cut by `continue.clcontinue` is refused as "categories incomplete"). Commons reports PD-USGov and PD-old files as "Public domain" too, so a file with any
country-limited or age-based category (PD-US*, PD-USGov*, PD-old*, PD-Art*, *-exempt, "Works of the United
States government") or no clear basis is refused. The basis is recorded per file in `sfx-licences.json`
(title, page, licence, author, basis). Writes `sfx-<name>-<n>.<ext>` and `sfx-licences.json`.
Eight minutes at most, reserved in the forecast; it never fails the job.
Import places them under `film_clips/<job_id>/sfx/`.
