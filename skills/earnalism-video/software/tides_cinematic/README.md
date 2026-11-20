# Tides cinematic motion repair

Private replacement for the owner-rejected slide-like visual candidate. The
earlier renderer, media, narration and score remain preserved. This module draws
a full-picture shoreline with a fixed timber piling and gauge, performs an
illustrative time-compressed water-level rise, and pulls back into a textured
three-dimensional Earth and cratered Moon. It returns to the actual shore context
when the narration discusses local complexity. There are no all-time header
cards, diagram panels or wire-grid globes.

The Earth and Moon use source-bound NASA editorial texture maps. Their original
downloads, exact URLs, hashes, credits, limitations and observed usage guidance
are recorded in `cinematic-v2/assets/EDITORIAL_TEXTURE_RIGHTS.json`. The Earth map
is a 2015 satellite composite, not current weather. The Moon map is aesthetically
optimized as NASA documents. Neither map supplies tidal observations. These
textures are for the educational video body, not automatically for promotional
thumbnail art. Preserve the NASA source credit in the final release description;
no NASA review, specific permission or endorsement is implied.

The exact point-Moon model, common linear actual-arrow scale, measured phrase
onsets, visibly separate centre-relative frame and connected exaggerated ideal
ocean remain intact. Satellite geography disappears only for the clearly labelled
ideal-ocean illustration. The ellipse is not a physical ocean solution or tide
forecast. Texture sampling, lighting and motion are deterministic CPU work; no
model inference, model-weight training, GPU allocation or new installation occurs.

This module reuses the healthy source-plan, text measurement and canonical
branding helpers from `tides_rebuild`, not its rejected scene composition. The
source plan additionally binds `earth_texture`, `moon_texture` and
`texture_rights` descriptors. Narration/caption timing remains source-bound.

```sh
python -B -m video_studio.tides_cinematic.renderer proofs /path/render-plan.json --output /new/proof-directory
python -B -m video_studio.tides_cinematic.renderer motion-proof /path/render-plan.json --format landscape --start-ms 0 --end-ms 10000 --max-width 1080 --output /new/motion-proof.mp4
python -B -m video_studio.tides_cinematic.renderer silent-body /path/render-plan.json --output /new/native-body-directory
python -B -m unittest video_studio.tides_cinematic.test_renderer -v
```

The first deliverable is proof stills plus a ten-second silent motion excerpt.
Root may combine the matching accepted narration and newly reviewed score for
private playback. A complete film is rendered only after the actual proof is
reviewed. These tests and source assets do not establish full AV/listening
acceptance, physical-device delivery, owner approval or publication.

After root reviews that performed motion, `silent_body(plan, output)` calls the
same segment renderer at native size for each complete source clock. It writes
both silent bodies and `SILENT-BODY-MANIFEST.json`; audio and END remain absent.
The exact pre-wrapper renderer is retained privately, and AST comparison confirms
all picture/segment function definitions remain unchanged by this wrapper.
