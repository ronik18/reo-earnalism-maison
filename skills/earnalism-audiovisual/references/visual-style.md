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
  gouache, 3D render, "not a cartoon", "not anime") is refused: describe the content instead.
- The world bible's `lens_and_look` names the house style; it never adds a second style.

## What still needs a human look after import

The style does not fix content. Check every imported still at full size for:

- **Faithfulness to the text**: appearance, age and beauty as the author describes them
  (e.g. Tagore's Kshiroda at 38 is "গভীর প্রশান্ত প্রগাঢ় সুন্দর", not haggard).
- **Period dress and customs**: e.g. a Bengali widow of the 1880s wears a plain white sari
  with no border, no bindi and no jewellery; no modern suits, watches, cars or wine bars.
- **Anatomy and physics**: hands and fingers, people sitting on something, feet on the ground.
- **Stray lettering or watermarks**, even small ones in a corner.
- **Identity drift** between shots of the same character.

Regenerate only the failing stills as a small patch job (`film` applies a later partial
stills job over the full set).
