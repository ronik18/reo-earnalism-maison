# Earnalism cinematic film upgrade: design

Status: DRAFT for owner approval. It amends `2026-11-23-earnalism-audiovisual-design.md`, including that design's 24 Nov owner amendment on film hosting. Where the two differ, this document wins for the film, the narration and the score. Everything not mentioned here stays as written there.

## Intent

The owner rated the first বিচারক film 6/10 (26 Nov 2026):

> "The animations are too static whereas the expectation is to make it smoothly transitioned scene per scene to create like a movie and cinematic experience for the book's content. The audio still has some mechanical/robotic texture in specific areas ... make it fully natural human, dramatically expressive and story-telling."

A book's film should feel like a hand-crafted animated short of the story, not a slideshow. Its narration should be one a listener would take for a human storyteller.

It must stay cheap enough to repeat for every title: about 20 Colab compute units and 20,000 ElevenLabs credits per 20-minute film.

Three pilots of বিচারক scene 14 tested and refined the method:
- v1 (26 Nov), three shots;
- v2, eight shots with two voices;
- v3, which fixed every defect a frame-by-frame review found.

This design makes that method the permanent production standard, and folds in the owner's re-review of the Read, Listen and Watch experiences.

## Goals

1. **Picture: a moving, story-led film.**
   - A beat-locked shot plan: one picture per phrase group, 4–12 s per shot, which removes the old 13–17 s stills.
   - The camera always moves, through layered depth glides.
   - Real animation only where the text names an action or where life matters (cloth, flame, water, a gesture).
   - Transitions that carry motion: dissolves between layers of time or imagination, hard cuts and match cuts inside a layer.
2. **Voice: natural, dramatic Bengali/English storytelling.**
   - The model is **Eleven v4** (owner choice, 26 Nov).
   - **One take per passage, redoing only the takes that fail the automatic check** (owner choice, 26 Nov).
   - Pauses are re-timed by punctuation and filled with real room tone.
3. **Score: a cue written for each scene, never a slice of another scene's cue.**
   - Drone, solo and phrase stems are placed at the cut times.
   - Purposeful silence at turns.
   - About 17 dB under the voice, in stereo.
4. **Sound: ambience and foley in every scene,** with a licence on file for every sound: CC0 field recordings, or original synthesis dedicated to CC0.
5. **Quality gates catch defects before the owner sees them:**
   - anatomy (eyes, hands);
   - character lock;
   - anachronistic objects;
   - motion artefacts;
   - edit continuity;
   - audio masking and loudness.
6. **Skills evolve permanently.** The methods, numbers and gates in this design go into `earnalism-audiovisual` and the stage skills it conducts, with tests. The next title then starts at the pilot-v3 standard without this conversation.

## Non-goals

- Full character animation of every moment. The owner chose (b), "one real animated moment per shot plus camera movement for the rest", and option (a) is over budget.
- Lip-synced talking characters (HeyGen-style). They are paid, they don't fit narrated prose, and they risk faces looking wrong.
- Training a style or character model per book. The character look lock is tried first.
- New paid services. Colab (existing units) and ElevenLabs (Creator plan credits) only.

## Anti-goals (a failure even if it "works")

- A picture that contradicts the words under it, including a still borrowed from another shot ("holds").
- A face that loses an eye or shows extra or detached hands, or an object that flies without cause.
- A modern object in a period world (gas cylinders, AC boxes, cables, modern glasses or belts).
- Music borrowed from another scene's cue; music that pulses, masks the voice or pumps.
- Digital-silence gaps in narration.
- Re-rendering a whole film to fix one shot.

## Constraints

- **Compute:**
  - Colab is capped at 60 CU per title for its lifetime and 100 CU per month.
  - Measured rates:
    - Wan 2.2 TI2V-5B, 1280×704 at 24 steps: 880–912 s per clip on L4, 212 s on A100.
    - 896×512: 405–434 s on L4.
    - FLUX stills: about 10 s each.
    - ACE-Step: 13 s per 60 s stem on L4.
    - Colab session setup: 5–8 min.
- **Voice:**
  - The owner's limit is 60,000 credits per calendar month on the Creator plan; the plan resets on the 23rd.
  - Eleven v4 costs 656 credits for a 47-s Bengali scene take, about one credit per character.
- **Licences** (verified on model cards):
  - Apache-2.0: Wan 2.2 TI2V-5B, FLUX.1-schnell, ACE-Step v1 3.5B, Depth Anything V2 **Small**.
  - Base and Large depth models are non-commercial and excluded.
  - OpenRAIL++ outputs: SDXL inpainting.
  - CC0: VCSL.
  - Owner-approved ElevenLabs Creator commercial licence.
  - BSD-3 models (e.g. Real-ESRGAN) need owner approval and are not used.
- **Network:**
  - The container cannot reach Hugging Face file CDNs or freesound/Wikimedia reliably (rate-limited).
  - Model downloads and CC0 sound fetching happen in Colab.
- **Child depiction:** named minors (e.g. Hem, 14) appear only in dignified close-ups. "Daughters" in general are drawn as grown young women unless the text requires a child.
- **Approved design binding (AGENTS.md):** this design changes the film's technology (adds Wan motion, depth glides and Eleven v4). The owner approved these choices on 26 Nov. This document records them for approval as the new baseline.

## Approaches considered

1. **(chosen, owner 26 Nov) Selective animation, camera on everything else.**
   - Each shot gets a depth glide, an animated beat where the text has an action, and motion-carrying transitions.
   - About 9–23 CU per film, depending on how many shots are animated at the higher resolution.
2. **Animate every moment.** About 100 CU per film. Over the cap.
3. **Camera only.** Cheapest, but still a slideshow.
4. **Voice:**
   - **(chosen)** v4, one take per passage, redo only failures.
   - Alternatives: best-of-three (45k credits per film; rejected on cost), Multilingual v2 (steadier but less dramatic; rejected), patching only flagged spots (leaves the long-take texture).

## Design

### 1. Shot planning (pre-production, the "edit on paper")

The planner turns each scene's text plus the measured narration timing into a **two-column AV script** (time | audio | visual). From it come the numbered shot list and the generation briefs. Rules, all testable in `eav qc`:

- **Shot count and length:**
  - shots = max(ceil(narration seconds / 7), number of beats);
  - each shot 4–12 s;
  - no screen goes more than **6 s without new visual information** (a cut, an animated beat or a reveal in the glide).
- **Cut placement:** cuts land in narration pauses or clause boundaries, about 0.3 s before the key noun or verb, never mid-word.
- **Coverage per scene:**
  - one establishing wide;
  - a close-up of whoever is perceiving or acting;
  - at least one insert of a concrete noun the text names;
  - imagined, remembered or future material bracketed by the perceiver's face;
  - a reaction on emotional verbs.
- **Layers of time:**
  - present, memory and imagined future each get a grade;
  - dissolves only between layers; hard cuts or match cuts inside a layer;
  - the last shot of a scene matches the first light of the next scene.
- **No holds:**
  - a failed still is regenerated or re-planned, never filled with a neighbour;
  - QC rejects a scene whose stills share a file hash.
- **Peak placement:** the scene's emotional peak lands on its key words. Music drops out or changes there, and the edit switches from dissolves to hard cuts.

### 2. Stills (FLUX.1-schnell in Colab)

- Composition-first prompts, with world-bible appearance lines word for word.
- Every recurring person, parents included, gets a bible entry.
- Three candidates per shot; the reviewer picks.
- **Character and period gate** before animation. Automatic plus contact sheet:
  - eye count and both eyes visible in close-ups;
  - iris colour;
  - earrings, bindi and mole as specified;
  - sari border;
  - no anachronisms (cylinders, AC boxes, cables, modern glasses or belts, spotlights, letterbox bars).
- Fixes: a different candidate, a crop or a local inpaint; regenerate only when those fail.

### 3. Motion

- **Depth glide (`eav glide`, CPU, free):**
  - Depth Anything V2 Small depth maps, computed in the same Colab run as the stills.
  - Edge-aware (guided filter).
  - Two layers (near/far by Otsu), with Telea-inpainted occlusions at a 13 px grow.
  - Overscan derived from the move.
  - Ease modes: `in` / `out` / `both` / `none`, so motion carries through dissolves.
  - Single-layer `--flat` for faces and close-ups (no neck shear).
  - Optional sunlight sweep along the painted light direction, and a warm-to-cold drain.
- **Animated beat (Wan 2.2 TI2V-5B, 1280×704, 24 steps):**
  - only for a named action, life in the frame, or a climax gesture;
  - about 25–35% of shots;
  - saved near-lossless (`quality=10`);
  - played at native 24 fps (the film masters at 24 fps, with no interpolation);
  - a continuation clip starts from the previous clip's last frame when an action must last longer than 5 s.
- **Prompt rules:**
  - one concrete physical action;
  - "static locked-off camera" (camera moves come from the glide);
  - the negative prompt lists detached or extra hands, floating or flying objects, blink, closed eyes, morphing eyelids, transparent cloth, and camera movement;
  - emotional close-ups of faces get the glide unless an HD take passes the face gate.
- **Motion gate per clip:**
  - periodic near-duplicate frames;
  - difference spikes;
  - a hands-and-eyes contact sheet every 4 frames;
  - pass, or reject and re-seed.
  - Budget: 2–3 seeds per action shot.

### 4. Voice

- Eleven v4, the title's chosen voice (বিচারক: "Subhajit – Grounded Bengali Storyteller").
- Passages of 15–30 s, split at sentence or paragraph ends. At most one audio tag per sentence; carry the previous mood tag across a join, and never open a passage on a bare `[softly]`.
- **Pause re-timing (`eav retime`):**
  - comma 0.4–0.55 s;
  - । or ? 0.8–1.0 s;
  - an emotional ! before a turn 1.4–1.6 s;
  - scene change 2.0 s.
  - Fill from the take's own room tone, never digital zero; crossfade joins by 10 ms.
- **Automatic redo check** (thresholds from the 26 Nov voice review):
  - duration ±12% of expected;
  - median pitch ±2 semitones of the book's running median;
  - pitch spread at least 3.0 semitones;
  - no 2-s window with pitch spread under 1.5 semitones for more than 20% of the take;
  - no stretch over 9 s without a pause;
  - spectral-jump and click rates within 1.5× of the profile;
  - no digital silence over 50 ms;
  - joins within ±3 semitones and 4 dB.
- **Word check:** Whisper (MIT) character-error check in Colab against the source, relative to accepted takes.
- **Credits:** about 15,000–20,000 per 20-minute film.

### 5. Score

- **One cue per scene** from ACE-Step stems generated to a scene brief:
  - drone, solo and phrase;
  - instrumental, no percussion or vocals;
  - three seeds per stem type;
  - picked by measurement: tonic, onset rate, pulse and low end.
- Stems are high-passed at 90 Hz and placed at the cut times.
- Silence at the scene's peak (the shame cut in scene 14).
- Ducking: 80 ms attack, 400 ms hold, 800 ms release.
- About 17 dB under the voice during speech; stereo throughout.
- Loudness −16 LUFS integrated, true peak ≤ −1.5 dBTP.

### 6. Ambience and foley

- **Per-scene beds:** night insects, dawn birds, crowd murmur and so on, plus action foley timed to motion events (pot, broom, carriage).
- **Sources:**
  - CC0 field recordings fetched in Colab, each with its licence and page recorded;
  - or original synthesis dedicated to CC0, recorded in `sfx/README.md`.

### 7. Assembly and review

- `eav film` builds per-shot clips, cached by hash so one shot can be re-rendered without the rest.
- It joins them with the planned transitions at 24 fps.
- It adds captions, the logo lockup and the AI-disclosure card.
- QC adds:
  - the edit gates (6-s rule, hold hashes, one-frame hitches, black bars);
  - the audio gates (voice-over-music margin, silence at peaks, digital zero, loudness).
- A frame-by-frame review (picture, motion, sound) runs before the owner sees a cut.

### 8. Read and Listen (owner re-review, 27 Nov)

[Filled from the Read and Listen reviews.]

## Rollout

1. Owner approves this design.
2. The implementation plan (superpowers:writing-plans) puts the spike code (glide3, compose3, mix3, retime, fx3) into `eav` with tests. It also updates `SKILL.md`, the references and the job templates, keeping the mirror byte-identical.
3. Re-render বিচারক at the new standard (about 22 CU, spread over December). Then do The Selfish Giant.
4. Review each film frame by frame, then owner approval, new clearance hashes, and staging.

## Open questions for the owner

[Filled after the builder check.]
