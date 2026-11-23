# Compute budget

Standing owner allowance: **60 Colab compute units (CU) per title over the title's whole
life** (every month counts) and **100 CU per calendar month** across all titles. Every GPU batch is forecast before it is built; the
forecast is reserved on the ledger; the actual units are settled on import.

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
 "reel_clips": {"clip_s": 500, "units_per_hour": 1.94, "steps": 24}}
```

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

Planning size per title: narration ~2–10 CU, stills ~3–5 CU, ACE-Step cues ~2–3 CU,
reel clips ~20–40 CU (the largest). About 30–60 CU per title, two titles a month.

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
