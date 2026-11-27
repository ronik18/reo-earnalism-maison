# Earnalism cinematic film upgrade: design

Status: APPROVED by the owner, 27 Nov 2026. The owner's instruction was "go ahead with the design document for the full upgrade and enhance all of our respective skills permanently"; the open questions were answered as recorded below. It amends `2026-11-23-earnalism-audiovisual-design.md`, including that design's 24 Nov owner amendment on film hosting. Where the two differ, this document wins for the film, the narration and the score. Everything not mentioned here stays as written there.

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

### 8. Film-wide rules enforced by `eav qc` (from the 27 Nov audio-visual re-review)

- **R1 New information.** No stretch longer than 6 s without a new subject, action or composition. A camera glide alone does not count.
- **R2 Shot density.**
  - At least one shot per 6 s of narration.
  - No shot over 8 s unless it contains a performed action.
- **R3 Peak.** One marked peak per scene, placed at 70–85% of the way through, with:
  - a preceding shot that motivates it (a planted image paid off at the peak);
  - at least 4 s on screen;
  - a mark in the sound (silence or a synced effect).
- **R4 Sound matches picture.**
  - Every visible sound source is heard, and day or night ambience matches the picture.
  - Each scene ends with a J- or L-cut into the next.
- **R5 Captions.**
  - On by default, muxed as a subtitle track, with a burned-in rendition on request.
  - At most 2 lines, at most 42 characters per line, 1–7 s per cue.
  - At most 15 characters per second for Bengali.
- **R6 Character lock.**
  - Every on-screen person has a world-bible entry and an anchor still.
  - An automatic check against the anchor covers eye colour and count, mole, jewellery and sari border.
- **R7 Fidelity.** No frame contradicts the current or neighbouring scene's text. Example: a "shut carriage" has no open window.
- **R8 Motifs.** Each scene reuses at least one motif from earlier, changed (the empty bed, the birdcage, the slats).
- **R9 Opener, closer, disclosure.**
  - 0.5–1 s of breath before the first word.
  - A title card ("বিচারক — রবীন্দ্রনাথ ঠাকুর").
  - Closing credits naming the author, the narration voice, and that the images and narration are AI-generated, before the logo lockup.
- **R10 Audio and safety.**
  - Film master at −16 LUFS ±1, true peak ≤ −1.5 dBTP.
  - At most 3 flashes per second.
  - Luminance jumps over 25% only on a deliberate cut.
- **R11 Paper edit first.** Each scene's two-column AV script, shot list and compute budget are approved, with a stopwatch pass, before anything is generated.

### 9. Listen: the audiobook (from the 27 Nov Listen re-review)

- **Narration fixes in `eav`:**
  - Takes render with tails of at least 400 ms, cut only in silence, with 30–50 ms crossfades. No take ends at speaking level.
  - Continuous room tone at −62 to −68 dBFS; digital zero is never allowed.
  - Joins matched to within 1.5 LU and ±1.5 semitones of the book median.
  - Pause lengths by punctuation (as in section 4), each varied ±15%. A পরিচ্ছেদ heading gets 2.5–3 s before it and 1.5 s after.
  - The redo check from section 4 adds:
    - last 50 ms above −50 dBFS;
    - brightness within ±2 dB of the book median;
    - phrase-end pitch spread of at least 3 semitones over 45 s;
    - at least 95% of । followed by a pause of 0.45 s or more.
- **The audiobook gets its own master, separate from the film:**
  - −18 LUFS ±1, true peak ≤ −2 dBTP after encoding, loudness range 4–8 LU, mono 64 kbps, encoded once from PCM.
  - Music only for the intro, outro and part changes. Any bed sits at least 24 LU under the voice with a 6 dB duck and 1.5 s release, never pumping in pauses.
  - Opens with the title and author; ends with 3 s of tail, "সমাপ্ত" and room tone.
- **Chapters and sync:** পরিচ্ছেদ chapter markers in the bundle; sentence-level timing maps (not paragraph-only) so the reader and player can follow along.
- **Player (frontend lane, `client/player.tsx`; proposed, needs owner approval as a design-behaviour change):**
  - on-screen −15 s and +30 s buttons, at least 44 px;
  - playback speed remembered between sessions;
  - full Media Session: artwork, author, part, lock-screen position and previous/next part;
  - a sleep timer driven by playback time, with a 15 s fade and "end of part";
  - a parts list;
  - text-follow highlighting;
  - the position-conflict prompt shows both positions;
  - Bengali labels and digits in the Bengali UI.

### 10. Read: the reader (from the 27 Nov Read re-review; frontend and backend lanes)

The typography is excellent and stays: Noto Serif Bengali 20 px, line-height 1.8, correct conjuncts and old spellings. The following changes are proposed and need owner approval as design-behaviour changes to the approved reading-room design (`2026-11-22-reading-room-all-screens-design.md`):

1. **Night first.** The reader theme defaults to the system's dark setting. The theme reaches the header, and the logo dims in dark themes.
2. **Immersive chrome with progress.**
   - One toolbar that hides on scroll down and returns on tap or scroll up, replacing the duplicated Back/title.
   - A 2 px gold progress hairline, minutes remaining, and a পরিচ্ছেদ drawer.
3. **A live "Reading comfort" bottom sheet.**
   - A−/A+ steppers, theme swatches, and Narrow/Medium/Wide. Changes apply live, with no save button.
   - "Justified" hidden for Bengali.
4. **A preview ending that converts.** The exact free sign-in path ("Sign in free to finish বিচারক — your place is kept"), the remaining length, and Listen/Watch alternatives.
5. **Visible cross-format journey.**
   - A Read · Listen · Film row on the title page, including "coming soon" states.
   - One Read/Listen/Watch switch in the reader that keeps the reader's position.
6. **Small fixes:**
   - on mobile, the primary action above the fold, with length and parts;
   - Latin-script search ("bicharak" finds বিচারক);
   - `lang="bn"` on the header title.

## Reference scene: বিচারক scene 14 v4 (the standard every scene is held to)

**Spine:** Hem, sleepless in a shut carriage, realises that morning will bring shame to her home.

It runs 55.5 s in 11 shots, about one shot per 4.7 s. The voice starts 0.85 s in.

The scene plants **Hem's own bed, empty** early. Sunlight later crawls onto the empty pillow, and that motivates the peak: the mother drops the pot on a hard cut into silence.

Shots:
- the night lane;
- a daughter asleep;
- Hem's empty bed;
- Hem's close-up in the shut carriage, with slats of moonlight (animated: she turns into the light, one slow blink);
- the mother sweeping, pausing toward Hem's door (animated);
- the paan-making place from scene 13, with Hem's place empty;
- Hem's eye at the slat, match-cut to the sunrise wall;
- sunlight onto the empty pillow;
- the mother's discovery (peak);
- neighbours gathering, with murmur and a distant wail, colour draining, and carriage wheels bridging into scene 15.

New material: 4 stills, 2–3 animated clips, CC0 ambience (crows, broom, crowd, wheels).

The pilot files and the two-column AV script are kept in `production/audiovisual/bicharak/pilot/`.

## Rollout

1. Owner approves this design.
2. The implementation plan (superpowers:writing-plans) puts the spike code (glide3, compose3, mix3, retime, fx3) into `eav` with tests. It also updates `SKILL.md`, the references and the job templates, keeping the mirror byte-identical.
3. Re-render বিচারক at the new standard (about 22 CU, spread over December). Then do The Selfish Giant.
4. Review each film frame by frame, then owner approval, new clearance hashes, and staging.

## Builder-check items settled as the builder's call (27 Nov)

- **Reference scene status.** Scene 14 v4 is a target, built first. Its 4 stills are staged as `stills-pilot4-f01s014`, its 2–3 Wan clips follow, and it must pass the owner before the spike code is ported. Tests pin to its measured outputs.
- **Shot density (sections 1 and 8 reconciled).**
  - shots = max(ceil(narration s / 6), beats);
  - 4–8 s per shot, up to 12 s only when the shot holds a performed action.
  - R2 is the rule; section 1's "/7" is superseded.
- **Voice thresholds.** One narration feeds both the film and the audiobook, so the stricter section 9 limits apply to both: joins within 1.5 LU and ±1.5 semitones, 30–50 ms crossfades. Section 4's looser numbers are superseded.
- **Film animation jobs.**
  - A new `film_clips` job kind, separate from `reel_clips`.
  - Batches sized to one Colab session (≤70 min wall clock, the notebook's own hard stop); A100 is preferred when offered.
  - Per-clip resolution is set in the shot list: 1280×704 for faces, hands and climax beats; 896×512 for environments.
  - The forecast passes `budget.forecast` within the title and month caps. Once the owner approves the scene's paper edit, no per-batch signature is needed.
  - The reel rules (≤5 clips, 2,700 s, a signed authority file) stay as they are for reels.
  - Resume is journalled: completed clips are kept, and a rerun skips them.
- **Detection models for the automatic gates.** Apache-2.0 only, verified on each model card at run time, and run in Colab next to the stills:
  - MediaPipe Face Landmarker and Hand Landmarker for eye count, hand count and detached hands;
  - OWLv2 open-vocabulary detection for anachronisms;
  - a CLIP-image similarity check against the anchor still for character lock.
  
  Where a model can't decide, the gate makes a contact sheet for a person; an unclear result never counts as a pass.
- **CC0 sound.**
  - Wikimedia Commons CC0 or public-domain files, fetched in Colab: the API needs no key, and the licence is read per file and recorded.
  - Otherwise original synthesis dedicated to CC0.
  - Freesound is not used (it needs a key).
- **Lane scope.**
  - This upgrade's implementation plan covers the `eav` media work and the audiobook master, timing data and chapter markers.
  - Bundle-contract changes (sentence-level timing maps, chapter markers) go to root as interface notes.
  - Sections 9 (player) and 10 (reader) are owner-gated frontend and backend work. They get their own plan once approved.

## Owner decisions, 27 Nov 2026

1. **Compute: (a).** বিচারক's lifetime cap rises from 60 to **100 CU**, and the 100 CU monthly cap stays. Budget code makes per-title caps configurable; the default stays 60 for other titles.
2. **Read and Listen UX (sections 9–10): approved now.** They get their own plan, run by the frontend and backend lanes in parallel with the film work.
3. **Paper-edit approval (R11):** Claude plus an independent reviewer approve each scene's paper edit. The owner approves the reference scene (scene 14 v4) and each finished film.

### The questions as asked

1. **Compute for the বিচারক re-render** (the builder's top finding).
   - At the new density the film is about 275 shots. With about 25–35% animated and 1.3 takes each, that's about 90–125 clips.
   - On A100 (about 0.27 CU per HD clip) that's about 25–34 CU; on L4 (about 0.6 CU) about 55–75 CU. Stills add about 5 CU.
   - বিচারক has about 23.9 CU left under its 60 CU lifetime cap.
   - Options:
     - (a) raise বিচারক's lifetime cap to 100 CU; the Colab balance is about 418 CU, and the 100 CU monthly cap still applies;
     - (b) animate only peaks and named actions, about 12% of shots, about 20 CU;
     - (c) spread the film over two titles' worth of caps.
2. **Read and Listen UX (sections 9–10):** approve them now as part of this upgrade, or as a separate project after the films?
3. **Paper-edit approval (R11):** I and an independent reviewer approve each scene's paper edit, and you approve the reference scene and each finished film. Or do you want to approve every scene's paper edit yourself?
