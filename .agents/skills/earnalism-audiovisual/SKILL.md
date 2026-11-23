---
name: earnalism-audiovisual
description: Use when the owner names a book (English or Bengali) and wants its audiobook film, story reels or audiovisual package, says "make the audiovisual of <title>", asks for a Squint-style reel of a book, a narrated illustrated film, Earnalism Voice narration with a score, or asks to continue, import, assemble, check or publish an existing audiovisual production record for a title.
---

# Earnalism audiovisual (single entry point)

One instruction ("Make the audiovisual of বিচারক") becomes one reviewable package:
a full-length **audiobook film** (illustrated scenes, gentle motion, Earnalism Voice,
theme-fit score, SRT subtitles) and **one or two Squint-grade story reels** (1080×1920,
60 s or 120 s). Zero extra spend: Claude plans, assembles and checks; the owner runs
each GPU job in the existing Colab Pro account.

**Core principle:** this skill *conducts*; it does not replace. Every stage is owned by
an existing Earnalism skill, every gate is enforced by the `eav` CLI, and the CLI's
`Next:` line is the only next step. Read it, do it, run `status` again.

Binding authority: `docs/superpowers/specs/2026-11-23-earnalism-audiovisual-design.md`,
`docs/EARNALISM_AUDIOVISUAL_PIPELINE.md`, `AGENTS.md`. They win over anything here.

## Run the CLI

```sh
cd skills/earnalism-audiovisual/software
python3 -m eav.cli status --root <title root>      # prints the next owner action
```

Commands: `init`, `plan`, `job`, `import`, `film`, `reel`, `qc`, `status`, `bundle-audio`
(usage in `eav/cli.py`). Exit codes: 0 ok, 2 stop, 3 budget exceeded, 4 import held,
5 QC failure. A non-zero exit is a decision, not a glitch: never re-run it with edited
inputs to get past it.

## Stage order and who owns each stage

| # | Stage | CLI | Delegated skill (read it for the stage) |
|---|---|---|---|
| 1 | Resolve exact edition and cleared text | server: `python manage.py export_audiovisual_source <slug> --out src.json`; then `init src.json --root <dir> --slug <slug>` | `earnalism-book-production` |
| 2 | Read the whole work; context map (speakers, turns, reveals, ending) | `plan` (30–90 s scenes, 1 still per 8–15 s; series past 40 min) | `earnalism-audiobook-go-live` (`references/narrative-performance.md`) |
| 3 | Earnalism Voice narration (dry, frozen before timing) | `job narration` → owner runs Colab → `import` | `earnalism-audiobook-go-live` |
| 4 | World bible, anchor stills, film keyframes (FLUX.1-schnell) | `job stills --spec` → Colab → `import` | `earnalism-video`, `earnalism-covers` (cover/thumbnail) |
| 5 | Score: VCSL editorial route by default, ACE-Step cues for colour | score bed or `job music` → Colab → `import` | `earnalism-audiobook-score` |
| 6 | Film assembly (measured timing, ducked mix, motion, logo, END) | `film` | `earnalism-video` |
| 7 | Reels: script, keyframes, Wan clips, narration, assembly | `reel N --script`, `job stills/reel_clips/narration --reel N`, `reel N` | `earnalism-video` (Wan22 route) |
| 8 | Review: automated checks, contact sheets, owner review | `qc`; owner watches the first package | `earnalism-book-audiovisual` |
| 9 | Publish, only when told and only where told | `bundle-audio` → Maison `attach_audiovisual_audio stage|publish`; social private staging | `earnalism-book-audiovisual`, `earnalism-book-production` |

Recipes: [film](references/film-recipe.md), [reels](references/reel-recipe.md),
[voice](references/earnalism-voice.md), [free stack](references/free-stack.md),
[budget](references/compute-budget.md), [record](references/production-record.md),
[publishing](references/publishing.md). Pressure scenarios this skill must pass:
[references/pressure-tests.md](references/pressure-tests.md).

## Stop conditions (exact behaviour)

| Condition | What you do | What you never do |
|---|---|---|
| **No cleared source** (no export, missing text/hash, title not imported) | Stop. Say which edition is missing what. Route to `earnalism-book-production`. | Fetch or type the text yourself, pick another edition, "start with the reels". |
| **Non-public-domain title** (`public_domain_evidence` false) | `init` refuses. Hold the title; it is out of scope. | Draft clearance for it, or produce social reels of it anyway. |
| **Audio format not cleared on Maison** (only Reader read/preview) | Keep producing: film, reels and review need no Maison grant. `bundle-audio` drafts the per-title evidence; the owner completes and approves it; only then `stage`. | Write `publication_clearance` or rights rows by hand, call the draft "cleared", or publish audio before stage + fresh browser report. |
| **Budget exceeded** (exit 3: forecast over 60 CU per title for its whole life, or 100 CU per calendar month) | Stop. For `reel_clips`, cut takes, then shots, in the spec as the CLI suggests and re-forecast. Anything else: hold for the owner. | Lower steps/resolution of a prepared job, split a job to slip under the cap, shrink measured rates, edit, reset or swap the ledger pinned at `init`, use another Colab account, or spend money. |
| **Import held** (exit 4: missing, extra or mismatched file) | Re-download the complete output of that exact job and re-run `import`. | Rebuild/rerun the GPU job, copy files in by hand, or edit `manifest.json`. |
| **QC failure** (exit 5: loudness, true peak, loop close, size, narration longer than clips) | Fix only the failing item (one shot, one still, the mix), re-assemble, re-run `qc`. | Lower a gate, trim narration, or call unheard audio "reviewed". |
| **Stream video held** | The film goes to owner review and to social destinations the owner names. Maison gets audio only. | Upload video to Maison/Stream; `attach_audiovisual_audio` refuses it anyway. |

## Non-negotiables

- **Words.** Film narration speaks the book's exact text, every unit once. Reels may
  condense, but every claim is true to the book; prefer the book's own sentences.
- **Voice.** `en_tisha::story` for English, `bn_arnav::story` for Bengali, description
  byte-for-byte from the roster plus at most one clause of ≤ 12 words. No new voice
  search, no impersonation, no spoken stage directions.
- **Models.** Only Indic Parler-TTS, FLUX.1-schnell, Wan 2.x, ACE-Step (Apache-2.0) and
  VCSL samples (CC0). MusicGen (CC-BY-NC weights) and FLUX.1-dev (non-commercial) are
  forbidden even if the owner names them; offer the licensed equivalent instead.
  No paid generator or credit-spending connector (Kling, ElevenLabs, Suno, Runway,
  Adobe/Canva credits): not for "just one test" either.
- **Colab.** The owner runs every job; bundles are inert until `RUN = True`. Claude
  never claims a GPU run it did not import and verify.
- **Listening.** Automated checks are advisory. Owner review of the first package is
  the listening assessment; anything not reviewed stays `unassessed`.
- **Publishing.** Only after an explicit owner instruction naming the destination.
  A finished package, a Maison release or "go live" for Reader does not authorise
  social posting.

## Red flags: stop and re-read the table above

- "The owner pre-authorised public-domain clearance, so I can mark audio cleared."
  (Pre-authorisation covers the *pattern*; the per-title record still needs completing
  and the owner's approval before `stage`.)
- "70 CU is only a little over; the month still has room." (The title cap is 60.)
- "I'll drop Wan to 16 steps so it fits." (Never lower a prepared job's quality.)
- "MusicGen sounds better and it's free." (Free to run is not free to publish.)
- "The import mismatch is just one file; I'll copy it over." (Held means held.)
- "The reel is basically the film's best minute, cropped." (A reel is its own 9:16
  composition.)
- "Colab is slow, I'll simulate the WAVs to finish the package." (Fixtures never become
  release media.)

## Rationalizations

| Excuse | Reality |
|---|---|
| "The owner wants it live today." | Speed comes from following `Next:`; gates are the owner's own rules. |
| "Reader is already cleared, audio is the same text." | Audio is a separate offered format with its own evidence and rights rows. |
| "I'll reserve later, the forecast is rough." | Forecast first from measured rates; the ledger reserves before anything is written. |
| "Retrying the failed clip once is fine." | A retry past the forecast is spend the owner did not approve. Cut or hold. |
| "The waveform looks fine, call it reviewed." | Measurement is not listening. Mark unassessed. |
