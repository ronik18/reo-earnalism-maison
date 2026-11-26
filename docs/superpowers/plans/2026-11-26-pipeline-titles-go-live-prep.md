# Pipeline titles: go-live preparation (12 titles)

**Spec:** `docs/superpowers/specs/2026-11-25-earnalism-revenue-phases-5-9-design.md` (D8 Monday-page approval, D10, D11) and `docs/BOOK_PUBLICATION_POLICY.md`.
**Owner instruction (26 Nov 2026):** "What about the other books in the pipeline? Could you use /superpowers:subagent-driven-development to prepare all of them in parallel to GO LIVE?"

Titles (slug): নিশীথে `nishithe`, দিদি `didi`, মানভঞ্জন `manbhanjan`, অতিথি `atithi`, মধ্যবর্ত্তিনী `madhyabartini`, শাস্তি `shasti`, সমাপ্তি `samapti`, মেঘ ও রৌদ্র `megh-o-roudra`, প্রায়শ্চিত্ত `prayashchitta`, আপদ `apad`, ঠাকুর্দ্দা `thakurda`, প্রতিহিংসা `pratihingsa`.

Goal: when the owner approves a title's clearance and cover on the Monday page, production needs only three server jobs (`publish_cleared_editions import`, `evidence --browser-report`, `publish`) and the title is live; its narration Colab job is already prepared.

## Global Constraints

- Nothing is approved, imported or published in production by these tasks. Approval is the owner's alone (D8). Any approval used locally is a replica-only simulation on a throwaway database, named as such in the report's `scope`.
- Browser acceptance follows `docs/evidence/publication-browser-20261125-kshudhita-pashan.json` exactly: schema `earnalism.publication-browser-acceptance.v1`, scope `release_code_replica_staff_draft_review`, criteria (every paragraph in order with exact anchor and text; front and back covers 800x1200; no horizontal overflow; no page or console errors), desktop 1440x900 and mobile 390x844, `books.<slug>.sha256` = the draft's `content_sha256`. One file per title: `docs/evidence/publication-browser-20261126-<slug>.json`.
- The replica runs the release code of branch `claude/wonderful-bardeen-s9k90x` at `b94449a` (what production will run) on loopback only, against a fresh local PostgreSQL database per agent; the import uses publisher public_id `649b8725-9f77-4dfd-bad9-74eacd7a973c` so edition, revision and anchor IDs are the deterministic ones production will create.
- Narration jobs: `eav init/plan/job narration` per `skills/earnalism-audiovisual`, voice `bn_arnav::story`, within the 60 CU title cap and the 100 CU month cap; no stills/music jobs in this plan (month budget). Jobs are inert until the owner runs them.
- Local PostgreSQL: 127.0.0.1:55433 (role `maison`); start with `su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/tmp/maison-pg/data -o '-p 55433 -k /tmp' -l /tmp/maison-pg.log start"` if down.

### Task 1: Replica browser acceptance + export — nishithe, didi, manbhanjan, atithi
### Task 2: Replica browser acceptance + export — madhyabartini, shasti, samapti, megh-o-roudra
### Task 3: Replica browser acceptance + export — prayashchitta, apad, thakurda, pratihingsa

Each: on a fresh replica DB, simulate Monday approval of the packet's clearance and cover items (operations.review queue + decide by a local staff user, bound to the exact file hashes), run `publish_cleared_editions import`, verify deterministic IDs and `content_sha256`, run the browser acceptance (desktop + mobile, title page covers + reader text; `megh-o-roudra` also has a `note` block that must render as a footnote), write the per-title report, then run `evidence --browser-report` on the replica and `export_audiovisual_source <slug> --out <scratch>/<slug>.json`. Commit only the report files.

### Task 4: Narration jobs for all 12 titles

From the Task 1–3 exports, run `eav init`, `plan`, `job narration` per title under `production/audiovisual/<slug>/` serially (the allowance ledger is shared), stop before the month cap, and write one combined run sheet `production/audiovisual/RUN_SHEET-pipeline-narration.md` in বিচারক's format.

### Task 5: Records

`docs/OWNER_TASKS.md` (what the owner's approval now triggers; the narration run sheet), release record note, progress table.
