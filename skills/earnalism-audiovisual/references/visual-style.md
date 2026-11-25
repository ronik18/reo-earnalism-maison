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
- Smooth motion between stills: the film's slow push-in on every still and a 0.8 s
  cross-dissolve on narration boundaries (`eav.film.assemble`); no hard cuts, no flashy wipes.

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
