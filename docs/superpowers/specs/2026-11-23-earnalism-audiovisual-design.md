# earnalism-audiovisual — one skill from a book title to a finished audiovisual — design

Owner request, 23 November 2026: build an "earnalism-audiovisual" skill that, given an English or Bengali book name, prepares and publishes an animated audiovisual of the book. It should be read in a distinctive **Earnalism Voice** (storytelling with drama), carry a theme-fit instrumental score and animation, and cost nothing beyond the owner's Claude Pro and Colab Pro. The benchmark is the end-to-end viewer experience of the @watchsquint Instagram reels: storytelling voice, music, animation pacing and animation quality.

Owner decisions in this conversation:
- **Formats (option 1).** Each title gets a full-length **audiobook film** (Squint-grade voice and score over illustrated scenes with gentle motion) plus **one or two Squint-grade story reels** (60–120 s, full AI motion).
- **Build approach (A).** One new entry-point skill that conducts the six existing Earnalism stage skills and adds what is missing. It does not replace them.

## Intent

One instruction, such as "Make the audiovisual of বিচারক", should yield a reviewable, release-ready package. It should feel like one coherent Earnalism production: the same narrator identity, the same sound world and one visual world per title. It should also be cheap enough to repeat for every catalogue title. The reels exist to bring people to the platform through shares. The film is the product members read and listen to on Maison.

## Goals

- **Title in, package out.** Input is a title, plus a language when the title alone is ambiguous. The skill resolves the exact Maison edition and its cleared source text, and stops if either is missing.
- **The package:**
  1. A full-length audiobook film: landscape for Maison and YouTube, with a portrait derivative only if requested.
  2. One or two reels at 1080×1920: 60 s, or 120 s when the story needs it.
  3. Captions/subtitles (SRT/VTT) for the film; reels follow the Squint "no burned text" rule.
  4. A cover or thumbnail per deliverable, and captions and copy per destination.
  5. A production record: source, voice, score and visual hashes, plus licences and review results.
- **The Earnalism Voice.** One recognisable narrator per language, with a storytelling-plus-dramatic performance (defined below), used in every film and reel.
- **The score.** A theme-fit instrumental score, quiet under speech and audible in pauses, with purposeful silence at turns.
- **Squint-grade reels:**
  - a paradox or dramatic hook spoken on frame 1;
  - one continuous visual world;
  - a new shot every 5–7.5 s, each advancing the story;
  - a slow, locked-off camera, with motion coming from the subject;
  - a loop close back into frame 1;
  - no text overlays.
- **Cost.** Zero additional spend. Every model is open-weight with a licence that permits commercial output. Heavy inference runs in the owner's existing Colab notebook under Colab Pro, and everything else runs in Claude (script, direction, assembly, QC).
- **Publication.** Publishing goes through the existing paths only: the Maison staff/production-handoff routes or `publish_cleared_editions`-style server commands, and the social private-staging adapters in `operations.production_delivery`. Publishing happens only to destinations the owner names.

## Non-goals

- Re-auditioning or retraining voices. The five-profile final roster and its pins stay as they are.
- New paid generators (Kling, ElevenLabs, Suno, Runway, Adobe/Canva credits, ElevenLabs Music) or any connector that spends credits.
- A new service, controller, or a separate notebook per stage. The existing Colab notebook is extended.
- Full-motion animation for the whole film. The owner chose option 1.
- Changing Maison's publication rules, the 9-territory whitelist or clearance requirements.

## Anti-goals (a failure even if it "works")

- Narration that changes, skips or adds to the book's words, or that sounds like two different narrators across units.
- Music that masks speech, uses drums or vocals under narration, or comes from an uncleared source.
- Visuals that contradict the text, drift in character or setting identity between shots, show deformed anatomy, or show text or logo artefacts.
- A reel that is a crop of the landscape film rather than its own composition.
- Publishing audio or video for a title whose audio/video formats are not cleared in every active territory.
- Burning through the Colab Pro allowance on retries. Every GPU job has a forecast and a hard stop.

## Constraints

- **Rights.** Audio and video are separate offered formats. Both live books are cleared for **Reader read/preview only**, so before publishing their audio or video on Maison, the owner's clearance decision and `publication_clearance` must be extended to those formats. That is the same evidence pattern as `docs/evidence/publication-clearance-20261123.json`. Social posting of public-domain story adaptations needs no Maison format grant, but it does need the owner's destination instruction.
- **Licences of every generator and asset**, recorded in the production record:
  - Indic Parler-TTS: Apache-2.0.
  - FLUX.1-schnell: Apache-2.0.
  - Wan 2.x: Apache-2.0.
  - ACE-Step: Apache-2.0.
  - VCSL samples: CC0.
  - Excluded: MusicGen (CC-BY-NC weights) and FLUX.1-dev (non-commercial).
- **Colab Pro compute.** Roughly 100 compute units a month. Measured on an L4: Wan 2.2 image-to-video at 704×1280, 50 steps runs at ~31 s/step; the `l4-balanced-v2` profile uses 512×896 at 24 steps. Every GPU job must carry a forecast (steps × measured s/step + decode + export) and stop rather than retry past it.
- **Pipeline rules.** The existing pipeline rules apply unchanged: `docs/EARNALISM_AUDIOVISUAL_PIPELINE.md`, AGENTS.md and the six stage skills. These cover dry narration first, measured timing, candidate-bound review, no invented listening claims, and one release writer.
- **Network.** This cloud container cannot reach Instagram or Hugging Face. Model downloads and GPU work happen in Colab, and Claude does planning, assembly and QC on retained outputs.

## Approaches considered

1. **One entry-point skill that conducts the existing six (chosen by the owner).** It adds the Earnalism Voice, the free generation stack in the existing notebook, the two format recipes and a compute budget. It reuses the roster, score, video, cover and release skills. It builds on proven work, keeps the policy gates, and gives one place to call.
2. **One self-contained skill replacing the six.** It is simpler to read, but it would duplicate and contradict the canonical pipeline and the voice pins. Rejected.
3. **A planning-only skill.** It would produce scripts, shot lists and prompts only. It is cheap to build but does not deliver an end-to-end video. Rejected.

## Design

### Skill shape

- **Location:** `skills/earnalism-audiovisual/` with a mirror in `.agents/skills/earnalism-audiovisual/`, matching how the other six are kept.
- **`SKILL.md`:** the entry point. It covers routing, the stage order, what each stage hands to the next, the stop conditions and the budget.
- **`references/`:**
  - `earnalism-voice.md`
  - `film-recipe.md`
  - `reel-recipe.md`, with the Squint DNA adapted to stories; the source is the installed `earnalism-reels` analysis.
  - `free-stack.md`: models, licences, Colab settings and measured costs.
  - `compute-budget.md`
  - `production-record.md`
  - `publishing.md`
- **Scripts.** Small deterministic helpers are added only where a stage has none today:
  - turning a cleared source into a scene plan;
  - a budget forecaster;
  - film assembly from scenes, narration and score;
  - reel assembly and loop check.

  Existing helpers in `earnalism-video/software` are reused rather than rewritten. These include `score.py`/`editorial_score.py`, `delivery_conform.py`, the contact sheets and the Wan22 builder.
- The skill is written and pressure-tested with `superpowers:writing-skills`: baseline scenarios without the skill, then with it.

### Stage flow

1. **Resolve.**
   - Resolve title to exact Maison edition, revision, cleared source text and hashes, and the rights scope per format. Stop if the source is not imported or cleared.
   - Read the whole work and build the context map (speakers, turns, reveals, ending) per `narrative-performance.md`.
2. **Adapt.**
   - **Film:** the full text, unchanged, split into scenes at natural boundaries. Target 30–90 s per illustrated scene; a long scene becomes several stills of the same moment.
   - **Reels:** a 100–125-word (60 s) or 200–245-word (120 s) narration that opens on the story's most striking moment as a ≤8-word hook. It runs one arc and closes back into the hook. Reel narration may condense, but every claim must be true to the book. For a public-domain text, the reel uses the book's own sentences where possible.
3. **Voice (Earnalism Voice).**
   - Profiles: `en_tisha` for English and `bn_arnav` for Bengali stories, per the roster. Explicit routes still apply.
   - The Earnalism Voice is a **fixed Indic Parler-TTS description template plus a direction method**, not a new voice. It is: "warm, intimate storyteller; unhurried (~115–130 wpm); quiet wonder; drops pitch and slows slightly for reveals; brief held breath before turns; dialogue coloured by small shifts in pace and intensity, not character impersonation".
   - Direction maps only to controls Parler actually supports (the description text, sentence grouping and pauses inserted in the edit). Never add spoken words.
   - Dry masters are generated per unit with context carried across units, and the narration is frozen before timing is measured.
4. **Score.**
   - **Default:** the existing cleared original-composition route (VCSL CC0 piano/harp, `editorial_score.py`).
   - **Richer theme colour (strings, flute, tanpura/sitar textures):** ACE-Step generates short instrumental cues in Colab from a theme brief. The cues are retained with seed and prompt, then arranged by the score skill.
   - **Mix:** cues placed at measured boundaries, ducked about 18–20 dB under speech, silence at turns; −14 LUFS for reels and −16 to −19 LUFS for the film, true peak ≤ −1 dBTP.
5. **Visuals.**
   - Each title gets one **world bible**: period, place, palette, light, lens, and character sheets with fixed descriptions. It also gets 2–3 anchor stills generated with FLUX.1-schnell in Colab and reused as references.
   - **Film:** one keyframe still per scene beat (roughly one per 8–15 s of narration), all from the bible and anchors. Gentle motion is done locally in Claude's container with no GPU: slow push-in or parallax layers (foreground and background split), light and particle drift, and cross-dissolves on narration boundaries. The style is consistent illustrated cinema, so the film never claims character acting.
   - **Reels:** a shot list at one shot per 5–7.5 s, with keyframes from FLUX. Each shot is animated with Wan 2.x image-to-video in Colab using the `l4-balanced-v2` profile, or an A100 profile if the forecast allows. Takes are chained last frame to first frame, re-anchored every 2–3 shots, and the final clip ends on the first keyframe for the loop. Generator audio is muted.
   - **QC:** contact sheets on every clip, checking anatomy, identity drift, stray text and continuity. Fix only failing shots.
6. **Assemble.** Assembly runs in the container (ffmpeg, plus Remotion where useful).
   - **Film:** stills with motion, narration, score, subtitles, the approved Earnalism logo lockup and the approved END.
   - **Reels:** clips, narration and score with no on-screen text. Each reel gets its own 9:16 composition and a loop check that the last frame matches the first.
   - Each rendition is hashed and measured.
7. **Review.**
   - One candidate-bound review per deliverable: opening, every join, the climax and the full ending.
   - Automated checks, all advisory only:
     - ASR comparison of narration against the source to catch missing or repeated words;
     - loudness and peak;
     - speech masking;
     - contact sheets.
   - Unperformed listening is marked as unassessed.
   - The owner reviews the first package of each title before release.
8. **Publish (only when told, only where told).**
   - **Maison:** stage audio/video into the edition's draft revision through the production-handoff route, validate, then publish under the existing gates, which require audio/video clearance.
   - **Social:** private-stage first through the official adapters, then post publicly only to the platforms named in the owner's instruction.
   - Captions and copy follow the reels caption rules (hook line plus emoji, the script, about 5 hashtags including `#earnalism #learnalism #theearnalism`).

### Compute budget (planning numbers, re-measured per run)

| Stage | Where | Approx. Colab cost per title |
|---|---|---|
| Narration, 15–25 min of Parler audio | Colab GPU | ~1–2 h on T4/L4 → ~2–10 CU |
| FLUX-schnell stills, ~60–120 film + ~30 reel keyframes, 4 steps | Colab GPU | ~0.5–1 h → ~3–5 CU |
| ACE-Step cues, optional, ~10 short cues | Colab GPU | ~0.5 h → ~2–3 CU |
| Wan 2.x reel clips: 2 reels × ~15 shots × 2 takes at the balanced profile | Colab GPU | the largest cost; forecast from measured s/step before each batch, roughly 20–40 CU |
| Film motion, assembly, mixing, QC | Claude container (CPU) | 0 CU |

That works out to roughly 30–60 CU per title, so about two titles a month inside Colab Pro. If the forecast exceeds the remaining allowance, the skill cuts reel takes or shots first. It never silently lowers quality settings on a job that is already prepared.

### What success looks like

- The owner watches the first বিচারক or Selfish Giant package and judges the reel comparable in viewer experience to the Squint benchmark: hook, voice, pacing, music and visual consistency.
- The film plays end to end on Maison with correct narration, synced subtitles and no masked speech.
- No new spend appears on any account.


## Owner answers to the builder check (23 Nov 2026)

1. **Colab is run by the owner (1a).** The skill prepares each Colab job (a self-contained notebook section plus an input bundle with hashes). The owner runs it in Colab Pro and leaves outputs in the agreed Drive folder, then the skill imports and hash-verifies them. Claude driving Colab through a connected browser is a later add-on, not part of this build.
2. **Standing compute allowance: yes.** Up to **60 Colab compute units per title and 100 per calendar month**. Each GPU batch is forecast before it runs, from measured seconds per step, decode and export, plus a 15% margin. Batches that would cross either cap are cut down (fewer reel takes, then fewer shots) or held for the owner. Never retried past the cap. Spend is logged in the production record.
3. **Hosting cost: unsure.** Treated as unresolved:
   - **Maison video via Cloudflare Stream is held** until the owner confirms Stream's per-minute storage and delivery cost is within budget. The film is still produced, reviewed and posted to the social destinations the owner names.
   - **Maison audio is allowed:** chapter MP3s plus measured timing maps, through the existing private R2 intake. R2 is already in use for covers and reader packages, and a title's audio is tens of MB. *Builder's call; the owner may veto.*
4. **Clearance and music: yes to all.**
   - For public-domain titles, the owner pre-authorises the same clearance pattern used for Reader (`docs/evidence/publication-clearance-20261123.json`), extended to the **audio and video** formats. The skill still writes a per-title evidence record:
     - term per territory;
     - text-source licence;
     - cover provenance;
     - generator and music licences;
     - asset hashes.

     It binds that record to the exact revision and assets, then sets `publication_clearance` for the offered formats. Non-public-domain titles are out of scope.
   - ACE-Step output is accepted for commercial use. Its record carries model revision, licence, seed, prompt and output hashes, alongside the existing VCSL route.

## Builder-check items settled as the builder's call

- **Reel loop close.** The Wan 2.2 TI2V-5B route that has been qualified cannot target an end frame. The loop closes in the edit with a designed match-cut, or a short dissolve from the last shot into frame 1 where the action resolves back into the hook image. The loop QC checks that this transition reads as continuous, not that the pixels are identical.
- **Earnalism Voice.** The pinned Parler roster descriptions (`en_tisha::story`, `bn_arnav::story`) stay byte-for-byte. The Earnalism Voice adds only controls that are compatible with them:
  - sentence grouping;
  - pauses inserted in the edit;
  - per-unit context;
  - at most a short pace or intensity clause appended where the preset's qualification allows it.

  Owner review of the first package counts as that title's listening assessment. Dimensions it doesn't cover stay marked unassessed.
- **Reel visual baseline.** Shots use the `l4-balanced-v2` profile (512×896, 24 steps), upscaled to 1080×1920 with ffmpeg lanczos plus mild sharpening. No new upscaler licence is needed. The hook shot may use the 704×1280 detail profile when the forecast fits the allowance.
- **Long books.** If narration would run past about 40 minutes, the film becomes a chapter-by-chapter series: one film per chapter or unit, sharing one world bible, voice and score palette. Reels draw from the whole book.
- **Maison formats.** Audio is offered as chapter MP3s with measured timing maps. Video is offered per unit only once Stream hosting is confirmed (owner answer 3). Access defaults to `free`, matching the Reader offering for these titles, unless the owner says otherwise.
- **AI disclosure.** Reels carry a small "AI-generated visuals" label for the first 3 seconds, placed in the safe area. This follows India's 2026 IT Rules disclosure requirement, as recorded in the `earnalism-reels` compliance reference, and is the only on-screen text. The film credits AI-generated illustration in its end card and description.

## Left to the builder

- **Assembly tooling.** Exact ffmpeg filter graphs, and whether Remotion or plain ffmpeg does the film motion.
- **Colab.** Exact cells, plus checkpoint revisions pinned at the time of build.
- **FLUX settings.** The prompt template wording, and the scheduler and steps within the schnell licence.
- **Scene splitting.** Thresholds within the 30–90 s target.
- **Skill copy.** Reference file wording, following writing-skills conventions.

## Owner amendment, 24 November 2026: film hosting

The owner chose to host full films on Maison from the private R2 bucket instead of Cloudflare Stream, and to use YouTube and the other named social destinations for reels, Shorts and trailers that point to Maison. Where this document holds Maison video until Stream's cost is confirmed, that hold is replaced by this decision: films are served as progressive MP4 through a short-lived signed R2 GET after an entitlement check, with no caching (`contracts/cache-policy.json` `private_r2_film`). Publication still needs the owner's instruction naming the destinations, and the 47-region policy still applies.
