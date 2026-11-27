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

## Qwen-Image-Edit-2511 (Apache-2.0): edit

`job edit` uses `Qwen/Qwen-Image-Edit-2511` (Hub card `license: apache-2.0`, tag
`diffusers:QwenImageEditPlusPipeline`, ~20.4B parameters; its text encoder is Qwen2.5-VL-7B,
shipped in the same repo under the same card), read 25 November 2026 through the Hugging Face
connector. Apache-2.0 permits commercial use of the model and places no restriction on outputs;
its notice and attribution obligations attach to redistributing the weights or code, which we do
not do (we run the unmodified model in our own Colab job and publish images). There is no
use-restriction attachment as in OpenRAIL; our own rules still apply: the child-depiction rule
below and the pick review against likenesses of real people, logos or existing artwork. The
notebook re-reads the card's `license` field before any download and refuses anything but
`apache-2.0` (its own allowlist; the retouch allowlist is not reused). Edit follows the same
child-depiction rule as retouch and touch-up: an edit of a child character only restores the
story's described age, dress and bare skin (a plain white sari, a bare forehead, earlobes or
wrists, a child's face), never alters a child's body, and never sexualises, demeans or endangers
a child.

## OpenCV (Apache-2.0): touch-up

`eav touchup` uses `opencv-python-headless` (Apache-2.0 since OpenCV 4.5.0; the wheel bundles
FFmpeg and other libraries under their own permissive or LGPL licences, which we do not
redistribute). It is a library run in our container, not a generative model: no weights, no use
restrictions, no attribution on outputs. The Telea and Navier-Stokes inpainting algorithms are
patent-free. Touch-up follows the same child-depiction rule as retouch: only restore the story's
described dress or bare skin (a plain white sari edge, a bare forehead, earlobes or wrists), never
alter a child's body, and never in a way that sexualises, demeans or endangers a child.

## Cinematic film models (27 November 2026)

Determined from each card's `license` field as the notebooks re-read it at run time (the check
fails closed: a card that cannot be read means the model is not loaded).

- **Wan 2.2 TI2V-5B** (`Wan-AI/Wan2.2-TI2V-5B-Diffusers`): Apache-2.0, commercial use of the model
  and its output permitted; no OpenRAIL attachment. Generator audio is always muted. `film_clips`
  allowlist: `apache-2.0` only.
- **Depth Anything V2 Small** (`depth-anything/Depth-Anything-V2-Small-hf`): Apache-2.0. **Base and
  Large are non-commercial and excluded**; the notebook raises on any other depth repo. Depth maps are
  working files for the glide, never published.
- **MediaPipe Face and Hand Landmarker**: Apache-2.0, declared in the notebook (there is no Hub card to read); gate-only, nothing published.
- **OWLv2** (`google/owlv2-base-patch16-ensemble`) and **DINOv2-small** (`facebook/dinov2-small`):
  Apache-2.0 on the Hub (read 27 Nov 2026). Gate-only. Run-time allowlist for gate models:
  `apache-2.0`, `mit`.
- **CLIP is excluded.** Its model card carries no licence and puts any deployed use, commercial or
  not, out of scope; the character-lock check uses DINOv2-small instead. Adding a model needs a card
  that grants commercial use and the owner's approval.
- **Whisper** (MIT): permits commercial use; listed for the planned word check (not yet built, planned: Task 14).
- **Eleven v4 narration**: ElevenLabs Creator plan, whose paid tier carries the commercial licence for
  generated audio (owner decision 24 Nov 2026, v4 chosen 26 Nov); credits only, never top-ups.
- **Sound effects**: only CC0 files, or public-domain files whose author released them to the public
  domain worldwide (Commons categories show the author's own release); country-limited or age-based
  public-domain files (PD-US, PD-old, PD-Art …) are refused because the 47-region publication policy
  needs worldwide status. Original synthesis is dedicated to CC0. Each file's page and licence are
  recorded.
- The child-depiction rule above applies to every new still, clip and edit: named minors only in
  dignified close-ups.

## How the record and clearance carry this

- Each retouch job records the model repos, resolved revisions and the card licence
  identifiers printed by the notebook preflight, which refuses anything outside
  `openrail++`/`apache-2.0`/`mit`.
- A title's clearance evidence (`publishing.md`, "generator and music licences") lists, for any
  film that uses retouched stills, "SDXL Inpainting 0.1, CreativeML Open RAIL++-M (2023-07-26),
  outputs only; Attachment A use restrictions reviewed: none applicable", with the retouch job
  ids.
- Each edit job records the model repo, resolved revision, the `apache-2.0` card licence the
  preflight printed, the pinned and installed diffusers versions and the precision used. A title
  whose film uses an edited still lists "Qwen-Image-Edit-2511, Apache-2.0, outputs only" with the
  edit job ids.
- Platform rules sit on top of this and are handled elsewhere: AI-content labels on social
  posts and the 2026 IT Rules disclosure (reel recipe), and Maison's 47-region publication
  policy.
