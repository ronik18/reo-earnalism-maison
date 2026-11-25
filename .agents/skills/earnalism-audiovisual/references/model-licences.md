# Model licences and compliance

Determined 25 November 2026 from the licence texts on the Hugging Face Hub (read via the Hub
connector): the `diffusers/stable-diffusion-xl-1.0-inpainting-0.1` card (`license: openrail++`,
base model `stabilityai/stable-diffusion-xl-base-1.0`), that base model's `LICENSE.md`
("CreativeML Open RAIL++-M License dated July 26, 2023", Copyright (c) 2023 Stability AI), and the
`CIDAS/clipseg-rd64-refined` card (`license: apache-2.0`). This is a reading of the licence text
for this skill's use, not legal advice.

## SDXL inpainting (CreativeML Open RAIL++-M): what governs our use

- **Outputs are ours to use, including commercially.** Section III, paragraph 6: "Except as set
  forth herein, Licensor claims no rights in the Output You generate using the Model. You are
  accountable for the Output you generate and its subsequent uses. No use of the output can
  contravene any provision as stated in the License." Publishing retouched stills in films on
  Maison (paid or free) and in reels/trailers on YouTube is a use of Output.
- **Distribution conditions do not apply to us.** Paragraph 4 (pass the licence on, carry the
  use restrictions into downstream agreements, mark modified files) applies to distributing
  "the Model or Derivatives of the Model", which includes hosting it as a service. We only run
  the unmodified model in our own Colab job and publish images. We never ship, host or
  fine-tune the weights. If that ever changes, paragraph 4 applies in full.
- **Use restrictions (Attachment A) apply to every use.** We may not use the model: unlawfully;
  to exploit or harm minors; for verifiably false information meant to harm; to generate
  harmful personal data; to defame or harass; for adverse fully automated decisions; to
  discriminate or to exploit a group's vulnerabilities; for medical advice; or for justice,
  law-enforcement, immigration or asylum administration. Illustrating public-domain literature
  (Tagore, Wilde) falls outside every item.
- **The minors clause in practice.** Several stories have child characters (বিচারক's Hemshashi
  is a 14-year-old child widow; the children and the boy in The Selfish Giant). The skill already
  limits retouch to small masked areas of finished stills and to story-faithful, non-sexual,
  dignified depiction. Never retouch a child character's body or clothing beyond restoring the
  story's described dress (for example a plain white widow's sari or bare forehead), and never
  in a way that sexualises, demeans or endangers a child. The pick review checks this.
- **"Research purposes" on the model card.** The card's "Direct Use" says "intended for research
  purposes only". The licence itself grants a "perpetual, worldwide, non-exclusive, no-charge,
  royalty-free, irrevocable copyright license", says it is "informed by the model card", and
  sets only Attachment A as the binding use restrictions. We treat the card text as the
  developers' guidance on fitness, not as a ban on commercial use of outputs: the licence
  grants output use expressly. The residual risk is low. To remove it entirely, a stricter
  route is to retouch only with Apache-2.0 models.
- **No attribution is required for outputs.** We still credit "AI-generated illustration" in
  each film's end card and description, and record the generator and licence per still.
- **No warranty, including on training data.** Section IV disclaims non-infringement. As for
  every generator here, the pick review rejects any still that resembles a recognisable real
  person, logo or existing artwork.
- **Trademarks.** We never use Stability AI's names or logos or suggest endorsement.

## CLIPSeg (Apache-2.0)

Masks are internal working files, never published. Apache-2.0 allows commercial use. Its notice
obligations attach to redistributing the model or its source, which we do not do.

## How the record and clearance carry this

- Each retouch job records the model repos, resolved revisions and the card licence
  identifiers printed by the notebook preflight, which refuses anything outside
  `openrail++`/`apache-2.0`/`mit`.
- A title's clearance evidence (`publishing.md`, "generator and music licences") lists, for any
  film that uses retouched stills, "SDXL Inpainting 0.1, CreativeML Open RAIL++-M (2023-07-26),
  outputs only; Attachment A use restrictions reviewed: none applicable", with the retouch job
  ids.
- Platform rules sit on top of this and are handled elsewhere: AI-content labels on social
  posts and the 2026 IT Rules disclosure (reel recipe), and Maison's 47-region publication
  policy.
