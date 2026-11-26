# GPU jobs: fast, resumable, Modal-runnable; then the audiovisual backlog
Design: `docs/superpowers/specs/2026-11-26-gpu-jobs-fast-resumable-modal-design.md`.
Owner decision (26 Nov 2026): A + B, Modal capped at $30/month.

Execution: superpowers:subagent-driven-development. Each task goes to one implementer subagent in its own worktree, then a spec review and a code review. Root (this session) integrates, deploys, provisions and imports. Subagents never push, never call Modal, Render, Neon or Cloudflare, and never spend.

## Tracks and frontier

The tracks run in parallel. A step starts when its `Blocked by` steps are done.

### Track O — owner (browser or Codex, in parallel with everything)
- **O1 Modal account** (Starter, free):
  - Set a workspace spend limit of $30/month in Modal billing.
  - Create an API token. Enter the token secret in the secure credential form Claude opens. The token id is not secret.
  - Blocked by: plan approval.
- **O2 Razorpay test keys into Render.** Codex prompt already given.
- **O3 Scan checks:** ক্ষুধিত পাষাণ page ১৭৬ "না", and the NVLI link. Codex prompt Part 1.
- **O4 Listen to the first finished narration package** (বিচারক). This is the owner listening assessment (R: automated checks are advisory). Blocked by: C2.
- **O5 Decisions still open:** column width, US/UK trigger, standing-permission date, route for the five held stories. They don't block this plan.

### Track A — faster, resumable Colab jobs (subagents)
**A1 Narration speed + resume** (Size M)
- **Acceptance:**
  - The cell uses bf16 (fp16 fallback) plus SDPA and pinned `BATCH` (default 8). It trims to `audios_length`.
  - Resume skips verified items. `sessions.jsonl` limits the total time to the reservation.
  - The manifest is unchanged in shape; a resumed COMPLETE run imports.
- **Verify:** `cd skills/earnalism-audiovisual/software && python3 -m pytest -q`, plus a new test: a simulated two-session run (fake model) imports, and a tampered item is held.
- **Files:** `eav/templates/narration_cell.py.txt`, `eav/colab_jobs.py` (clock/resume shared cells), `tests/test_colab_jobs.py`, `tests/test_importer.py`.
- **Blocked by:** none.

**A2 Stills + music resume** (Size S)
- Same resume rule for `stills_cell` and `music_cell`.
- **Verify:** eav suite.
- **Files:** `eav/templates/{stills,music}_cell.py.txt`, tests.
- **Blocked by:** A1 (shared resume cell in `colab_jobs.py`).

**A3 Chunking ≤ 60 min** (Size M)
- `eav job narration|stills` emits N chunk jobs when the forecast exceeds 3600 s.
- The cap check runs on the sum before anything is reserved. `status` and the run sheet list the chunks.
- **Verify:** eav suite, plus a test that the sum over a cap refuses every chunk.
- **Files:** `eav/cli.py`, `eav/colab_jobs.py`, `eav/budget.py`, tests.
- **Blocked by:** A1.

### Track B — Modal runner (subagents; live parts at root)
**B0 Reachability spike** (root, XS)
- After O1, propose adding `api.modal.com` to this environment's allowed hosts (owner approval prompt).
- Ask for the token secret through the credential form, header `x-modal-token-secret`. Run `modal token info` / a 10-second CPU function ($0).
- Decides the transport: **direct** (container → Modal) or **fallback** (GitHub Actions runs `modal run` with repo secrets; outputs to a private R2 prefix that Claude reads through the Cloudflare API).
- **Blocked by:** O1.

**B1 `eav modal-run` + shim** (Size M)
- Executes a built notebook's code cells headlessly with the `google.colab` shim and a Volume-backed job folder. Timeout = `DEADLINE_SECONDS`. Downloads the folder and reports seconds and USD.
- Unit tests run the shim locally on CPU with a fake model, so no Modal call is needed.
- **Verify:** eav suite.
- **Files:** new `eav/modal_run.py`, `eav/cli.py` (subcommand), tests.
- **Blocked by:** none. Its contract is "notebook code cells", independent of A's internals.

**B2 Ledger provider + $30 cap** (Size S)
- `provider` per reservation. Modal settles `usd/0.10` CU-equivalent (Q3). A $30/UTC-month Modal cap is refused before start.
- **Verify:** eav suite (`test_budget.py`).
- **Files:** `eav/budget.py`, `eav/cli.py`, tests.
- **Blocked by:** none (run alongside B1; different functions in `cli.py`, merged by root).

**B3 Skill text** (Size S)
- SKILL.md, `references/{compute-budget,free-stack,pressure-tests}.md`: Modal is an approved runner within $30/month; reels stay Colab.
- Copy byte-identical to `.agents/skills/earnalism-audiovisual`.
- **Verify:** `tests/test_skill_files.py`.
- **Blocked by:** B1, B2 (texts must match behaviour).

### Track C — run the backlog (root, then subagents per title)
**C1 Rebuild jobs.**
- Supersede the 18 never-run jobs (they were never run, so supersede is allowed). Rebuild them with A1–A3, keeping forecasts at the old measured Colab rates.
- Commit and push so the Colab links work as a fallback.
- **Blocked by:** A3, B2.

**C2 First real run on Modal: বিচারক narration.**
- Measure the rates and record them in `rates.json` per runner. Import, run QC, and build the audio package.
- **Blocked by:** B0, B1, C1.

**C3 Rest of the backlog on Modal**, in this order:
1. বিচারক stills and music;
2. ক্ষুধিত পাষাণ (narration, stills, music);
3. the 12 narrations.

- It stops at the $30 month cap or the 100 CU month cap, whichever comes first. The remainder rolls to December or to the owner's Colab via the same notebooks.
- **Blocked by:** C2, O4 (the voice is approved before the other 13 narrations are spent).

**C4 Per-title packaging** (one subagent per imported title, parallel):
- QC, audio bundle, a ≤120 s public preview clip (T20), and the posting kit (`eav social`). For বিচারক and ক্ষুধিত পাষাণ, also the film assembly.
- Nothing is posted.
- **Blocked by:** C3 for that title.

**C5 Podcast preview episodes** (D10) for the packaged titles; the feed updates on deploy. Also the founding-Pass audio count toward 8.
- **Blocked by:** C4.

### Track R — records (root)
- R1: `docs/OWNER_TASKS.md`, release record and progress table after each checkpoint.
- Checkpoints: after A1+B1+B2, after C2, after C3.

## Decision log
| Decision | Chosen option | Why |
| --- | --- | --- |
| Runner | Colab (improved) + Modal | owner, 26 Nov |
| Modal spend | ≤ $30 per UTC month, enforced in the ledger and by a Modal spend limit | owner cap; two independent stops |
| Reels | stay on Colab/Wan with owner authority | 20–40 CU per title does not fit $30/month |
| Modal ↔ ledger | CU-equivalent at $0.10/CU (Q3) | keeps the 60/100 CU caps meaningful |
| B1 seam | run the built notebook's own cells | one artifact for both runners; nothing to drift |
| Chunk size | ≤ 60 min forecast | fits Colab sessions and the GPU allocation window |

## Not yet specified
- **B0:** whether Modal's client works through this container's proxy with an injected header. A probe answers it; the fallback is already designed.
- **C2:** measured speed-up of the batched bf16 narration. The rates are re-measured, never assumed.
- **C3:** fog. The month split between November and December depends on measured cost.

## Always / Never
- **Always:**
  - same pinned models and voices;
  - import only COMPLETE, hash-verified outputs;
  - secrets only via the credential form or provider settings;
  - the owner listens before narration is spent at scale.
- **Never:**
  - reels on Modal;
  - a paid generator;
  - publishing or posting;
  - lowering a forecast;
  - spending above $30 on Modal in a month;
  - force-push.

## Progress
| Step | Status |
| --- | --- |
| A1–A3 | A1 in progress (26 Nov) |
| B0–B3 | B1 in progress (26 Nov); B0 waits on O1 |
| C1–C5 | not started |
| O1–O5 | O2, O3 prompts given |
