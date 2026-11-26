# GPU jobs: faster, resumable, and runnable on Modal (design)

Status: APPROVED by the owner 26 Nov 2026 (all five plan questions: yes).
`plans/pending/gpu-jobs-fast-resumable-modal.md`.
Owner decision (26 Nov 2026): "Go with A + B, $30/month cap."

## Why

The owner's Colab runs fail in two ways:
- the 2–4.5 h narration jobs outlive the session window;
- Colab often refuses to allocate the GPU or RAM.

Each failure strands the job. A job that ran cannot be resumed, so it is closed and its units count as spent. Narration takes 2–4.5 h because the notebook renders one voice unit at a time in fp32 with no batching.

Goal: the same Apache-licensed outputs, the same Earnalism voice, the same import checks, with:
1. much shorter jobs;
2. no lost work on a disconnect;
3. a second runner Claude can drive end to end, without the owner in a browser.

## Goals
- **A (Colab, no new cost):**
  - Narration runs in batches with bf16 and SDPA attention.
  - Every job is resumable: finished items persist, and a rerun skips them.
  - Long jobs are cut into chunks of ≤ 60 min forecast.
- **B (Modal, ≤ $30/month):**
  - `eav modal-run <job_id>` executes the very same built notebook's code cells headlessly on a Modal L4, with a shim for `google.colab`.
  - It writes the same `manifest.json`, downloads the folder and leaves the normal `eav import` unchanged.
- One allowance ledger for both runners, so title and month caps still hold.

## Non-goals
- Reels (Wan 2.2) stay on Colab with the owner-signed authority file. They are 20–40 CU per title and do not fit $30/month.
- No new models, no paid generators, no voice change (`bn_arnav::story`, `en_tisha::story`, Indic Parler-TTS at the pinned revision).
- Nothing published, posted or charged by these tasks.

## Anti-goals
- Any change that lets an incomplete or altered output import.
- Any change that lowers a forecast to fit a cap.
- A secret in the repo, in chat, or in a plain environment variable.
- Modal spend beyond $30 in a calendar month.

## Approaches (picked: A + B)
| Option | Trade-off | Outcome |
| --- | --- | --- |
| A only | $0, but still browser-run and still hit by GPU refusals | part of the pick |
| **A + B (Modal)** | ~$0.80/L4-hour, per-second billing, about $30/month of free credit on the Starter plan; Claude runs jobs itself | **picked by the owner** |
| RunPod / Vast | ~$0.43/h, but Claude must run the pod lifecycle and pay in advance | dropped |
| Kaggle | free 30 h/week T4, but browser-run, slower GPU, 12 h sessions | dropped |
| HF Jobs | similar price to Modal; this container cannot reach Hugging Face | dropped |

## Design

### A1 — narration speed
- `narration_cell.py.txt` loads the model with `torch_dtype=bfloat16` (fp16 on a GPU without bf16) and `attn_implementation="sdpa"`.
- It generates `BATCH` units per `generate()` call with left-padded prompts, trimming each output to its returned `audios_length`.
- The sampling settings stay the pinned roster preset. `BATCH` is pinned per job in `job.json` (default 8) and recorded in the manifest's `MODEL_INFO`.

### A2 — resume (narration, stills, music)
- Each finished item is written to the Drive folder at once, with its sha256 appended to `progress.jsonl`.
- On a rerun, the cell skips items whose file exists and whose sha256 matches `progress.jsonl`.
- Each session appends `{started, ended, seconds}` to `sessions.jsonl`. Its hard stop is the reserved forecast minus the seconds already used, so the total across sessions never exceeds the reservation (R25 holds).
- The manifest is written only when every item is present, and lists every output exactly as today.
- `import` is unchanged. Actual units = the sum the owner reads off Colab for all sessions, or, for Modal, the billed cost.

### A3 — chunking
`eav job` splits a title's work into jobs of ≤ 60 min forecast: narration by consecutive units, stills by keyframe groups. Every chunk is reserved on the ledger as now. This is splitting for session length, not to slip under a cap. The cap check sums all chunks before any chunk is built, so the R21 forbidden "split to slip under the cap" is still enforced.

### B1 — Modal runner
`eav modal-run <job_id> --root <title root>`:
1. Reads the built `notebook.ipynb` and `inputs.zip`, then checks the zip sha256 and that the job is reserved and not closed or superseded.
2. Starts one Modal function on an `L4` GPU, image pinned (Python and the notebook's own pip line), with a Modal Volume for the job folder.
3. Executes the notebook's code cells in order:
   - `RUN = True` is injected;
   - `google.colab.drive.mount` maps to the Volume;
   - `google.colab.runtime.unassign` ends the function;
   - the deadline is the same `DEADLINE_SECONDS`, also set as the Modal function timeout.
4. Downloads the job folder to `<root>/.downloads/<job_id>/` and reports seconds and cost (seconds × the recorded L4 $/s).
5. Claude then runs the normal `eav import <job_id> --units <cost-equivalent>`.

Resume applies on Modal too, because the Volume keeps finished items.

### B2 — budget
- The ledger gains a `provider` field per reservation (`colab` | `modal`).
- Title (60) and month (100) caps stay in CU. A Modal run settles as `usd / 0.10` CU-equivalent, the Colab price of a unit, so a title's life cap and the month cap keep their meaning.
- New: a hard `$30` per UTC month cap on Modal spend. `modal-run` refuses to start a job whose forecast cost would exceed what is left.
- A Modal workspace budget alert/limit set by the owner in Modal is the backstop.
- The CU-equivalent conversion is a gate question (Q3).

### Skill update
`skills/earnalism-audiovisual` and `.agents/skills/earnalism-audiovisual`, byte-identical:
- SKILL.md, `compute-budget.md`, `free-stack.md` and `pressure-tests.md` name Modal as an owner-approved runner with the $30/month cap.
- "Spend money" stays forbidden beyond that cap and that provider.
- "The owner runs every job" becomes "the owner or Claude via `modal-run` within the cap".

## Constraints
- Same pinned models and revisions; same import checks; tests on the `eav` suite.
- Secrets only through the secure credential form or provider settings.
- Measured rates come from the first real run per kind per runner, never guessed. Until then, forecasts use the old Colab L4 rates (conservative).

## Left to the builder
Batch padding details, the Modal image definition, file layout of `progress.jsonl`/`sessions.jsonl`, and test fixtures.

## Amendments (26 Nov 2026)
- **Owner decision on caps** (supersedes B2's CU-equivalent rule for the caps):
  - Modal is capped in dollars only: $30 per UTC month and $6 per title over its whole life (the dollar value of the 60 CU title cap).
  - The 100 CU month cap and the 60 CU title cap apply to Colab work only.
  - When a job is run on Modal, its CU reservation is released.
  - Reason: an L4 costs about $0.80/h on Modal against about $0.19/h on Colab. Converting at $0.10/CU would have let the remaining November CU cover only about $1.87 of Modal.
- **Transport (B0 finding):**
  - This container's egress proxy re-encrypts TLS without offering HTTP/2 (ALPN none), and Modal's client needs gRPC over HTTP/2. So Claude cannot reach Modal directly. GitHub artifact downloads are blocked too, because their storage hosts vary.
  - The plan's approved fallback is used instead:
    1. Claude checks the caps, writes the pending row and pushes a run request.
    2. A GitHub Actions workflow runs `eav modal-run` with repository secrets.
    3. The workflow uploads the outputs to the existing private R2 bucket `reo-earnalism-maison-private` under `gpu-jobs/<slug>/<job_id>/`, and commits the actual spend back.
    4. Claude downloads the outputs through the Cloudflare API and imports them.
  - The owner adds `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` and `CLOUDFLARE_R2_TOKEN` as GitHub Actions secrets.
