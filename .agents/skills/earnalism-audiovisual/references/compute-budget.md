# Compute budget

Standing owner allowance: a **per-title lifetime cap** (every month counts) and **100 CU per calendar
month** across all titles. The default title cap is 60 CU; a title can have its own cap in
`title-caps.json` beside the ledger (`production/audiovisual/title-caps.json`, a JSON object of
title slug → units; every value a finite number above 0). `init` pins that file in `record.json` (`title_caps`,
or `--title-caps <file>`); a root whose ledger has none beside it (a scratch or test root inside a title's tree)
reads the nearest one above its ledger, never a silent 60, and `status` prints which file the cap comes from. Owner decision 27 Nov 2026: **বিচারক
(`bicharak`) is 100 CU**; every other title stays at 60 until the owner sets another number there.
Never change a cap yourself: it is the owner's number. Every GPU batch is forecast before it is built;
the forecast is reserved on the ledger; the actual units are settled on import.

## Forecast

```
seconds = (steps × s_per_step × items + decode_s + export_s) × 1.15       narration, stills, music
seconds = max(items × clip_s × 1.15, 600)                                  reel_clips (one Wan batch)
units   = seconds / 3600 × units_per_hour
```

`items` is always the job's real count (voice units, stills, cues, shots) and `steps` the
pinned setting (narration 1 per unit, FLUX 4, ACE-Step 60, Wan 24); takes are 1. The CLI
derives them; a spec `compute` block may only restate them and is refused if it differs,
so it can never lower a forecast (R21). The forecast seconds are also each notebook's hard
stop (R25) and each Wan batch's wall (≤ 2700 s).

Rates are **measured** on the last real run of that job kind on that GPU, never guessed
and never defaulted. `rates.json` (one entry per kind; `steps`, if present, must equal the
pinned value):

```json
{"narration":  {"s_per_step": 9.0,  "units_per_hour": 1.94, "steps": 1,  "decode_s": 300, "export_s": 60},
 "stills":     {"s_per_step": 2.5,  "units_per_hour": 1.94, "steps": 4,  "decode_s": 240, "export_s": 60},
 "retouch":    {"s_per_step": 1.0,  "units_per_hour": 1.94, "steps": 30, "decode_s": 900, "export_s": 120},
 "edit":       {"s_per_step": 3.75, "units_per_hour": 1.94, "steps": 40, "decode_s": 1500, "export_s": 120},
 "reel_clips": {"clip_s": 500, "units_per_hour": 1.94, "steps": 24}}
```

`retouch` (SDXL inpainting 0.1, 30 pinned steps, one item per candidate image) has no measured
run yet: its first `rates.json` entry is an ESTIMATE like the first stills entry ("source":
"ESTIMATE — replace with measured values after the first run"; ~1 s/step at about 1024² on an L4,
decode_s covering the install, ~7 GB fp16 download and load) and is replaced by measured values
after that run.

`edit` (Qwen-Image-Edit-2511, one item per candidate image) has no measured run yet either. Its
first entry is an ESTIMATE ("source": "ESTIMATE — replace with measured values after the first
run"): ~150 s per image on an L4 at 40 steps including model CPU offload (`s_per_step` 3.75),
`decode_s` 1500 for the install, the ~58 GB download (transformer ~41 GB bf16, Qwen2.5-VL-7B text
encoder ~17 GB) and the transformer load. Its `steps` is the reference the rate is measured at
(40); items set their own steps (8–50), so the forecast uses ceil(total item steps / images) as
`steps`, never less than the job's real step total. The notebook prints and records the seconds
of every image (`seconds_per_image`): measure the first run from those. On an A100 the CU per
hour differs from an L4's; the rate holds only for the GPU it was measured on. The first L4 run
(NF4, 40 steps) took ~400 s per image; the forecast and hard stop use the `edit` entry of
rates.json exactly as written (no code constant), so update that entry, not the code.

`clip_s` is the measured end-to-end seconds per finished Wan `l4-balanced-v2` clip
(load, 24 denoising steps, decode, export). Reel batches: at most 5 shots each, so a
batch fits one Wan job's 2700 s wall at ~500 s per clip, and the owner's metered Wan
authority (≤ 5 CU, at least 2 × observed rate × wall / 3600) can cover it; the CLI
refuses a batch that cannot.

Numbers above are the shape, not measurements to copy. Known observations (L4,
`earnalism-video/software/WAN22_COLAB.md`): Wan `l4-balanced-v2` steady denoising about
11.3–11.5 s/step, about 480–500 s per finished clip end to end; full 704×1280/50 steps
about 31 s/step; an L4 session showed about 1.94 CU/hour. For narration, one "step" is one
voice unit (`items` = number of units).

Planning size per title (pre-cinematic reels): narration ~2–10 CU, stills ~3–5 CU, ACE-Step cues
~2–3 CU, reel clips ~20–40 CU (the largest). About 30–60 CU per title, two titles a month.

### Cinematic film (`film_clips`, stills with gates)

```
seconds = ((HD clips × clip_s_hd[_a100] + SD clips × clip_s_sd) × takes × 1.15) + decode_s + export_s + sfx_s
units   = seconds / 3600 × units_per_hour_<gpu>          (gpu = a100 when the spec's min_vram_gib > 24, else l4)
stills:   ((4 × s_per_step × items × candidates + decode_s + export_s) × 1.15) + gate_s
          gate_s = gate_setup_s 300 + gate_s_per_still 6 × stills     (ESTIMATE until a gated run is measured)
```

`rates.json` `film_clips` (measured 26–27 Nov pilots): `clip_s_hd` 900 (880–920 s per 1280×704 clip on
an L4), `clip_s_hd_a100` 215 (212–215 s), `clip_s_sd` 435 (896×512 on an L4; the A100 SD clip is
unmeasured and forecast at the L4 figure), `units_per_hour_l4` 2.4, `units_per_hour_a100` 4.5;
`decode_s` 900 and `export_s` 120 are ESTIMATES borrowed from stills. FLUX stills take about 10 s each
on an L4 int8 (about 0.1 CU per 4-candidate job); ACE-Step about 13 s per 60 s stem; a Colab session
sets up in 5–8 minutes. Without a measured value for every key the CLI refuses to forecast.

Per-film forecast (বিচারক at the new density, about 275 shots, 25–35% animated at 1.3 takes each, so
about 90–125 clips): **about 25–34 CU on an A100** (about 0.27 CU per HD clip), about 55–75 CU on an
L4 (about 0.6 CU per HD clip); stills add about 5 CU. This is why A100 is preferred for the film and
why বিচারক's cap is 100 CU; ordinary titles at 60 CU need the animated share kept to peaks and named
actions, and each scene's `plan-shots` output prints a planning estimate (Wan clips and CU) to check
against the remaining allowance before the batch is built. The job's own forecast (derived from
`rates.json`, never the planning figure) is what the ledger reserves.

Each `film_clips` job fits one Colab session: its forecast (the notebook's own hard stop) is at most 4200 s
(70 min); `job film_clips` splits a longer spec into several jobs, a continuation chain never split, each
reserved within the caps before anything is written. The forecast includes the depth maps (`depth_s`,
ESTIMATE 90 s + 4 s per image; `rates.json` may restate `depth_setup_s` and `depth_s_per_image`). Once the
owner approves a scene's paper edit, no per-batch signature is needed (the reel rules of ≤ 5 clips and a
signed authority file stay for reels). Resume is journalled: `done.json` keeps finished clips. **A resumed
session is reserved first:** `job film_clips --resume <job_id> --from <the partial download>` reserves the
remaining items' forecast as a ledger entry linked to the job (`resume_of`), within the title and month caps,
and writes the resume notebook whose hard stop is that reservation; the job then imports or closes with the
CU of all its sessions, and the job and its resumes settle together. **Settling never overruns a cap:**
actual units above the reservation that would take the title past its lifetime cap or the month past 100 CU are
refused (exit 3, nothing settled): hold for the owner. A stalled batch that cannot be resumed is `close`d with
the units Colab shows.

### Lessons from the pilots (carry into every new job)

- **A hard stop must leave time for the manifest and the upload after every cell.** Pilot v4's timer
  unassigned the runtime after the fourth clip, before the manifest and upload: its outputs survived
  only because each clip had been written to Drive. `film_clips` therefore runs the cheap sound stage
  first and writes each finished clip into the Drive job folder as soon as it is journalled (`done.json`),
  so a lost archive can still be downloaded from Drive; never shorten the forecast's reserve to "fit".
- **Never build a Colab job while uncommitted skill changes are in the tree.** The bundle embeds the
  tree's templates and code; with uncommitted changes the record cannot name the code that ran.
- **A prompt past the T5 limit loses its tail silently.** `job stills` now refuses an item whose
  house-style-first prompt is estimated over 180 tokens: put the character lines first and keep an item
  prompt to about 85–90 words.
- **Commons labels country-limited public domain as "Public domain".** The sfx stage keeps only CC0 or
  author-released worldwide PD (see film-recipe.md, Score and sound).
- **A pull-back glide needs `zoom0` high enough** that `zoom0 · (1 + min(0, zoom) · near_gain) ≥ 1` (scene 14 needs about 1.17),
  else the shot is refused: a re-render costs nothing, but an unnoticed edge band would cost a clip.

## The ledger

- Shared by every title and **pinned at `init`**: `--ledger`, else `$EAV_LEDGER`, else
  `<title root>/../allowance-ledger.json`, written into `record.json` as a path relative to
  the title root, so a checkout at another location (keep the ledger beside the roots) sees
  the same reservations; an absolute pin is refused and needs a fresh `init`. Every later command
  uses only that path and refuses a different `--ledger` or `$EAV_LEDGER`. Keep all title
  roots on the same ledger.
- The title cap sums every month of that title. Only the 100 CU monthly cap resets: other
  months' spend does not count against it.
- The month is always the current UTC month; there is no flag to choose another one.
- Reservations count as spent until settled. One writer at a time.
- The title cap is keyed by the export's `edition_id` (entries also carry the title root);
  `init` refuses a second title root for an edition already on the ledger.
- A built job that will never run (replaced before its Colab run) is released only with
  `supersede <job_id> --root <root> --reason "..."`: it settles the reservation at 0 and
  records `job/superseded`; imported jobs and settled entries are refused.
- A job that **ran** but cannot be imported (crash before the manifest, hard stop, lost
  download) is ended with `close <job_id> --root <root> --units <CU Colab shows>
  --reason "..."`: it settles the actual units and records `job/closed` (ran, not
  imported). It never claims the job did not run.
- Both record their intent first (`job/superseding`, `job/closing`), then settle, then
  record the result; after any interruption, rerun the same command to finish it.

## Over a cap (exit 3)

1. Nothing has been reserved or written.
2. `reel_clips`: the CLI says how many of the batch's shots still fit. The reel needs
   every planned shot, so the rest wait for allowance: **hold** for the owner.
3. Any other kind, or no fit: **hold** and tell the owner the forecast, the remaining
   allowance and what would fit next month.

Never: lower steps, resolution or frames of a prepared job; write a `compute` block;
split a job to slip under a cap; shrink a measured rate; edit, delete or reset the ledger; run on another account;
buy units; retry a failed job past its forecast; point a title at a fresh ledger.

## Actuals

`import <job_id> --units <CU>` settles the real units shown in Colab's usage panel for
that session. If another session ran at the same time, record the session's own
observation, not the account aggregate.
