# Compute budget

Standing owner allowance: **60 Colab compute units (CU) per title over the title's whole
life** (every month counts) and **100 CU per calendar month** across all titles. These CU caps
apply to **Colab work only**; Modal is limited in dollars (see [Modal runs](#modal-runs-eav-modal-run)).
Every GPU batch is forecast before it is built; the
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

Rates are **measured** on the last real run of that job kind on that runner and GPU, never
guessed and never defaulted. The first real Modal run of a kind sets Modal's rate for it; until
then forecasts use the Colab L4 rates, and a forecast is never lowered. `rates.json` (one entry per kind; `steps`, if present, must equal the
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

## Batching and resuming

Narration generates `batch` units per call (pinned in the job, default 8, 1 to 32; part of the job
identity) in bf16/fp16 with SDPA attention. Every narration, stills and music job is resumable: a
finished item (file present, sha256 logged) is skipped when the job is re-run, in Colab or with
`modal-run` again. Each session's seconds are logged (`sessions.jsonl`), and the stop for a re-run is
the reserved forecast minus what earlier sessions used, so the total across sessions never exceeds
the reservation. A resumed job settles once, at import or `close`.

## Chunks (session length, not the caps)

A `narration` or `stills` job whose forecast is over **3600 s** (`MAX_CHUNK_SECONDS`, margin
included) is built as the fewest consecutive chunks, as even as possible, each forecast with the
same formula and its own `decode_s` + `export_s` at most 3600 s, so every chunk fits one GPU
session (Colab or `modal-run`) and resumes cleanly. Order is kept (narration by voice unit,
stills by keyframe). A job at or under 3600 s is built exactly as before. Music cues and
`reel_clips` batches are never chunked.

- The caps are checked **once, for the sum of every chunk's forecast** (more than the unsplit
  forecast, since each chunk pays its own overhead). Over a cap: exit 3, nothing reserved or written.
  Chunking never lets a title slip under a cap.
- Each chunk is its own job: id `<kind>-<hex8>-c<i>of<n>` (or `<--job-id>-c<i>of<n>`; the part
  before `-c` is the group id), its own `inputs.zip`, notebook, build manifest (`chunk: {index, of,
  group}`, also in `job.json`), hard stop and ledger reservation. `import`, `close` and `modal-run`
  take one chunk at a time.
- `film`, `bundle-audio`, reels and `Next:` use a group only once **every** chunk is imported, then
  all chunks' outputs in chunk order; provenance names the group (`narration_job_id`) and its
  chunks (`narration_chunk_job_ids`). `status` lists every chunk (`chunk i/n of <group>`) and one
  line per group: `k of n chunks imported (complete|incomplete|dead ...)`.
- One chunk is never superseded alone: `supersede <chunk or group id> --group --reason "..."`
  supersedes every chunk of the group that is neither imported nor ended (the group is given up).
- A chunk that ran but cannot be imported is `close`d on its own (actual units). Only that chunk is
  rebuilt: `job <kind> --root <root> --rates <rates.json> --replace-chunk <closed chunk id>` builds
  `<chunk id>-r<k>` (k = 1, 2, ...) from the closed chunk's own job.json and build manifest (the
  same items in the same order, the same settings, model and revision), forecast from the measured
  rates, cap-checked (exit 3 over a cap) and reserved on its own. It is refused unless the chunk is
  closed or superseded and its index has no imported or live chunk. The group's other chunks are
  kept; for each index the group uses the imported chunk, else the latest live one, and it is
  complete once every index has an imported chunk. `Next:` offers `--replace-chunk` for a closed
  chunk. This is a retry of one already cap-checked slice, not a split to slip under a cap.
- If building a later chunk fails, every chunk built by that command is removed, its reservation
  settled at 0 and the record restored.

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
  imported). It never claims the job did not run. A job run on Modal is closed without
  `--units`: it settles from its Modal rows in USD.
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
buy units; retry a failed job past its forecast; point a title at a fresh ledger. For Modal also
never: run past or raise the $30 cap, skip or delete the pending row, run `reel_clips` on Modal,
or rebuild a whole group when one closed chunk needs `--replace-chunk`.

## Actuals

`import <job_id> --units <CU>` settles the real units shown in Colab's usage panel for
that session. If another session ran at the same time, record the session's own
observation, not the account aggregate.

## Modal runs (`eav modal-run`)

Modal is capped in dollars only, owner decision of 26 November 2026: **$30.00 per UTC calendar
month** across titles and **$6.00 per title over the title's whole life** (`MODAL_TITLE_CAP_USD`,
the dollar value of the 60 CU title cap at $0.10/CU; keyed like the CU title cap, by `edition_id`).
The 100 CU month and 60 CU title caps apply to Colab work only. The ledger keeps one append-only `modal_spend` record per month with rows
`{job_id, usd, seconds, at, status}` (status `ok`, `failed` or `hard_stopped`); older ledgers
without it load as empty.

- Before contacting Modal, `modal-run` forecasts the worst case the function timeout allows,
  `(DEADLINE_SECONDS + 900) x L4_USD_PER_S`, and refuses (exit 3, naming spent, forecast and
  remaining) if the month's spend plus that exceeds $30.00, or the title's lifetime Modal spend
  (every month, pending rows included) plus that exceeds $6.00. Hold and ask the owner; never run
  past either.
- Before Modal is contacted a provisional row (`status: pending`) at the worst-case usd is appended; it
  counts toward the cap and the job's sum. When the run returns it is replaced in place by the actual
  spend (ok, failed or hard_stopped), before the result is printed. If the process dies (Ctrl-C, kill, an
  error after the paid run) the row stays pending at the worst case: replace it with the billed amount from
  the Modal dashboard via `eav modal-settle <job_id> --root <dir> --usd <billed>` (status `settled`).
- A job is reserved in CU at build time (it may run on either runner). When it is run with
  `modal-run` (after the caps pass, before Modal is contacted) its CU reservation is released: the
  ledger entry records `runner: "modal"`, `moved_to_modal_at` and `reserved_units`, and its units
  become 0, so it no longer counts against the Colab CU caps. From then on it is governed by the
  Modal dollar caps. A resumed run does not move it again.
- A job with any Modal spend row (or moved to Modal) is never imported or closed with Colab
  `--units` (refused, even a matching value): `import` and `close` settle it from its Modal rows,
  recording `usd` (the sum of every session) and `cu_equivalent` (usd / 0.10, information only, not
  counted against any CU cap). Colab jobs still need `--units` and count against the CU caps.
- `status` prints the Colab CU per title and month (Modal-run jobs excluded) and
  `modal: $X.XX of $30.00 this month; title: $Y.YY of $6.00 (UTC month YYYY-MM; ...)`.
- Only narration, stills and music run on Modal; `reel_clips` stays on Colab with the owner-signed
  Wan authority file. The owner's listening review of the first narration package is still required
  before narrations are spent at scale.
- Hold on exit 3 from `modal-run` (cap), on a run that failed or hard-stopped (settle the pending
  row, then import, resume or `close`), and on an `INCOMPLETE` import (resume, or `close`).
