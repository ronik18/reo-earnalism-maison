# Earnalism revenue growth: feature and task plan

Strategy and evidence: `docs/superpowers/specs/2026-11-24-earnalism-revenue-strategy-design.md`
Status: **APPROVED by the owner on 24 Nov 2026 ("Yes to all decisions, start Phase 1").** G0.1–G0.6 accepted as recommended.

Lane ownership follows AGENTS.md: Frontend (`client/`, `web/`, `templates/`, `static/`), Backend (`accounts/`, `reader/`, `core/`), Media/commerce (`library/`, `billing/`, `learning/`), Root (`config/`, `operations/`, `contracts/`, docs, CI, final commits).

## Gate 0: owner decisions (no code)

These are the batched questions in section "Not yet specified". Phase 1 needs only G0.1 and G0.2.

## Phases

### Phase 1: Measure the funnel (risk first: we have no data)
Verified when: a test signup from a UTM-tagged link shows `source=youtube, title=<slug>` in the staff funnel report, and no third-party tracker is loaded.
Files to touch: `accounts/`, `core/`, `operations/`, `templates/`

#### Step 1.1: First-party attribution on signup (Size: S), Backend
- Acceptance criteria: `utm_source`/`utm_campaign`/`utm_content` and the landing title are captured server-side at first visit into the session, and stored on account creation; no cookie beyond the necessary session cookie; values are length-bounded and allow-listed.
- Verification command: `.venv/bin/python manage.py test accounts core --noinput`
- Files likely touched: `accounts/models.py`, `accounts/migrations/`, `core/` middleware
- Test seams: signup view integration test
- Blocked by: G0.2

#### Step 1.2: Aggregate funnel report (Size: S), Backend + Root
- Acceptance criteria: weekly signup cohorts by source (and optionally campaign) counted through verified → started reading → completed a story → Pass started, from existing records; cells under 5 suppressed; no per-person output.
- Verification command: `.venv/bin/python manage.py test accounts.test_attribution --noinput`
- Files likely touched: `accounts/attribution.py`, `operations/management/commands/funnel_report.py`
- Test seams: management command output on PostgreSQL fixtures
- Blocked by: 1.1

### Phase 2: Content flywheel (Strategy 1)
Verified when: one title has a private YouTube film, two private Shorts and a quote-card set staged with UTM links, all from one `eav` run, awaiting owner publication authority.
Files to touch: `skills/earnalism-audiovisual/`, `operations/social_delivery/`, `operations/production_bundle.py`, `library/`

#### Step 2.1: Title rights pipeline for 9 regions (Size: S), Media/commerce + Root
- Acceptance criteria: a shortlist of 12 public-domain Bengali titles (published before 1931, author died 1955 or earlier) with a per-edition, per-region evidence record in the existing `Rights` model; new English translations marked as Earnalism-owned works.
- Verification command: `.venv/bin/python manage.py test library --noinput`
- Files likely touched: `library/intake/`, `docs/BOOK_PUBLICATION_POLICY.md` (references only)
- Test seams: intake API tests
- Blocked by: G0.1

#### Step 2.2: Social kit derived from each candidate (Size: M), Root
- Acceptance criteria: `eav` emits a 16:9 film, 9:16 reels and 1:1 quote cards from one candidate hash; each description carries the title-page link with UTM tags; captions are attached for YouTube.
- Verification command: `python3 -m unittest operations.social_delivery.test_bridge -v` and `.venv/bin/python manage.py test operations --noinput`
- Files likely touched: `skills/earnalism-audiovisual/`, `operations/production_bundle.py`, `operations/social_delivery/bridge.py`
- Test seams: bundle verifier tests
- Blocked by: 1.1

#### Step 2.3: Owner-authorized YouTube publication (Size: S), Root
- Acceptance criteria: the existing private upload path plus an exact-action `Authority` publishes one film; provider readback recorded in the journal; Shorts published the same way.
- Verification command: `python3 -m unittest operations.social_delivery.test_bridge -v`; live readback receipt
- Files likely touched: `operations/social_delivery/`, `operations/management/commands/`
- Test seams: mocked HTTP suite, then one live provider receipt
- Blocked by: 2.2, G0.3

#### Step 2.4: Google Play Books audiobook distribution (Size: S), Media/commerce
- Acceptance criteria: an export bundle (cover, chapters, metadata) for one cleared English title passes Google Play Partner Center validation; Earnalism is listed as publisher.
- Verification command: `.venv/bin/python manage.py test library --noinput`
- Files likely touched: `library/production_handoff.py`
- Test seams: export bundle unit test
- Blocked by: 2.1, G0.4

### Phase 3: Bilingual Pass (Strategy 2)
Verified when: a sandbox Razorpay journey buys the Pass, unlocks Pass-only features, cancels in one confirmed step and issues the correct invoice and credit note, on PostgreSQL.
Files to touch: `billing/`, `library/`, `learning/`, `web/`, `client/`, `templates/`

#### Step 3.1: Entitlement split, free vs Pass (Size: M), Media/commerce
- Acceptance criteria: reading stays free for every released edition; full audio, the parallel bn⇄en switch, offline, certificates and early access require an active Pass; `MAISON_FREE_ACCESS` behaviour is unchanged while the flag is on.
- Verification command: `.venv/bin/python manage.py test library learning billing --noinput`
- Files likely touched: `library/services.py`, `learning/services.py`, `billing/subscriptions.py`
- Test seams: `library/test_free_access.py`, entitlement service tests
- Blocked by: G0.5

#### Step 3.2: Parallel bilingual read-along (Size: M), Frontend
- Acceptance criteria: a Reader toggle shows the Bengali and English `Paragraph` pairs side by side (stacked on mobile) with `TimingMap` highlighting; accessible markup; approved typography preserved.
- Verification command: `npm run check && npm run build` then `.venv/bin/python manage.py test web --noinput`
- Files likely touched: `client/`, `templates/reader/`, `static/`
- Test seams: Reader island tests and browser regression suite
- Blocked by: 3.1

#### Step 3.3: Completion certificate (Size: S), Media/commerce
- Acceptance criteria: finishing a track with the quiz passed produces a verifiable certificate page (unique ID, no personal data beyond the display name the member chooses).
- Verification command: `.venv/bin/python manage.py test learning --noinput`
- Files likely touched: `learning/models.py`, `learning/views.py`, `learning/migrations/`
- Test seams: learning journey tests
- Blocked by: 3.1

#### Step 3.4: Honest Pass page and upgrade moments (Size: S), Frontend
- Acceptance criteria: the Pass page shows the real price and real competitor anchors with sources; the upgrade prompt appears only after a completed free chapter; one confirmed-step cancel is linked from Account.
- Verification command: `.venv/bin/python manage.py test web --noinput`; ui-consistency verifying pass
- Files likely touched: `templates/`, `web/`
- Test seams: web view tests and browser regression
- Blocked by: 3.1, G0.5

#### Step 3.5: Merchant re-qualification in sandbox (Size: M), Root + Media/commerce
- Acceptance criteria: the existing Razorpay adapter passes a hosted-offer sandbox journey end to end; finance profile and invoice numbering verified; live mode still rejected until owner sign-off.
- Verification command: `.venv/bin/python manage.py test billing --noinput`
- Files likely touched: `billing/`, `config/`
- Test seams: `billing/test_live_mode.py`, `billing/test_checkout.py`
- Blocked by: 3.1, G0.5

### Phase 4: Classroom licence (Strategy 3)
Verified when: 3 pilot teachers each run 4 weekly classroom sessions, logged in the funnel report.
Files to touch: `accounts/`, `learning/`, `billing/`, `templates/`

#### Step 4.1: Teacher account and classroom mode (Size: M), Backend + Frontend
- Acceptance criteria: a teacher role opens a full-screen projection mode for any released title (large text, film, highlighting); no student accounts; usage counted per session.
- Verification command: `.venv/bin/python manage.py test accounts web --noinput`
- Files likely touched: `accounts/`, `templates/reader/`, `client/`
- Test seams: role permission tests
- Blocked by: 1.2, G0.6

#### Step 4.2: Printable worksheets from learning tracks (Size: S), Media/commerce
- Acceptance criteria: each `Track` exports a printable PDF worksheet and answer key using the existing PDF fonts (Bengali shaping verified).
- Verification command: `.venv/bin/python manage.py test learning billing --noinput`
- Files likely touched: `learning/`, `billing/pdf_fonts.py` (reuse only)
- Test seams: PDF render tests
- Blocked by: 4.1

#### Step 4.3: Institution invoicing (Size: S), Media/commerce
- Acceptance criteria: a manual-invoice B2B plan (per class, per year) uses the existing invoice numbering; no card checkout needed.
- Verification command: `.venv/bin/python manage.py test billing --noinput`
- Files likely touched: `billing/invoices.py`, `billing/subscription_models.py`
- Test seams: `billing/test_invoices.py`
- Blocked by: 4.1, G0.5

## Decision log

| Decision | Chosen option | Why |
| --- | --- | --- |
| Order of strategies | Flywheel → Pass → Classroom | Traffic is the binding constraint; the Pass converts only with an audience |
| Paywall line | Reading free forever; audio, bilingual, offline and certificates paid | Keeps the free promise honest and gives a clear reason to pay |
| Analytics | First-party, server-side, aggregate only | No third-party trackers; fits the privacy and consent posture |
| Schools | Teacher-only licence, no student accounts | Avoids new child-data processing under DPDP |
| Price | Keep the planned INR 99 / INR 999 | Already designed; below Storytel and Kuku; test before changing |
| Attribution transport (1.1) | Carry `utm_*` inside the existing `return_to` link; capture at registration | No new cookie for anonymous visitors; tagged URLs already bypass the public cache; almost no template changes |
| Funnel data (1.2) | Derive stages from existing Progress/Completion/Subscription rows; no new event table | Simpler; nothing new to retain or delete; "visit" counts are left to provider analytics |
| Header CTA on tagged pages | "Start reading free" returns to the tagged page instead of Explore | Found while testing: the header link dropped the tags, losing YouTube visitors who click it |
| Term screen (2.1) | Code the 9 territory rules once and screen every candidate; reproduce the two approved evidence records as a test | Removes hand arithmetic; caught Thakurmar Jhuli (compiler died 1956/57: in copyright in GB/BR/SG/ID until 2027) |
| Quote cards (2.2) | Only the book's exact words; Bengali subset font for text, Latin font for the address | Truth rule; the Bengali font subset has no Latin glyphs |
| Certificates (3.3) | One per member and track, only after every current lesson (and current quiz pass); public by unguessable link; member-chosen name; withdrawable; none for guardian-managed accounts; free while free access is on | Shareable proof of learning that doubles as free marketing; minimal personal data |
| Pass split (3.1) | Use the existing per-format policy and platform entitlement; no new gate | The approved design already supports it; less code to qualify |
| Classroom role (4.1) | Staff-granted Django permission via an audited command; no self-serve, no new account type | Pilot is founder-led; smallest change that keeps a record |
| Classroom usage (4.1) | Count a projection once per teacher, chapter and 30 minutes | Refreshes and back-and-forth must not inflate the pilot metric |
| Invoicing (4.3) | Deferred until a pilot school agrees to pay | Pilot is free; nothing to bill; avoids building against an unknown contract |
| Attribution privacy | Allow-listed sources and slugs only; exported with the account, deleted on account deletion, treated as registration scaffolding by abandoned-signup cleanup; none for guardian-managed accounts | Minimal data that still answers "which content brings members" |

## Not yet specified (Gate 0 questions for the owner)

- G0.1 Approve the flywheel title list approach (pre-1931, author died 1955 or earlier, new in-house English translations)?
- G0.2 Approve first-party UTM attribution (Phase 1)?
- G0.3 Grant publication authority for YouTube and social posts of cleared titles, and name the channel? **Answered 24 Nov 2026:** channel `UCw-UnAXdRzqij8_B2TlgQjQ` (https://www.youtube.com/channel/UCw-UnAXdRzqij8_B2TlgQjQ). Uploading still needs the channel owner to authorize upload access (OAuth) for `operations/social_delivery`, and a finished film.
- G0.4 Distribute audiobooks on Google Play Books (52% share) and approach Storytel, Kuku or Pocket FM for licensing?
- G0.5 Re-enable the paid Pass (INR 99 / INR 999) once Phase 2 reaches a traffic threshold (proposed: 10,000 monthly title-page visits)?
- G0.6 Approve a teacher-only classroom licence pilot at about INR 200 per student per year, free for the pilot?
- Later, separate decisions: a USD diaspora tier for US and GB (needs account service beyond India); returning Bangladesh to the active regions.
- Fog: the Strategy 1 licensing deal terms (researched when a partner responds).

## Always / Never

- Always: exact-edition clearance in all active regions before publication; one confirmed-step cancel; real sources behind every claim and price anchor; PostgreSQL tests for each step.
- Never: paid provisioning or ad spend without budget authority; third-party ad trackers on the Reader; student or child accounts; changing the approved stack or design without approval; publishing without an exact-action authority.

## Progress

| Phase | Status |
| --- | --- |
| Gate 0 | Approved 24 Nov 2026 |
| 1 Measure | Implemented 24 Nov 2026: `accounts/attribution.py`, migration `accounts/0007`, `funnel_report` command, header CTA keeps tags on tagged pages, guide in `docs/CAMPAIGN_LINKS.md`. Verified by `accounts.test_attribution` (13 tests) and the full suite. Deployed to production 24 Nov 2026 (release record `docs/evidence/release-20261124-revenue-phases.md`). |
| 2 Flywheel | In progress (24 Nov 2026). 2.1: `library/term_check.py` + `term_check` command; 14-title screen in `library/intake/candidates-20261124.json` (11 pass, 2 illustration review, 1 hold). 2.2: `eav social` posting kit (tagged links, YouTube descriptions/chapters, reel posts, exact-word quote cards). 2.3 blocked on owner: first film must be produced (Colab jobs for বিচারক are prepared, none run) and the YouTube channel and upload access named. 2.4 blocked on audio clearance and a Google Play Books partner account. 25 Nov 2026: Colab run sheet for the three বিচারক jobs (`production/audiovisual/bicharak/RUN_SHEET.md`) handed to the owner; ক্ষুধিত পাষাণ intake packet from the 1895 Galpa-Dashak with owner-approved clearance (cover pending, #63); কাবুলিওয়ালা waits on an early (pre-1931) printing, only the 1946 Visva-Bharati edition is transcribed. Next: the remaining Galpa-Dashak stories as intake packets. |
| 3 Pass | In progress (24 Nov 2026). 3.1: no code needed: per-format `free`/`paid` policy plus a platform Pass entitlement already gives "read free, audio with Pass"; proven by `library/test_pass_split.py`; switched on later by content policy and turning `MAISON_FREE_ACCESS` off at the G0.5 threshold. 3.3: completion certificates (model, issue/withdraw, public page, export/deletion), free for all while free access is on. 3.2 waits on the first translated edition pair; 3.4 and 3.5 wait on the G0.5 traffic threshold and Razorpay test keys. |
| 4 Classroom | In progress (24 Nov 2026). 4.1: teacher role granted by staff (`classroom_teacher grant|revoke|list`, audited); classroom projection page per chapter (large type, clicker/arrow/Space stepping, full screen) using the normal reader authorization; one counted session per teacher, chapter and half hour; `classroom_report` gives sessions per teacher per week. 4.2: printable worksheet and answer key PDFs from a track's quiz (Bengali shaped). 4.3 deferred: the pilot is free, so there is nothing to invoice until a school converts. Deployed 24 Nov 2026. First pilot teacher granted 24 Nov 2026 (audited); teachers 2 and 3 on hold by the owner. Next: a বিচারক reading track with a quiz, so worksheets and certificates have content. |
| 5–9 Content engine and recurring income | Designed and planned 25 Nov 2026 (`docs/superpowers/specs/2026-11-25-earnalism-revenue-phases-5-9-design.md`, `docs/superpowers/plans/2026-11-25-earnalism-revenue-phases-5-9.md`). Built on branch `claude/wonderful-bardeen-s9k90x`, each task reviewed: Wikisource intake (T1), Cloudinary cover pairs (T2), publish any owner-approved packet with explicit `--book`/`--all` (T3) and translation labels at import (T3b), AI/editor translation labels and `intake_translation` (T4), Monday review queue with standing permission off until `MAISON_REVIEW_STANDING_FROM` is set (T5), attended private-only YouTube upload batch (T6), founding member plans inactive until 8 audio titles and merchant approval (T7), Pass page founding offer shown only when purchasable and free access is off (T8), revenue and 30% reinvestment record with Pass labelled as invoiced (T9), Play Books export bundle for the 9 regions (T10), licensing catalogue of editor-revised translations (T12), test-only school invoices until an approved institution tax rule exists (T13), labelled sponsored tracks (T14). Podcast feed (T11) with public-preview episodes (D10, T17); Monday-page approval unlocks publishing (D8, T16). Deployed to production 25 Nov 2026 (#64, #65, #66; release record docs/evidence/release-20261125-revenue-phases-5-9.md). Ten Galpa-Dashak titles packaged (বিচারক and ক্ষুধিত পাষাণ approved; eight drafts on the Monday page; four covers still needed). T15 (US/UK accounts design) waits for its trigger; T20 (stage preview clips) waits for the first narration. |
