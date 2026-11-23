# Compute budget

Standing owner allowance: **60 Colab compute units (CU) per title over the title's whole
life** (every month counts) and **100 CU per calendar month** across all titles. Every GPU batch is forecast before it is built; the
forecast is reserved on the ledger; the actual units are settled on import.

## Forecast

```
units = (steps × s_per_step × items × takes + decode_s + export_s) × 1.15 / 3600 × units_per_hour
```

All inputs are **measured** on the last real run of that job kind on that GPU, never
guessed and never defaulted. `rates.json` (one entry per kind):

```json
{"narration":  {"s_per_step": 9.0,  "units_per_hour": 1.94, "steps": 1,  "decode_s": 300, "export_s": 60},
 "stills":     {"s_per_step": 2.5,  "units_per_hour": 1.94, "steps": 4,  "decode_s": 240, "export_s": 60},
 "reel_clips": {"s_per_step": 11.5, "units_per_hour": 1.94, "steps": 24, "decode_s": 300, "export_s": 120,
                "takes": 2}}
```

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
- A built job that will never run (replaced before its Colab run) is released only with
  `supersede <job_id> --root <root> --reason "..."`: it settles the reservation at 0 and
  records `job/superseded`; imported jobs and settled entries are refused.

## Over a cap (exit 3)

1. Nothing has been reserved or written.
2. `reel_clips`: the CLI prints the largest fitting cut, **takes first, then shots**
   (never below 8 shots). Rewrite the shot spec to that size and run `job` again.
3. Any other kind, or no fit: **hold** and tell the owner the forecast, the remaining
   allowance and what would fit next month.

Never: lower steps, resolution or frames of a prepared job; split a job to slip under a
cap; shrink a measured rate; edit, delete or reset the ledger; run on another account;
buy units; retry a failed job past its forecast; point a title at a fresh ledger.

## Actuals

`import <job_id> --units <CU>` settles the real units shown in Colab's usage panel for
that session. If another session ran at the same time, record the session's own
observation, not the account aggregate.
