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
finished item (file present, sha256 logged in `progress.jsonl` for this job's own inputs.zip) is
skipped when the job is re-run, in Colab or on Modal again (from the session: `modal-request` once
more, which resumes from the Modal volume). A resumed session starts its first item only if the
last recorded item (or batch) time still fits before its stop. Each session's seconds are logged (`sessions.jsonl`), and the stop for a re-run is
the reserved forecast minus what earlier sessions used, so the total across sessions never exceeds
the reservation. A resumed job settles once, at import or `close`.

## Chunks (session length, not the caps)

A `narration` or `stills` job whose forecast is over **3600 s** (`MAX_CHUNK_SECONDS`, margin
included) is built as the fewest consecutive chunks, as even as possible, each forecast with the
same formula and its own `decode_s` + `export_s` at most 3600 s, so every chunk fits one GPU
session (Colab or Modal) and resumes cleanly. Order is kept (narration by voice unit,
stills by keyframe). A job at or under 3600 s is built exactly as before. Music cues and
`reel_clips` batches are never chunked. A job holding a single item that alone is forecast over
3600 s cannot be cut into session-length chunks and is refused (check the measured rates; hold for
the owner if they are right).

- The caps are checked **once, for the sum of every chunk's forecast** (more than the unsplit
  forecast, since each chunk pays its own overhead). Over a cap: exit 3, nothing reserved or written.
  Chunking never lets a title slip under a cap.
- Each chunk is its own job: id `<kind>-<hex8>-c<i>of<n>` (or `<--job-id>-c<i>of<n>`); the group
  id is `chunk.group` in its `job.json` (never parsed from the id; a `--job-id` already used as a
  job or group id in the record is refused), its own `inputs.zip`, notebook, build manifest (`chunk: {index, of,
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
  records `job/superseded`; imported jobs, settled entries and jobs with a Modal run (any Modal
  spend row or a move to Modal; with `--group`, if any chunk has one, before anything is written)
  are refused: `close` them instead.
- A job that **ran** but cannot be imported (crash before the manifest, hard stop, lost
  download) is ended with `close <job_id> --root <root> --units <CU Colab shows>
  --reason "..."`: it settles the actual units and records `job/closed` (ran, not
  imported). It never claims the job did not run. A job run on Modal settles its Modal rows in
  USD plus its Colab CU: those recorded at the move, plus `--units` for any Colab run after it.
- Both record their intent first (`job/superseding`, `job/closing`), then settle, then
  record the result; after any interruption, rerun the same command to finish it.

## Over a cap (exit 3)

1. Nothing has been reserved or written.
2. `reel_clips`: the CLI says how many of the batch's shots still fit. The reel needs
   every planned shot, so the rest wait for allowance: **hold** for the owner.
3. Any other kind, or no fit: **hold** and tell the owner the forecast, the remaining
   allowance and what would fit next month.

## Retiring a replaced job

When a newer build replaces a job or a whole chunk group (for example a narration group rebuilt as
one single job), `eav retire <job_id | group id> --root <dir> --reason "<what replaced it>"` marks
it retired: its artifacts, events and ledger rows stay on record, but `film`, `bundle-audio`,
`preview`, reels, `Next:` and `status` never use it as current again (they use the newest complete
job for the target and say which one). Allowed when every job of it is imported, closed or
superseded, or failed on Modal (such a job is closed first, settling its Modal spend); refused while
any of them has a pending Modal row or an open request, and for a single chunk (retire the group).

Never: lower steps, resolution or frames of a prepared job; write a `compute` block;
split a job to slip under a cap; shrink a measured rate; edit, delete or reset the ledger; run on another account;
buy units; retry a failed job past its forecast; point a title at a fresh ledger. For Modal also
never: run past or raise the $30 month or $6 title cap, skip or delete the pending row, run `reel_clips` on Modal,
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
`{run_id, job_id, usd, seconds, at, status}` (status `pending`, `ok`, `failed`, `hard_stopped` or
`settled`; a row reconciled from the bill also has `billed: true` and `estimated_usd`); older
ledgers without it load as empty. A `run_id` is `<job_id>#<n>` and is never reused: n is one more
than the highest n ever issued for the job, including rows released since (the job's ledger entry
keeps `modal_runs_issued`).

**The figures are estimates, reconciled from the bill.** Every Modal amount the ledger writes is
wall seconds x `L4_USD_PER_S` ($0.000222) x `MODAL_OVERHEAD_FACTOR` (1.25, which covers the CPU and
memory surcharges and the image build that the GPU rate leaves out), for the worst case and for the
recorded spend alike. The recorded estimate is at most the worst case the caps were checked with
(the wall clock also holds image build and GPU queue time, which the function timeout does not
bound and Modal does not bill as GPU time); a larger wall-clock figure is kept on the row as
`wall_estimate_usd`. After each run, read the billed amount from the Modal usage page and run
`eav modal-settle <job_id> --root <dir> --usd <billed> [--run <run_id>]`: it replaces the job's
pending row(s), else its one finished row still holding an estimate, or the row `--run` names
(pending or finished). The row keeps its first estimate as `estimated_usd` and records
`billed: true`; the caps always read the rows. Because the ledger is an estimate, it is not a hard
dollar stop: **the owner sets the Modal workspace spend limit to $30 a month or less when adding the
payment method, before any request is made or re-made.** That limit is the hard backstop; until it
is set, hold every Modal request.

- Before contacting Modal, `modal-run` forecasts the worst case the function timeout allows,
  `(DEADLINE_SECONDS + 900) x L4_USD_PER_S x MODAL_OVERHEAD_FACTOR`, and refuses (exit 3, naming spent, forecast and
  remaining) if the month's spend plus that exceeds $30.00, or the title's lifetime Modal spend
  (every month, pending rows included) plus that exceeds $6.00. Hold and ask the owner; never run
  past either. A run that may still be going in the next UTC month (start + timeout + 1800 s of
  image build and queue) is checked against that month's cap too, and if it ends there its row
  moves there (a run is never invisible to the month it spent in).
- Before Modal is contacted a provisional row (`status: pending`) at the worst-case usd is appended; it
  counts toward the cap and the job's sum. When the run returns it is replaced in place by the
  estimated spend (ok, failed or hard_stopped), before the result is printed; reconcile it from the
  bill as above. If the process dies (Ctrl-C, kill, an error after the paid run) the row stays pending
  at the worst case: replace it with the billed amount via `eav modal-settle <job_id> --root <dir>
  --usd <billed>` (status `settled`). `import` and `close` refuse while the job has a pending row.
  A failure before Modal is contacted (for example an inputs.zip that no longer matches its build
  manifest) releases the row at once: nothing was spent.
- A job whose Modal run finished `ok` (request `done`) is fetched and imported, never run or
  requested again (`modal-run` and `modal-request` refuse it); if it can never be imported, `close`
  it and rebuild. A request that `failed` after its Modal run (for example an R2 upload error) is
  requested again: the new run resumes from the Modal volume, generates nothing that is already
  done, and uploads under its own new `run-<n>/` prefix.
- The Modal volume `earnalism-eav-jobs` keeps each job folder (for resuming) and the Hugging Face
  model cache (`/hf-cache`, so a rerun does not download the weights again). Modal may bill volume
  storage under its own pricing: tell the owner it exists, and clear old job folders and the cache
  (`modal volume rm earnalism-eav-jobs <path> -r`, where Modal is reachable) when no run of them is
  planned. A notebook cell never prints the environment (it holds `HF_TOKEN`); errors are written
  with the token masked.
- A job is reserved in CU at build time (it may run on either runner). `modal-run` requires
  `--colab-units <CU>` (>= 0): the CU Colab already showed for this job, 0 if it never ran there.
  When it moves to Modal (after the caps pass, before Modal is contacted) the ledger entry records
  `runner: "modal"`, `moved_to_modal_at`, `reserved_units` (the forecast) and `colab_units`; its
  units become `colab_units`, which stay counted against the Colab CU caps, and the rest of the
  reservation is released. From then on the Modal portion is governed by the Modal dollar caps. A
  later `modal-run` of the same job passes the cumulative Colab CU again: it may grow (a Colab
  session in between), never shrink (refused). `--colab-units` above the job's CU reservation is
  refused: ask the owner if Colab showed more. A request refused before Modal was contacted undoes
  the move when the job has no non-pending Modal row: the reservation is restored and the job is a
  Colab job again (Colab cap checks and `supersede` work as before the request).
- `import` and `close` of a job with any Modal spend row (or moved to Modal) settle both portions:
  its Modal rows, recording `usd` (the sum of every session) and `cu_equivalent` (usd / 0.10,
  information only, not counted against any CU cap), and its Colab CU against the CU caps: the
  `colab_units` recorded at the move plus an optional `--units` for any Colab run after the move
  (default 0). Switching runner is never free: every CU of Colab work and every Modal dollar counts.
  Colab-only jobs still need `--units`.
- `status` prints the Colab CU per title and month (including Colab work on jobs that moved to
  Modal) and
  `modal: $X.XX of $30.00 this month; title: $Y.YY of $6.00 (UTC month YYYY-MM; ...)`.
- Only narration, stills and music run on Modal; `reel_clips` stays on Colab with the owner-signed
  Wan authority file. The owner's listening review of the first narration package is still required
  before narrations are spent at scale.
- Hold on exit 3 from `modal-run` (cap), on a run that failed or hard-stopped (settle the pending
  row, then import, resume or `close`), and on an `INCOMPLETE` import (resume, or `close`).

### Through GitHub Actions (request, workflow, fetch, import)

When the session cannot reach Modal (its proxy has no HTTP/2, so the gRPC client cannot connect),
the run goes through the `modal-jobs` workflow on a GitHub-hosted runner, and the outputs come
back through the private Cloudflare R2 bucket `reo-earnalism-maison-private`. The caps are the same.

**GitHub secret `HF_TOKEN`**: the narration model `ai4bharat/indic-parler-tts` is gated on Hugging
Face. Add a read-only token of the account that accepted its terms as the repository secret
`HF_TOKEN`; only the workflow's "Run on Modal" step receives it, and `modal-run` attaches it to the
Modal function as an in-memory secret (never written, printed or recorded). A gated model without
`HF_TOKEN` is refused (exit 3) before Modal is contacted; the request's row is released.

1. **Request** (in the session): `eav modal-request <job_id> --root <title root> --colab-units <CU>`
   runs every `modal-run` check (job state, inputs.zip sha256, `reel_clips` refused, both dollar caps
   against the worst case with pending rows counted), records the move to Modal with
   `--colab-units` (same meaning and validation as on `modal-run`) and writes the worst-case
   `pending` row exactly as `modal-run` would, so the caps hold while the remote run is in flight.
   Then it writes `production/audiovisual/modal-requests/<job_id>.json` (schema
   `earnalism.modal-request.v1`: `job_id`, `title_root`, `requested_at`, `status: requested`,
   `colab_units`, `pending_run_id`, `worst_case_usd`, `r2_prefix` =
   `gpu-jobs/<slug>/<job_id>/run-<n>/`, one prefix per run). The job id must match
   `^[a-z0-9][a-z0-9.-]*$` and the title root must be under `production/audiovisual/`. It refuses while a request
   for the job is `requested` or `running`, and a local `modal-run` of that job is refused too. It
   never commits: root commits the request with the ledger and pushes to
   `claude/wonderful-bardeen-s9k90x`.
2. **Workflow** (`.github/workflows/modal-jobs.yml`, triggered only by a pushed
   `modal-requests/*.json`; one request at a time, each its own matrix job with its own 300-minute
   timeout). Actions are pinned to commit SHAs and the client to `modal==1.6.4`, installed in a step
   without secrets; the checkouts keep no token (`persist-credentials: false`), only the steps that
   push get the GitHub token, and each other step gets only the secrets it needs. Per `requested`
   file:
   - check it (`python3 -m eav.modal_requests check`: schema, status, job id pattern and file
     name, title root under `production/audiovisual/`, pending run id, `colab_units`, `r2_prefix`),
     then mark it `running` and push. An invalid request is refused (below), never left to block
     the queue;
   - `eav r2-probe` (R2 token only): PUT, list, GET and DELETE a probe object under the request's
     prefix + `_probe/`. If that fails, the request becomes `refused`, its pending row is released,
     the CU reservation restored, and Modal is never contacted;
   - `modal-run <job_id> --root <title_root> --request` (Modal tokens only): reuses the request's
     pending row and `--colab-units`, but re-checks both caps first for the **current** UTC month
     (the row moves there) and the title. Over either cap: `refused`, row released, reservation
     restored, exit 3, nothing contacted. Immediately before contacting Modal it writes
     `modal_contacted_at` into the request. The row is replaced with the estimated spend in a
     `finally`. In the container the volume is committed at the hard stop and at the end;
   - refuse if Modal was never contacted (an `always()` step, stdlib only, so it also works when the
     install failed: `python3 -m eav.modal_requests refuse-unstarted`): a request still open
     without `modal_contacted_at` (install, check, mark, probe or `modal-run` failed or was
     cancelled before contact) becomes `refused`, its pending row released and the reservation
     restored, and is pushed;
   - `eav r2-upload` (R2 token only): puts every file of the downloaded job folder under the
     request's prefix, reads each one back to compare its sha256, and finishes the request as
     `done`, `failed` or `hard_stopped` with `seconds`, `usd`, `r2_prefix` and `files` (`path`,
     `sha256`, `bytes`). A copy of the finished request goes to `<prefix>_request-result.json`;
   - push the request and the ledger back (only the push token, `.github/scripts/modal-publish.sh`).
     A conflicting rebase is aborted; on the fresh branch head the stdlib-only replay
     (`python3 -S -m eav.modal_requests replay`, also `eav modal-replay`) re-applies the request
     file and this job's ledger entry, and makes the job's rows exactly the saved ones (a released
     row stays released; a row billed on the branch meanwhile stays billed); other jobs' rows are
     kept. Every `python3` in a step holding the push token runs with `-S`, so nothing the pip
     install added runs there; only the run job may write to the repository. Write access to the
     branch is still equivalent to access to the secrets. Then it retries; a failed fetch,
     rebase or replay is retried too, never ends the script early. If every attempt fails, this
     run's commit is pushed to `modal-results/<job_id>` (`-run-<GitHub run id>` appended if that
     branch exists).

   The hard backstop is the Modal workspace spend limit, set by the owner to $30 a month or less
   when the payment method is added, before any request is made or re-made.
3. **Fetch** (in the session, after pulling the branch): `eav modal-fetch <job_id> --root <title
   root> [--into <dir>]` lists and downloads every object under the request's prefix through
   api.cloudflare.com (the session proxy supplies the credential), refuses a missing, extra or
   mismatched file with nothing written, and lands the folder in `<root>/.downloads/<job_id>/`
   (git-ignored). If the branch request is still `running` (the push-back failed), it reads the
   R2 copy `_request-result.json` under that request's prefix (only if it carries the same
   `pending_run_id`) and says to merge the fallback branch for the ledger. A `refused` request has
   nothing to fetch. It never imports.
4. **Import** as usual: `eav import <job_id> --root <title root> --from <that folder>`; the Modal
   portion settles from the Modal rows.

A request left `running` (the runner died or hit its timeout and the refusal step could not
push) keeps its pending worst-case row. If the request has no `modal_contacted_at` on the branch,
first check the Modal dashboard (app `earnalism-eav`) for a run of it: a runner lost after it
reached Modal could not push that field. If there is none: `eav modal-request <job_id> --root <dir>
--abandon --reason "..."` refuses it, releases the row and restores the reservation (unless the job
has earlier Modal runs, which stay on record), and says exactly which rows it released and kept (it
refuses when `modal_contacted_at` is set). If a run of it shows up billed later, `modal-settle
<job_id> --usd <billed> --run <its run_id>` writes the released row again, billed. Otherwise read
the billed amount from the Modal dashboard, `modal-settle` it, and hold for the owner before a new
request. A request refused after its reservation was restored, when another job reserved the
released CU meanwhile, says which CU cap is now exceeded: hold that job for the owner. If the request
file cannot be written, `modal-request` releases its pending row again. Never edit a request file by
hand.
