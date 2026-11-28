---
name: earnalism-audiovisual
description: Use when the owner names a book (English or Bengali) and wants its audiobook film, story reels or audiovisual package, says "make the audiovisual of <title>", asks for a Squint-style reel of a book, a narrated illustrated film, Earnalism Voice narration with a score, or asks to continue, import, assemble, check or publish an existing audiovisual production record for a title.
---

# Earnalism audiovisual (single entry point)

One instruction ("Make the audiovisual of বিচারক") becomes one reviewable package:
a full-length **cinematic audiobook film** (beat-locked shots, a camera that always moves, real
animation where the text names an action, Earnalism Voice on Eleven v4, a cue and ambience for every
scene, captions) and **one or two Squint-grade story reels** (1080×1920,
60 s or 120 s). Zero extra spend: Claude plans, assembles and checks; the owner runs
each GPU job in the existing Colab Pro account.

**Core principle:** this skill *conducts*; it does not replace. Every stage is owned by
an existing Earnalism skill, every gate is enforced by the `eav` CLI, and the CLI's
`Next:` line is the only next step. Read it, do it, run `status` again.

Binding authority: `docs/superpowers/specs/2026-11-27-earnalism-cinematic-film-design.md` (the film,
narration and score standard; rules R1–R11), `docs/superpowers/specs/2026-11-23-earnalism-audiovisual-design.md`,
`docs/EARNALISM_AUDIOVISUAL_PIPELINE.md`, `AGENTS.md`. They win over anything here.

## Run the CLI

```sh
cd skills/earnalism-audiovisual/software
python3 -m eav.cli status --root <title root>      # prints the next owner action
```

Commands: `init`, `plan`, `scene-timing`, `plan-shots`, `job` (kinds incl. `stills`, `film_clips` with `--resume`,
`music`), `exchange-stage`, `exchange-collect`, `import`, `import-take` (`--accept PID=reason`, `--no-retime` for an
already-retimed take), `split-passages`, `pick`, `adopt` (already-imported media bound to a scene's approved shots,
verified by sha256, 0 CU), `supersede` (never ran), `close` (ran, not imported: settles the actual CU), `glide`, `retime`, `voicecheck`,
`motiongate`, `facegate`, `cue`, `film`, `reel`, `qc`, `status` (`--scene <ID>`: one scene's route; `film --shots --scene`),
`bundle-audio` (`--profile audiobook|film`), `bundle-film`, plus the older `hold`, `touchup`, `clip-touchup`
(usage in `eav/cli.py`; `--help`). Exit codes: 0 ok, 2 stop, 3 budget exceeded, 4 import held,
5 QC failure. A non-zero exit is a decision, not a glitch: never re-run it with edited
inputs to get past it.

## Stage order and who owns each stage

**Cinematic film flow (the standard, [film recipe](references/film-recipe.md)), per scene as `Next:` walks it:** voice (v4 passages, retime, voicecheck, inside `import-take`) → scene-timing → plan-shots (approved) → stills+gates → pick → film_clips (Wan shots, glide depth maps) → music → cue → then film --shots → qc → owner review.
Each scene's paper edit is approved (Claude plus an independent reviewer) before any generation. Media the owner
already picked is adopted, not regenerated (`adopt`, [film recipe](references/film-recipe.md), Adoption). A film with a
shot plan is never assembled without `--shots`; the `eleven_v3` one-take route is for reels and older films.
The table below lists the stages by who owns them.

| # | Stage | CLI | Delegated skill (read it for the stage) |
|---|---|---|---|
| 1 | Resolve exact edition and cleared text | server: `python manage.py export_audiovisual_source <slug> --out src.json`; then `init src.json --root <dir> --slug <slug>` | `earnalism-book-production` |
| 2 | Read the whole work; context map (speakers, turns, reveals, ending) | `plan` (30–90 s scenes, 1 still per 8–15 s; series past 40 min) | `earnalism-audiobook-go-live` (`references/narrative-performance.md`) |
| 3 | Earnalism Voice narration (frozen before timing) | ElevenLabs (owner decisions 24 and 26 Nov 2026): Eleven v4 in 15–30 s passages: `split-passages film-NN` → tagged passage takes → `import-take film-NN` (model id from the title's `voice.json`; retimes and voicechecks each passage, a failed passage blocks its scene's join, at most 3 takes of a passage before the owner decides, `--accept PID=reason` records an override; uncalibrated absolute limits only warn; the scene wav, with its 0.85 s lead-in and 2 s tail, lands at `film/film-NN/voice/<scene>.wav`) → `scene-timing` (measured clauses for the paper edit). Reels and older films: one `eleven_v3` tagged take → `import-take film-NN\|reel-N` → `retime` → `voicecheck`, or a pre-retimed scene wav placed by hand. Parler: `job narration` → owner runs Colab → `import` | `earnalism-audiobook-go-live`, `references/earnalism-voice.md` |
| 4 | World bible, anchor stills, shot stills with gates (FLUX.1-schnell; MediaPipe, OWLv2, DINOv2-small gates) | `plan-shots` (approve) → `job stills --spec` (3 candidates per shot, T5 limit enforced) → Colab → `import` → `pick` | `earnalism-video`, `earnalism-covers` (cover/thumbnail) |
| 4b | Animated beats and depth maps (Wan 2.2 TI2V-5B, depth Small only) and CC0 sound | `job film_clips --spec` (items bound to the plan's Wan shots, each chain covering its shot; the picked glide stills' depth maps filled in; one 70-minute session per job, split if longer; `--resume` reserves a cut-short job's rest first) → Colab → `import` (motion gate) | `earnalism-video`, `earnalism-covers` (cover/thumbnail) |
| 5 | Score: one ACE-Step cue per scene (film); VCSL editorial bed for the older route | `job music` (spec `"scene"`, stem `"role"`) → Colab → `import` → `cue --scene --pick` (within each stem family), `cue --scene --fx` (every sound with its licence record) | `earnalism-audiobook-score` |
| 6 | Film assembly (24 fps, measured timing, scene mixes, glides and clips, captions, logo, END) | `film --shots` (picked stills only; prints and records every Wan take the motion gate wants reviewed); `film` only for older films without shot plans | `earnalism-video` |
| 7 | Reels: script, narration (measured), shot plan, keyframes, Wan clips in batches of ≤ 5, assembly | `reel N --script`, `job narration --reel N`, `reel N --plan-shots`, `job stills --reel N`, `job reel_clips --reel N` per batch, `reel N` | `earnalism-video` (Wan22 route) |
| 8 | Review: automated checks, contact sheets, face close-up sheets, the minute anomaly review (below), owner review | `qc` (incl. the `faces` gate, `qc/<scene>-faces.jpg`); owner watches the first package | `earnalism-book-audiovisual` |
| 9 | Publish, only when told and only where told | `bundle-audio` → Maison `attach_audiovisual_audio stage|publish`; social private staging | `earnalism-book-audiovisual`, `earnalism-book-production` |

Redone stills: prompts are positive-only (the builder refuses `no`, `not`, `without`, …;
describe what is there). Each redone shot gets `"candidates": 3` in its spec item → Colab makes
`<key>--c1..c3.png` → `import` → a reviewer checks every candidate at full size → `pick --job
<stills job> --choices <{"<key>": N} json>` → `film` uses only the picked files (as `<key>.png`)
over the base set; an unpicked candidates job adds nothing ([visual style](references/visual-style.md)).

Retouch (a chosen still right except a small forbidden detail: bindi, ear studs, beard, wires):
`job retouch --film N --spec retouch.json` redraws only text-masked regions of that imported still
with open-licence SDXL inpainting (CLIPSeg masks; the notebook refuses a model card licence outside
`openrail++`/`apache-2.0`/`mit`). Region prompts are positive-only; `find` texts are mask queries.
It returns `<key>--cN.png` candidates plus `<key>--mask.png` for review → `import` → `pick --job
<retouch job>` → `film` patches the pick; masks never enter the film (visual style, Retouch).

Touch-up (small, local defects a mask query keeps missing): `touchup --film N --spec touchup.json
--job-id ID` repaints hand-placed boxes locally with OpenCV (inpaint, recolor, fill, clone; no
model, no Colab) → `<key>--c1.png` + `<key>--mask.png` → open both at full size → `pick --job ID`
→ `film` patches the pick; with spec `"scene"` the pick is that scene's shot still (licence inherited only from a
verified source; `film --shots` needs its reason in `picks/gate-overrides.json` and face-gates it; visual style, Touch-up).

Clip touch-up (a small fixed defect in an imported Wan take, e.g. an LED-like glow between slats):
`clip-touchup --film N --spec clip-touchup.json --job-id ID` repaints one recorded mask in every frame
with OpenCV (fill along a direction, or inpaint; no model, 0 CU) into a NEW clip; the record keeps the
reason and the sha256 of source and output, and the motion gate runs on the touched clip → look at
`<key>.before/after/mask.png` → `adopt` with `"clips": {"<n>": {"job": "<ID>", "takes": ["<key>"]}}`.

Edit (a held shot drawn wrong in a way a mask cannot fix: a child widow given a bindi or looking
too young, a bearded judge, the Giant at the wrong scale, snow indoors, out-of-season fruit):
`job edit --film N --spec edit.json` runs Qwen-Image-Edit-2511 (Apache-2.0 only; pinned diffusers)
on the imported still with 0–2 reference images and a plain instruction plus a real negative
prompt (the positive-only rule does not apply) → `<key>--cN.png` at the source size → `import` →
`pick --job <edit job>` → `film` patches the pick; a picked edit releases that key's hold (visual style, Edit).

Recipes: [film](references/film-recipe.md), [house visual style](references/visual-style.md), [reels](references/reel-recipe.md),
[voice](references/earnalism-voice.md), [free stack](references/free-stack.md),
[budget](references/compute-budget.md), [record](references/production-record.md),
[publishing](references/publishing.md), [Colab R2 exchange](references/colab-exchange.md). Pressure scenarios this skill must pass:
[references/pressure-tests.md](references/pressure-tests.md).

## Minute anomaly review (before any cut is sent)

The owner found two pupils in one eye at 0:51 of scene 14 v7 (take f01s014-9p, and already in its start still);
earlier, a mole that came and went on Hem, the mother's face gaunt in one take and childlike in another, and a cyan
LED-like glow. Gates catch some of these; a person looking catches the rest. Before sending any cut to the owner,
run `qc` and go through every item below on the face sheet `qc/<scene>-faces.jpg` (face crops ×3, red = flagged;
`film --shots` prints its path), the `qc/` contact sheet and the cut itself at full size, paused, shot by shot:

- [ ] **Eyes**: two per face, one round pupil each, none missing, no extra eyeball; left and right match in size
  and shape; no eye off the face or melting between frames. `faces` fails a double or missing pupil (on a still,
  or held over a take); a shot with a character where no face was judged is listed NOT JUDGED: look at it yourself.
- [ ] **Hands**: five fingers, attached to an arm, nothing fused or floating (the still gate checks attachment only).
- [ ] **Faces**: the same person in every shot at the bible's age (not gaunt here and childlike there); moles and
  marks exactly as the bible says (Hem has none); no face change inside a take. Identity is not measured: look.
- [ ] **Jewellery and costume**: earrings, bangles, bindi or bare forehead, sari border colour as the bible says, the
  same in every shot.
- [ ] **Background**: no glows or LEDs (`faces` lists cyan glows), no text, numbers or letters, no wires, no modern
  objects.
- [ ] **Objects**: nothing duplicated (two pots, a second hand), nothing melting or morphing.

Fix the cause (redo the still or take, `touchup`, `clip-touchup`, `edit`); a fail stands only with the owner's
reason in `picks/gate-overrides.json` as `"faces:<key>"`. Say in the hand-off which items you checked; anything
not checked is `unassessed`. `facegate <clip|still|folder>` runs the gate on any media without a record.

## Stop conditions (exact behaviour)

| Condition | What you do | What you never do |
|---|---|---|
| **No cleared source** (no export, missing text/hash, title not imported) | Stop. Say which edition is missing what. Route to `earnalism-book-production`. | Fetch or type the text yourself, pick another edition, "start with the reels". |
| **Non-public-domain title** (`public_domain_evidence` false) | `init` refuses. Hold the title; it is out of scope. | Draft clearance for it, or produce social reels of it anyway. |
| **Audio format not cleared on Maison** (only Reader read/preview) | Keep producing: film, reels and review need no Maison grant. `bundle-audio` drafts the per-title evidence; the owner completes and approves it; only then `stage`. | Write `publication_clearance` or rights rows by hand, call the draft "cleared", or publish audio before stage + fresh browser report. |
| **Budget exceeded** (exit 3: forecast, or actual units settled at import or close, over the title's lifetime cap (keyed by edition; 60 CU by default, set per title in `title-caps.json` beside the ledger, 100 for বিচারক) or 100 CU per calendar month) | Stop. Hold for the owner with the forecast, the remaining allowance and the CLI's fit (for `reel_clips`: how many of the batch's shots still fit). | Write or edit a spec `compute` block (it is derived and refused if it differs), lower steps/resolution of a prepared job, split a job to slip under the cap (the CLI's own per-session split reserves every part), shrink measured rates, edit, reset or swap the ledger pinned at `init`, init a second root for the edition, use another Colab account, or spend money. |
| **Import held** (exit 4: missing, extra or mismatched file, or an `INCOMPLETE` manifest) | Re-download the complete output of that exact job and re-run `import`. A `film_clips` job its hard stop cut short: `job film_clips --resume <job_id> --from <partial download>` (reserves the rest first), then import with the CU of all its sessions. A job that ran but can never be imported (crash, lost download): `close <job_id> --units <CU Colab shows> --reason "..."`, then hold for the owner. | Rebuild/rerun the GPU job, copy files in by hand, edit `manifest.json`, or `supersede` a job that ran (supersede is for never-run jobs only). |
| **QC failure** (exit 5: loudness, true peak, loop close, size, hook onset, reel narration that does not fit its length ± 3 s; film: R1/R4/R5/R10 gates, per-scene margin, silence at peaks, digital zero on the delivered film, any gate `not_run`) | Fix only the failing item (one shot, one still, one scene's cue or mix), re-assemble (the shot cache re-renders only what changed), re-run `qc`. Reel narration that does not fit: rewrite the script's words, `reel N --script`, new reel narration. | Lower a gate, trim narration, or call unheard audio "reviewed". |
| **Plan not approved / gate fails** (a spec with `"scene"` or `cue` on an unapproved plan; `plan-shots` exit 1 on R1–R3; a certain-fail still or motion gate; a failed passage in `import-take`) | Fix the cause: split the shot, add a continuation, regenerate the still or take, get the independent reviewer's approval. After 3 failed takes of one passage, stop regenerating and ask the owner (`--accept PID=reason` only on the owner's word). | Edit the plan after approval, use `hold`, borrow a neighbouring still or cue, `--override-fail` or `--accept` for schedule, or lower a limit. |
| **Maison film path not built yet** (owner decision 2026-11-24: full films from private R2, see `references/publishing.md`) | The film goes to owner review and is archived to private R2. Social destinations the owner names get reels, Shorts and trailers only. Maison gets audio until its film grant and player exist. | Upload to Cloudflare Stream, post a full film to a social platform, make a film object public, or hand out an unsigned or long-lived R2 URL. |

## Non-negotiables

- **Words.** Film narration speaks the book's exact text, every unit once. Reels may
  condense, but every claim is true to the book; prefer the book's own sentences.
- **Voice.** `en_tisha::story` for English, `bn_arnav::story` for Bengali, description
  byte-for-byte from the roster plus at most one clause of ≤ 12 words. To fix flat,
  robotic delivery: audition first (`job narration --audition audition.json`; candidates in
  `references/storyteller-voices.json`), the owner picks (`OWNER_SELECTED`), then narrate with
  `--voice <pick> --expressive` (grouping, emotion direction, varied pauses; exact text
  kept). Candidates never voice production. No impersonation, no spoken stage directions.
  ElevenLabs route: the owner-picked voice of the title, Eleven v4 passage takes (`split-passages`, `import-take`; model id in `voice.json`) or one tagged-script `eleven_v3` take per scene,
  `import-take` (refuses any script whose words differ from the book).
- **Models.** Only Indic Parler-TTS, FLUX.1-schnell, Wan 2.x (film: 2.2 TI2V-5B), ACE-Step (Apache-2.0), Depth Anything V2 **Small**, the gate models MediaPipe, OWLv2 and DINOv2-small (Apache-2.0), SDXL inpainting 0.1 + CLIPSeg (retouch), Qwen-Image-Edit-2511 (edit, Apache-2.0), OpenCV (touch-up and the face gate, no model), Whisper (MIT) and
  VCSL samples (CC0). MusicGen (CC-BY-NC weights), FLUX.1-dev (non-commercial), Depth Anything V2 Base and Large (non-commercial) and CLIP (card puts deployed use out of scope) are
  forbidden even if the owner names them; offer the licensed equivalent instead.
  No paid generator or credit-spending connector (Kling, Suno, Runway, Adobe/Canva
  credits): not for "just one test" either. The one exception is ElevenLabs narration (the owner chose Eleven v4 on 26 Nov; the CLI imports it with the model id of the title's `voice.json`, and `eleven_v3`) within the plan's included credits (owner decision 24 Nov 2026,
  `references/earnalism-voice.md`).
- **Colab.** The owner runs every job. Narration, stills, retouch, edit, music and film_clips notebooks are inert
  until `RUN = True` and stop at their forecast seconds (hard stop). Their default route
  is the R2 exchange (`exchange-stage` → Maison `presign_colab_exchange` → owner: RUN = True,
  Run all → `exchange-collect`); signed URLs live only in the gitignored `exchange.json`. Reel clips use the
  Wan batch notebook: its own flags plus an authority file
  (`/content/wan22-batch-authority.json`) that **the owner writes and signs. Claude never
  writes, edits, drafts or fills in Wan authority files**, never supplies an observed rate,
  allocation time or approval for one. Claude never claims a GPU run it did not import
  and verify.
- **Listening.** Automated checks are advisory. Owner review of the first package is
  the listening assessment; anything not reviewed stays `unassessed`.
- **Publishing.** Only after an explicit owner instruction naming the destination.
  A finished package, a Maison release or "go live" for Reader does not authorise
  social posting.

## Red flags: stop and re-read the table above

- "The owner pre-authorised public-domain clearance, so I can mark audio cleared."
  (Pre-authorisation covers the *pattern*; the per-title record still needs completing
  and the owner's approval before `stage`.)
- "70 CU is only a little over; the month still has room." (The title's cap is in `title-caps.json`: 60 by default.)
- "I'll drop Wan to 16 steps so it fits." (Never lower a prepared job's quality.)
- "MusicGen sounds better and it's free." (Free to run is not free to publish.)
- "The import mismatch is just one file; I'll copy it over." (Held means held.)
- "The reel is basically the film's best minute, cropped." (A reel is its own 9:16
  composition.)
- "Colab is slow, I'll simulate the WAVs to finish the package." (Fixtures never become
  release media.)
- "I'll write the Wan authority JSON so the owner only has to press Run." (Owner
  evidence is the owner's; Claude prints what it must contain, nothing more.)
- "The job crashed, so it cost nothing: supersede it." (It ran: `close` it with the CU
  Colab shows.)
- "The still failed the gate; hold the neighbour's under it for now." (No holds: regenerate it.)
- "A 9 s push-in is fine, the voice is calm." (R1/R2: split it; a glide adds no new information.)
- "Reuse scene 14's cue under scene 15." (One cue per scene; borrowed music is an anti-goal.)
- "Commons says Public domain, so the sound is cleared." (Worldwide, by the author's own release, or CC0.)
- "I'll start the Colab job with these skill edits uncommitted." (Commit first; the record must name the code.)
- "Put every costume detail in the prompt." (T5 cuts at 256 tokens: character lines first, about 90 words.)

## Rationalizations

| Excuse | Reality |
|---|---|
| "The owner wants it live today." | Speed comes from following `Next:`; gates are the owner's own rules. |
| "Reader is already cleared, audio is the same text." | Audio is a separate offered format with its own evidence and rights rows. |
| "I'll reserve later, the forecast is rough." | Forecast first from measured rates; the ledger reserves before anything is written. |
| "Retrying the failed clip once is fine." | A retry past the forecast is spend the owner did not approve. Cut or hold. |
| "The waveform looks fine, call it reviewed." | Measurement is not listening. Mark unassessed. |
