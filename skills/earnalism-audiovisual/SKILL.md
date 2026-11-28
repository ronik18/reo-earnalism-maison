---
name: earnalism-audiovisual
description: Use when the owner names a book (English or Bengali) and wants its audiobook film, story reels or audiovisual package, says "make the audiovisual of <title>", asks for a Squint-style reel of a book, a narrated illustrated film, Earnalism Voice narration with a score, or asks to continue, import, assemble, check or publish an existing audiovisual production record for a title.
---

# Earnalism audiovisual (single entry point)

One instruction ("Make the audiovisual of বিচারক") becomes one reviewable package:
a full-length **audiobook film** (illustrated scenes, gentle motion, Earnalism Voice,
theme-fit score, SRT subtitles) and **one or two Squint-grade story reels** (1080×1920,
60 s or 120 s). Zero extra spend beyond the owner's Colab Pro account and a Modal
allowance of $30 per UTC month and $6 per title: Claude plans, assembles and checks; narration, stills and
music jobs run either in Colab (the owner runs them) or on Modal (Claude runs `modal-run`);
reel clips run only in Colab.

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

Commands: `init`, `plan`, `rebase-source` (a corrected revision of the same edition), `job` (`--replace-chunk`), `modal-run`, `modal-request`, `modal-fetch`, `modal-settle`, `import`, `supersede` (never ran; a chunk only with `--group`), `close` (ran, not
imported: settles the actual CU), `retire` (a job or chunk group a newer build replaced: kept on record, never used as current), `film`, `reel`, `qc`, `status`, `bundle-audio`, `preview` (public ≤120 s preview clip of chapter 1),
`social` (posting kit; see [publishing](references/publishing.md)) (usage in `eav/cli.py`). Exit codes: 0 ok, 2 stop, 3 budget exceeded, 4 import held,
5 QC failure. A non-zero exit is a decision, not a glitch: never re-run it with edited
inputs to get past it.

## Stage order and who owns each stage

| # | Stage | CLI | Delegated skill (read it for the stage) |
|---|---|---|---|
| 1 | Resolve exact edition and cleared text | server: `python manage.py export_audiovisual_source <slug> --out src.json`; then `init src.json --root <dir> --slug <slug>` | `earnalism-book-production` |
| 2 | Read the whole work; context map (speakers, turns, reveals, ending) | `plan` (30–90 s scenes, 1 still per 8–15 s; series past 40 min) | `earnalism-audiobook-go-live` (`references/narrative-performance.md`) |
| 3 | Earnalism Voice narration (dry, frozen before timing) | `job narration` → Colab (owner) or `modal-run` → `import` | `earnalism-audiobook-go-live` |
| 4 | World bible, anchor stills, film keyframes (FLUX.1-schnell) | `job stills --spec` → Colab or `modal-run` → `import` (per key the newest imported still is used: a small new job replaces only its keys); small defects only: `retouch <key> --film N --region x,y,w,h[:rect] --reason "..."` ($0, local, recorded) | `earnalism-video`, `earnalism-covers` (cover/thumbnail) |
| 5 | Score: VCSL editorial route by default, ACE-Step cues for colour | score bed or `job music` → Colab or `modal-run` → `import` | `earnalism-audiobook-score` |
| 6 | Film assembly (measured timing, ducked mix, motion, logo, END) | `film` | `earnalism-video` |
| 7 | Reels: script, narration (measured), shot plan, keyframes, Wan clips in batches of ≤ 5, assembly | `reel N --script`, `job narration --reel N`, `reel N --plan-shots`, `job stills --reel N`, `job reel_clips --reel N` per batch, `reel N` | `earnalism-video` (Wan22 route) |
| 8 | Review: automated checks, contact sheets, owner review | `qc`; owner watches the first package | `earnalism-book-audiovisual` |
| 9 | Publish, only when told and only where told | `bundle-audio` → Maison `attach_audiovisual_audio stage|publish`; social private staging | `earnalism-book-audiovisual`, `earnalism-book-production` |

Recipes: [film](references/film-recipe.md), [reels](references/reel-recipe.md),
[voice](references/earnalism-voice.md), [free stack](references/free-stack.md),
[budget](references/compute-budget.md), [record](references/production-record.md),
[publishing](references/publishing.md). Pressure scenarios this skill must pass:
[references/pressure-tests.md](references/pressure-tests.md).

## Correcting a published text

When the owner approves a correction of the edition's text (a new live revision of the **same**
edition), never `init` a second root: re-export it and run
`rebase-source <corrected export.json> --root <dir> --reason "<owner approval>"`. It requires the
same edition, language, unit count and paragraph count per unit (otherwise it refuses: a new root),
maps every plan anchor and unit id by position, refreshes the plan's text, keeps scene ids and
still keys, keeps the old export as `source-<old revision>.json`, supersedes never-run film
narration built from the old text and marks imported film narration stale (`film` refuses it).
Stills and music are kept. Then `job narration` as usual ([record](references/production-record.md)).

## Stop conditions (exact behaviour)

| Condition | What you do | What you never do |
|---|---|---|
| **No cleared source** (no export, missing text/hash, title not imported) | Stop. Say which edition is missing what. Route to `earnalism-book-production`. | Fetch or type the text yourself, pick another edition, "start with the reels". |
| **Non-public-domain title** (`public_domain_evidence` false) | `init` refuses. Hold the title; it is out of scope. | Draft clearance for it, or produce social reels of it anyway. |
| **Audio format not cleared on Maison** (only Reader read/preview) | Keep producing: film, reels and review need no Maison grant. `bundle-audio` drafts the per-title evidence; the owner completes and approves it; only then `stage`. | Write `publication_clearance` or rights rows by hand, call the draft "cleared", or publish audio before stage + fresh browser report. |
| **Budget exceeded** (exit 3: Colab forecast over 60 CU per title (keyed by edition) for its whole life, or 100 CU per calendar month; for `modal-run`, worst case over the $30.00 UTC-month or the $6.00 per-title (lifetime) Modal cap) | Stop. Hold for the owner with the forecast, the remaining allowance and the CLI's fit (for `reel_clips`: how many of the batch's shots still fit). Nothing was reserved or run. | Write or edit a spec `compute` block (it is derived and refused if it differs), lower steps/resolution of a prepared job, split a job to slip under the cap, shrink measured rates, edit, reset or swap the ledger pinned at `init`, init a second root for the edition, use another Colab account, raise or work around a Modal cap (month or title), or spend other money. |
| **Import held** (exit 4: missing, extra or mismatched file, or an `INCOMPLETE` manifest) | Re-download the complete output of that exact job and re-run `import`. A job that is `INCOMPLETE` but only stopped short (hard stop, disconnect) is resumed by re-running it (Colab, or on Modal: from this session `modal-request <job_id> --root <dir> --colab-units <CU Colab already showed, 0 if none>` again, which resumes from the Modal volume; `modal-run` itself only where Modal is reachable), within its reserved time; a switch of runner is never free: Colab CU already used stay on the CU caps (`modal-run --colab-units`) and Colab work after the move is settled with `--units`. A job that ran but can never be imported (crash, lost download): `close <job_id> --reason "..."` (Colab: `--units <CU Colab shows>`; a job that ran on Modal settles its Modal rows in USD plus its Colab CU: `--units` only for Colab work after the move), then hold for the owner; for a chunk, rebuild only that chunk with `job --replace-chunk <closed chunk id>`. | Rebuild/rerun the whole GPU job or group, copy files in by hand, edit `manifest.json`, or `supersede` a job that ran (supersede is for never-run jobs only; the CLI refuses a job, or a group, with a Modal run). |
| **Modal run died, failed or hard-stopped** (Ctrl-C, kill, error after the paid run: the ledger row stays `pending` at the worst case; `import` and `close` refuse while it is pending) | Read the billed amount from the Modal dashboard and run `modal-settle <job_id> --root <dir> --usd <billed>`; then `import` the output, or re-run to resume, or `close` as above. A `running` request whose run never reached Modal (no `modal_contacted_at`, and the Modal dashboard shows no run of it): `modal-request <job_id> --root <dir> --abandon --reason "..."` (it says which rows it released and kept). A request that `failed` after a finished Modal run (upload error) is simply requested again: it resumes from the volume and uploads under a new prefix. A group or job replaced by a newer build: `retire` it so nothing uses it as current. | Delete or edit the pending row, edit a request file, or assume the run was free. |
| **QC failure** (exit 5: loudness, true peak, loop close, size, hook onset, reel narration that does not fit its length ± 3 s; `film`/`bundle-audio`/`reel` assembly on `suspect_truncated` narration: a unit ≥ 29.0 s or > 1.6 x the job's median chars/s, Parler's ~30 s cut-off) | Fix only the failing item (one shot, one still, the mix), re-assemble, re-run `qc`. Reel narration that does not fit: rewrite the script's words, `reel N --script`, new reel narration. Suspect_truncated: the owner listens to each unit; complete ones are named with `--accept-qc <unit_key,...>` (only keys on the current suspect list are accepted), cut-off ones are regenerated. | Lower a gate, trim narration, `--accept-qc` a unit nobody heard, or call unheard audio "reviewed". |
| **Stream video held** | The film goes to owner review and to social destinations the owner names. Maison gets audio only. | Upload video to Maison/Stream; `attach_audiovisual_audio` refuses it anyway. |

## Non-negotiables

- **Words.** Film narration speaks the book's exact text, every unit once. Reels may
  condense, but every claim is true to the book; prefer the book's own sentences.
- **Voice.** `en_tisha::story` for English, `bn_arnav::story` for Bengali, description
  byte-for-byte from the roster plus at most one clause of ≤ 12 words. No new voice
  search, no impersonation, no spoken stage directions. A Bengali title with
  `specs/cast.json` is multi-voice (owner decision 28 Nov 2026: narrator + character
  voices from the owner's audition pick in `references/voices.json`; `eav audition`);
  see references/earnalism-voice.md.
- **Models.** Only Indic Parler-TTS, FLUX.1-schnell, Wan 2.x, ACE-Step (Apache-2.0) and
  VCSL samples (CC0), the same pinned models, voices and licences on either runner.
  MusicGen (CC-BY-NC weights) and FLUX.1-dev (non-commercial) are
  forbidden even if the owner names them; offer the licensed equivalent instead.
  No paid generator or credit-spending connector (Kling, ElevenLabs, Suno, Runway,
  Adobe/Canva credits): not for "just one test" either. The only money Claude may spend is
  Modal GPU time through `modal-run` (or `modal-request`), inside the cap below.
- **Modal.** Narration, stills and music may run on Modal on the same built notebook: where Modal
  is reachable, `modal-run <job_id> --root <dir> --colab-units <CU>` (`--dry-run` first checks the
  plan); from this session, which cannot reach Modal, always `modal-request` (below).
  Spend is capped in dollars only (owner decision of 26 Nov 2026): **$30 per UTC month** and
  **$6 per title over its whole life**. The worst case is checked against both before Modal is
  contacted and recorded first as a `pending` ledger row, replaced afterwards by an estimate (wall
  seconds x the kind's GPU rate x 1.25 for CPU, memory and image build; GPU per kind: narration and music on an L4 at $0.000222/s, stills on an L40S (48 GB) at $0.000542/s, because FLUX.1-schnell does not fit an L4); after each run, reconcile the row
  from the Modal usage page with `modal-settle <job_id> --usd <billed> [--run <run_id>]` (also for a
  run that died). The ledger is an estimate, not a hard dollar stop: **when the owner adds the Modal
  payment method, the owner also sets the workspace spend limit to $30/month or less, before any
  request is made or re-made**; until then, hold every request. The 60 CU title and 100 CU month
  caps apply to Colab work only, and count every CU of Colab work, also on a job that changes
  runner. `--colab-units` (required) is the CU Colab already showed for the job, 0 if it never ran
  there: they stay settled against the CU caps and only the rest of the reservation is released (the
  ledger records the move to Modal). `import` and `close` then settle both portions: the Modal rows
  in USD and the Colab CU, i.e. those recorded at the move plus `--units` for any Colab run after it.
  Never raise, split around or skip a cap or the pending row. Reel clips (Wan 2.2) never run on Modal.
  When this session cannot reach Modal: `modal-request <job_id> --root <dir> --colab-units <CU>`
  (same checks, move and pending row; writes `production/audiovisual/modal-requests/<job_id>.json`;
  root commits and pushes it) → the `modal-jobs` GitHub Actions workflow probes R2, re-checks both
  caps for the run's UTC month (any failure before Modal is contacted ends `refused`: pending row
  released, CU reservation restored; nothing was run), runs `modal-run --request` and uploads the
  outputs to the private R2 bucket (one prefix per run) → `modal-fetch <job_id>
  --root <dir>` (sha256 verified, never imports) → `import`. The gated narration model needs the GitHub secret `HF_TOKEN` (a read-only token of the
  account that accepted the model's terms); without it `modal-run` refuses (exit 3) before Modal. See [compute budget](references/compute-budget.md).
- **Rates.** Forecasts are per runner kind from measured rates: the first real Modal run of a kind
  sets its rate; until then use the Colab L4 rates. Never lower a forecast.
- **Colab.** The owner runs Colab jobs. Narration, stills and music notebooks are inert
  until `RUN = True` and stop at their forecast seconds (hard stop). Narration is batched (pinned
  `batch`, default 8, bf16/fp16 with SDPA); every narration, stills and music job is resumable:
  re-running continues, and the total across sessions stays within the reserved forecast.
  Narration or stills
  forecast over 3600 s are built as chunks `<id>-c<i>of<n>` of ≤ 3600 s each (one session
  each; the caps see the sum): run and import every chunk; a closed chunk is rebuilt alone with `job --replace-chunk`, never the whole group ([budget](references/compute-budget.md)). Reel clips use the
  Wan batch notebook: its own flags plus an authority file
  (`/content/wan22-batch-authority.json`) that **the owner writes and signs. Claude never
  writes, edits, drafts or fills in Wan authority files**, never supplies an observed rate,
  allocation time or approval for one. Claude never claims a GPU run it did not import
  and verify.
- **Listening.** Automated checks are advisory. Owner review of the first package is
  the listening assessment, and narrations are not spent at scale before the owner has listened
  to the first narration package; anything not reviewed stays `unassessed`.
- **Retouch.** A small defect regeneration does not reliably remove (a bindi dot on a widow's
  forehead, a small earring, a scrawl or lettering in a corner or on a wall) is painted over from
  the surrounding texture with `retouch` (each region ≤ 3% of the still, ≤ 6% in all; $0,
  deterministic, recorded with source, regions, method, hashes and reason). Never to change a
  character, a face, a pose or the composition: that is a new prompt and a stills job. Look at
  the retouched still; `retouch-undo` retires it. A newer import of the key makes it stale
  ([film recipe](references/film-recipe.md)).
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
- "I'll write the Wan authority JSON so the owner only has to press Run." (Owner
  evidence is the owner's; Claude prints what it must contain, nothing more.)
- "The job crashed, so it cost nothing: supersede it." (It ran: `close` it with the CU
  Colab shows; a Modal job settles its Modal rows in USD plus any Colab CU; supersede refuses it.)
- "It ran in Colab first, but Modal is dollars, so the Colab part no longer counts." (Pass the CU
  Colab showed as `--colab-units`; they stay on the CU caps.)
- "The Modal run was cheap, skip the pending row." / "Just raise the cap to $35 for one job."
  (The pending row and the $30 cap are the owner's rules, not estimates.)
- "Modal still has dollars this month; the title's $6 is only a guideline." (It is a hard cap:
  `modal-run` exits 3; hold for the owner, or run it in Colab inside the CU caps and settle that
  Colab work with `--units` at import/close.)
- "Wan is faster on Modal." (Reels stay on Colab with the owner-signed authority file.)
- "The chunk failed, rebuild the whole job." (`close` it, then `--replace-chunk` that chunk.)
- "That seed was nearly right; regenerate it once more with the same seed." (Seed re-runs are not
  reproducible across batches. A small defect: `retouch`; anything else: a new prompt.)
- "The face drifted from the bible; a retouch can fix it." (Retouch removes small defects only;
  identity, pose and composition are regenerated.)

## Rationalizations

| Excuse | Reality |
|---|---|
| "The owner wants it live today." | Speed comes from following `Next:`; gates are the owner's own rules. |
| "Reader is already cleared, audio is the same text." | Audio is a separate offered format with its own evidence and rights rows. |
| "I'll reserve later, the forecast is rough." | Forecast first from measured rates; the ledger reserves before anything is written. |
| "Modal is only a few dollars." | Dollars are capped: $30 per UTC month and $6 per title for its whole life. |
| "Retrying the failed clip once is fine." | A retry past the forecast is spend the owner did not approve. Cut or hold. |
| "The waveform looks fine, call it reviewed." | Measurement is not listening. Mark unassessed. |
