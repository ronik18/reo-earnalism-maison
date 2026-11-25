# Earnalism Revenue Phases 5–9 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the software side of the content engine and the recurring-income sources (Pass, stores, licensing, podcast, schools, sponsorship) the owner approved on 25 Nov 2026.

**Architecture:** Everything stays inside the existing Django app and services (no new service). Phase 5 turns the hand-run steps used for ক্ষুধিত পাষাণ into reusable modules and commands, adds a staff "Monday review" queue, and generalizes the audited publish command. Phases 6–8 add small, separately testable pieces on the existing `billing`, `library` and `learning` models. Phase 9 is a design task only, gated by a trigger.

**Tech Stack:** Django 5.2, Python 3.13, PostgreSQL (18 in CI), Pillow, ReportLab (existing `billing.pdf_fonts`), Razorpay adapter (existing), server-rendered templates with `web/i18n.py` strings.

**Spec:** `docs/superpowers/specs/2026-11-25-earnalism-revenue-phases-5-9-design.md` (owner-approved 25 Nov 2026). Earlier context: `plans/pending/earnalism-revenue-growth.md`, `docs/superpowers/specs/2026-11-24-earnalism-revenue-strategy-design.md`.

## Global Constraints

- Publication only for editions whose owner-approved clearance record covers the exact source hash, every active region (IN, US, GB, BR, SG, MY, ID, PH, TH) and the offered format/action.
- Sell, list and post only in those 9 regions (D7); a channel that cannot restrict regions is skipped.
- Standing permission never clears a new title, edition (including an AI translation) or format; it only schedules posts of already-cleared editions.
- AI translations are labelled "AI translation"; editor-revised ones credit the editor by name. AI narration is disclosed.
- Growth spending comes only from reinvested revenue: share `30` percent (setting `MAISON_REINVEST_SHARE_PERCENT`, owner may change), each spend owner-approved, stopped if not paid back within `60` days.
- Founding member Pass: INR `99`/month (`9900` minor) and INR `999`/year (`99900` minor); members keep their plan's price for life.
- Pass start condition: about 8–10 titles with complete Bengali narration of every chapter.
- No paid calls, no stored provider refresh tokens, no new scheduler service, no student accounts, no third-party trackers.
- Tests run on PostgreSQL: `MAISON_ENV=test DATABASE_URL='postgres://maison@127.0.0.1:55433/maison?sslmode=disable' .venv/bin/python manage.py test <labels> --noinput`; set a distinct `MAISON_TEST_DB_NAME` when running suites in parallel.
- Every user-visible string goes through `web/i18n.py` in English and Bengali.

## Review Focus

1. A Wikisource page that is not proofread level 4 (or a missing page) in a requested range: the intake must refuse, not silently import weaker text. Test in Task 1.
2. A clearance record edited after approval (hash of `source.json` no longer matches): publishing must refuse. Test in Task 3.
3. A reviewer approving the same queue item twice, or an item whose underlying file changed after it was queued: the second decision is a no-op and a changed item cannot be approved. Test in Task 5.
4. A founding-plan price change: existing founding subscribers must stay on the old price. Test in Task 7.
5. A store export or podcast item for an edition whose clearance does not cover audio: must refuse. Test in Tasks 10 and 11.

---

## Phase 5: Content engine and the Monday review page

### Task 1: Wikisource intake module and command

**Files:**
- Create: `operations/intake/__init__.py`, `operations/intake/wikisource.py`
- Create: `operations/management/commands/intake_wikisource.py`
- Test: `operations/test_intake_wikisource.py` (fixtures inline)

**Interfaces:**
- Produces: `pages_to_paragraphs(pages: list[dict], *, title: str, keep_hyphen_after: frozenset[str] = frozenset()) -> list[str]` where each page dict is `{"page": str, "revision": int, "quality": int, "wikitext": str}`; raises `IntakeError(code)`.
- Produces: `build_packet(slug: str, title: str, pages: list[dict], *, source_ref: str, source_edition: str, house: str, description: str, first_published: int, author_died: int) -> dict` returning `{"source": dict, "manifest": dict, "clearance": dict}` (manifest validated by `operations.book_source.validate_manifest`, clearance status `DRAFT_PENDING_OWNER_APPROVAL` in the shape of `docs/evidence/publication-clearance-kshudhita-pashan.json`).
- Command: `intake_wikisource <slug> --api-json <path> --title ... --source-ref ... [--keep-hyphen-after <page>]... --write` (reads a saved MediaWiki API response; no network in the command).

- [ ] **Step 1: Write failing tests** `test_rules_match_the_kshudhita_pashan_packet` (feed the 24 pages recorded in the evidence file's revisions via a saved fixture subset of 3 pages: a title page with `{{কেন্দ্র|{{x-larger|…}}}}`, a page ending in `-` and a page ending `{{nop}}`; assert duplicate title dropped, `আলো-`+`ড়িত` → `আলোড়িত`, no `​`, `{{gap}}` starts a paragraph), `test_quality_below_four_is_refused` (`IntakeError.code == "PAGE_NOT_VALIDATED"`), `test_leftover_markup_is_refused` (`"UNKNOWN_MARKUP"` for `[[` or `<ref>`), `test_packet_manifest_validates_and_binds_source_sha`.
- [ ] **Step 2: Run** `... manage.py test operations.test_intake_wikisource --noinput` → FAIL (module missing).
- [ ] **Step 3: Implement** using the exact rules recorded in `library/intake/kshudhita-pashan/manifest.json` `provenance.source_edition`; the clearance draft calls `library.term_check.screen`.
- [ ] **Step 4: Regression:** run the command on the saved ক্ষুধিত পাষাণ API data in a temp dir and assert byte-identical `source.json` (sha `ab59291c…` from its manifest). Run tests → PASS.
- [ ] **Step 5: Commit** `git commit -m "Intake: reusable Wikisource packet builder"`.

### Task 2: Cover pair module and command

**Files:**
- Create: `operations/intake/covers.py`, `operations/management/commands/intake_cover.py`
- Test: `operations/test_intake_covers.py`

**Interfaces:**
- Produces: `derive_pair(front_raw: bytes, back_raw: bytes, originals: dict[str, dict]) -> tuple[bytes, bytes, dict]` returning 800×1200 JPEGs (quality 90) and a provenance dict with schema `earnalism.cover-provenance.v2` exactly as in `library/intake/kshudhita-pashan/cover_provenance.json`.
- Command: `intake_cover <slug> --front <public_id> --back <public_id>` downloads originals from `https://res.cloudinary.com/dzlrhlfpu/image/upload/v<version>/<public_id>.<format>` (version/format/bytes from the Admin API listing at `api.cloudinary.com`, credential injected by the proxy) and writes `front.jpg`, `back.jpg`, `cover_provenance.json` into the packet.

- [ ] **Step 1: Failing tests:** `test_pair_is_800_by_1200_and_hashes_recorded`, `test_non_two_by_three_original_is_refused` (`CoverError("COVER_RATIO")`), `test_downloaded_bytes_must_match_listing_size` (`COVER_BYTES_MISMATCH`), all with Pillow-generated images, network mocked.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** (LANCZOS resize; no metadata copied).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `"Intake: owner cover pair from Cloudinary with provenance"`.

### Task 3: Publish any owner-approved packet

**Files:**
- Modify: `operations/management/commands/publish_cleared_editions.py` (replace hard-coded `BOOKS` and `CLEARANCE_DOC` with packet discovery; keep the two existing books working)
- Test: `operations/test_publish_packets.py`

**Interfaces:**
- Produces: `approved_packets(intake: Path = INTAKE) -> dict[str, Packet]` where `Packet = {slug, edition_slug, folder, clearance_path, clearance_sha256}`; a packet qualifies only if its clearance record (from `manifest.provenance.rights_evidence_refs`) has `status` starting `OWNER_APPROVED`, `approval.approved is True`, no remaining `still_required` entries, `books[slug].source_sha256` equal to the packet's `source.json` sha256, and `front.jpg`/`back.jpg` matching `cover_provenance.json` delivery hashes.
- `--book` choices come from `approved_packets()`.

- [ ] **Step 1: Failing tests:** `test_approved_packet_with_cover_is_discovered`, `test_draft_or_cover_pending_packet_is_skipped`, `test_source_changed_after_approval_is_refused` (`CommandError` naming `SOURCE_HASH_MISMATCH`), `test_existing_bicharak_and_selfish_giant_still_listed`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**; update ক্ষুধিত পাষাণ's clearance `approval.still_required` to `[]` and status `OWNER_APPROVED` now that its cover is attached (owner approval recorded 25 Nov 2026; cover committed).
- [ ] **Step 4: Run** `operations library` suites → PASS.
- [ ] **Step 5: Commit** `"Publish: discover owner-approved intake packets"`.

### Task 4: Translation fields and labels

**Files:**
- Modify: `library/models.py` (`Edition`), Create: `library/migrations/0008_edition_translation.py`
- Modify: `templates/web/title.html`, reader header template, `web/i18n.py`
- Test: `library/test_translation_label.py`

**Interfaces:**
- Produces on `Edition`: `translated_from = ForeignKey('self', null=True, blank=True, on_delete=PROTECT, related_name='translations')`, `translation_method = CharField(max_length=16, blank=True, choices=[('', ''), ('ai', 'ai'), ('ai_edited', 'ai_edited')])`, `translation_credit = CharField(max_length=160, blank=True)`, `translation_model = CharField(max_length=80, blank=True)`. DB check constraints: method non-empty iff `translated_from` set; `ai_edited` requires non-empty `translation_credit`; locale differs from source (enforced in `clean()` and service).
- Command: `intake_translation <slug> --from <source_slug> --source <translated source.json> --method ai|ai_edited [--credit <editor>] --model <model id>` writes a packet (manifest with `edition.language` the target locale, `provenance.source_edition` naming the source packet sha256, method, model and date) plus a `DRAFT_PENDING_OWNER_APPROVAL` clearance draft for the new edition; the translated text itself is produced by Claude in-session (design 5.3a) and passed in as the file.
- i18n keys: `ai_translation` ("AI translation" / "এআই অনুবাদ"), `translated_by` ("Translated with AI, edited by {name}" / "এআই-সহায়ক অনুবাদ, সম্পাদনা: {name}").

- [ ] **Step 1: Failing tests:** `test_intake_translation_writes_draft_packet_with_method_and_model`, `test_ai_translation_is_labelled_on_title_and_reader`, `test_edited_translation_credits_the_editor`, `test_database_rejects_edited_without_credit` (`IntegrityError`), `test_original_editions_show_no_label`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** + `makemigrations library`. **Step 4: Run** `library web` → PASS.
- [ ] **Step 5: Commit** `"Library: label AI and editor-revised translations"`. Then run the ui-consistency verifying pass on the two touched templates.

### Task 5: Monday review queue (model, service, staff page)

**Files:**
- Modify: `operations/models.py`; Create: `operations/migrations/0002_review_item.py`, `operations/review.py`
- Modify: `web/urls.py`, `web/views.py`; Create: `templates/web/staff_review.html`
- Test: `operations/test_review.py`

**Interfaces:**
- Produces model `ReviewItem(id UUID, kind ∈ {'clearance','cover','edition','post'}, ref CharField(240), sha256 CharField(64), summary JSONField, status ∈ {'pending','approved','rejected'}, decided_by FK user null, decided_at null, decision_note TextField(blank), standing BooleanField(default False), created_at)`; unique `(kind, ref, sha256)`.
- Produces `queue(kind: str, ref: str, sha256: str, summary: dict) -> ReviewItem` (idempotent), `decide(actor, item_ids: list[UUID], decision: str, note: str = '') -> int` (requires `is_staff`, `is_verified` and perm `operations.decide_review`; re-hashes the referenced file and refuses `REVIEW_ITEM_CHANGED`; audits `review.decided` per item; already-decided items are skipped and not counted), `auto_checks(item) -> list[str]` (failure codes; empty means pass), `standing_permission_active(now) -> bool` (true when setting `MAISON_REVIEW_STANDING_FROM` is set and `now >= it`; owner sets it two months after the first batch).
- Standing permission applies only to `kind == 'post'` items whose edition has an approved `clearance` item and passing `auto_checks`; such items are created `status='approved', standing=True` and listed in the weekly report.
- Command `review_report --week <YYYY-Www>` lists items decided that week, marking `standing=True` ones, for the owner's weekly report.
- Page `GET/POST /<locale>/staff/review/`: pending items grouped by kind with checkboxes, "Approve selected" / "Reject selected"; staff only (others 404).

- [ ] **Step 1: Failing tests:** `test_queue_is_idempotent`, `test_decide_requires_permission_and_audits`, `test_second_decision_is_a_no_op`, `test_changed_file_cannot_be_approved`, `test_standing_permission_never_applies_to_clearance_or_edition`, `test_standing_post_requires_passing_checks`, `test_page_is_staff_only_and_lists_pending`, `test_weekly_report_marks_standing_items`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (+ migration). **Step 4: Run** `operations web` → PASS; ui-consistency verifying pass on the page.
- [ ] **Step 5: Commit** `"Review: Monday batch approval queue"`.

### Task 6: Attended posting batch for approved posts

**Files:**
- Create: `operations/management/commands/post_approved.py`
- Test: `operations/test_post_approved.py`

**Interfaces:**
- Consumes: `ReviewItem` (`kind='post'`, `status='approved'`), `operations.social_delivery.bridge.prepare`, `Authority`, `Delivery`.
- Command: `post_approved --provider youtube [--execute]`; dry run by default prints the batch; `--execute` reads the access token from env `EARNALISM_YOUTUBE_ACCESS_TOKEN` (in memory only), uploads each item with an exact-action `Authority`, and stores the provider receipt in `ReviewItem.summary["receipt"]`. Only provider `youtube` is accepted until the owner authorizes others.

- [ ] **Step 1: Failing tests (transport mocked):** `test_dry_run_changes_nothing`, `test_execute_uploads_only_approved_posts_once`, `test_unknown_provider_is_refused`, `test_missing_token_is_refused_without_partial_upload`.
- [ ] **Step 2–4:** Run → FAIL; implement; run `operations` → PASS.
- [ ] **Step 5: Commit** `"Posting: attended batch for approved YouTube posts"`.

## Phase 6: Founding member Pass and the money record

### Task 7: Founding member plans

**Files:**
- Create: `billing/founding.py`, `billing/management/commands/founding_pass.py`
- Test: `billing/test_founding.py`

**Interfaces:**
- Produces `ensure_founding_plans(actor) -> dict[str, BillingPlan]` creating (idempotently) offers `founding-pass-month` (`price_minor=9900`, `interval_unit='month'`) and `founding-pass-year` (`99900`, `'year'`), `currency='INR'`, formats `['audio','reader']`, `approved=False`, `active=False`, `terms_version='founding-pass-v1'`; audited.
- Produces `activate_founding_plans(actor, *, audio_titles: int) -> None` refusing `FOUNDING_START_CONDITION` when `audio_titles < 8` and `FOUNDING_MERCHANT_UNAPPROVED` unless each plan has `merchant_approved_at`.
- Command: `founding_pass create|status|activate`.

- [ ] **Step 1: Failing tests:** `test_plans_created_once_inactive`, `test_activation_needs_eight_audio_titles_and_merchant_approval`, `test_price_change_leaves_existing_subscribers_on_founding_plan` (create a new plan at 12900; the existing `Subscription.plan.offer.price_minor` stays 9900).
- [ ] **Step 2–4:** Run → FAIL; implement; run `billing` → PASS.
- [ ] **Step 5: Commit** `"Billing: founding member Pass plans (inactive until start condition)"`.

### Task 8: Honest Pass page with founding wording

**Files:** Modify: the Pass page template and `web/i18n.py`; Test: `web/test_pass_page.py`

**Interfaces:** context `founding_open: bool` (true when both founding offers are `active`), `anchors: list[dict(name, price, source_url)]` with Storytel INR 149/month, Kuku FM INR 899/year, SpeakX ~INR 300/month and their sources from the strategy doc §2.2.

- [ ] **Step 1: Failing tests:** `test_founding_price_and_lifetime_wording_shown_only_when_open`, `test_every_anchor_has_a_source_link`, `test_cancel_link_is_one_step_from_account`, `test_no_countdown_or_preticked_box`.
- [ ] **Step 2–4:** Run → FAIL; implement; run `web` → PASS; ui-consistency verifying pass.
- [ ] **Step 5: Commit** `"Pass page: founding member offer with sourced anchors"`.

### Task 9: Revenue and reinvestment record

**Files:**
- Create: `billing/revenue.py`, `billing/migrations/0012_revenue_ledger.py`, `operations/management/commands/revenue_report.py`
- Modify: `billing/models.py` (or new `billing/revenue_models.py` imported from it), `config/settings.py` (`MAISON_REINVEST_SHARE_PERCENT`, default `30`)
- Test: `billing/test_revenue.py`

**Interfaces:**
- Models: `RevenueEntry(month DateField first-of-month, source ∈ {'pass','play_books','youtube','podcast','schools','licensing','sponsorship','other'}, amount_minor PositiveBigInteger, currency, reference CharField(160), recorded_by FK, created_at)`; `ReinvestmentEntry(month, kind ∈ {'set_aside','spend'}, amount_minor, purpose, approved_by FK null, payback_due DateField null, paid_back BooleanField null)`; spend requires `approved_by` and `payback_due` (DB check).
- `month_report(month: date) -> dict` with `by_source` (pass derived from settled `Invoice` rows for founding plans plus manual entries), `total_minor`, `set_aside_due_minor = total × share // 100`, `spends`, `overdue_paybacks` (spends past `payback_due` with `paid_back` not true).
- Command: `revenue_report --month 2026-12 [--record-set-aside]`.

- [ ] **Step 1: Failing tests:** `test_report_sums_by_source_and_computes_thirty_percent`, `test_spend_without_approval_is_rejected_by_database`, `test_spend_past_sixty_days_unpaid_is_flagged`.
- [ ] **Step 2–4:** Run → FAIL; implement + migration; run `billing operations` → PASS.
- [ ] **Step 5: Commit** `"Revenue: monthly report and reinvestment record"`.

## Phase 7: Stores, licensing and podcast

### Task 10: Google Play Books export bundle (9 regions)

**Files:** Create: `library/store_export.py`, `library/management/commands/store_export.py`; Test: `library/test_store_export.py`

**Interfaces:** `export_play_books(edition_id: UUID, out_dir: Path) -> dict` writes cover, chapter audio list, metadata JSON (`publisher: "Earnalism"`, `territories: list(settings.MAISON_PUBLICATION_TERRITORIES)`, `narration: "ai"` disclosure, translation label/credit from Task 4) and returns the manifest; refuses `STORE_FORMAT_NOT_CLEARED` unless the live revision's clearance evidence covers format `audio` in every territory.

- [ ] **Step 1: Failing tests:** `test_bundle_lists_exactly_the_nine_territories`, `test_audio_not_cleared_is_refused`, `test_ai_narration_and_translation_disclosed`.
- [ ] **Step 2–4:** Run → FAIL; implement; run `library` → PASS.
- [ ] **Step 5: Commit** `"Stores: Play Books export bundle restricted to the 9 regions"`.

### Task 11: Podcast feed

**Files:** Modify: `web/urls.py`, `web/views.py`; Create: `web/podcast.py`; Test: `web/test_podcast.py`

**Interfaces:** `GET /podcast/<locale>.xml` (RSS 2.0 with iTunes tags) listing published units whose edition's `access_policy['audio']` is `free` and whose clearance covers audio; each item links the title page with UTM `utm_source=podcast`. Public cache headers as other public pages. Platform-side region limits are set by hand per platform (documented in `docs/CAMPAIGN_LINKS.md`); platforms that cannot limit regions are not used.

- [ ] **Step 1: Failing tests:** `test_feed_lists_only_cleared_free_audio`, `test_items_link_with_podcast_utm`, `test_feed_is_valid_xml_with_itunes_namespace`.
- [ ] **Step 2–4:** Run → FAIL; implement; run `web` → PASS.
- [ ] **Step 5: Commit** `"Podcast: public feed of cleared narrations"`.

### Task 12: Licensing catalogue export

**Files:** Create: `library/management/commands/licensing_catalogue.py`; Test: `library/test_licensing_catalogue.py`

**Interfaces:** `licensing_catalogue --out <path.csv>` lists only editions with `translation_method == 'ai_edited'` and a non-empty credit, plus their source edition, audio duration, cover URL and `territories` (the 9). AI-only translations are never listed.

- [ ] **Step 1: Failing tests:** `test_only_editor_revised_translations_listed`, `test_territories_column_is_the_nine`.
- [ ] **Step 2–4:** Run → FAIL; implement; run → PASS.
- [ ] **Step 5: Commit** `"Licensing: catalogue export of editor-revised translations"`.

## Phase 8: Schools, CSR and sponsorship

### Task 13: Institution invoices

**Files:** Create: `billing/institution.py`, `billing/management/commands/institution_invoice.py`; Test: `billing/test_institution.py`

**Interfaces:** `issue_institution_invoice(actor, *, institution: str, classes: int, students: int, price_per_student_minor: int, period_start: date) -> Invoice` (one year), numbered through `billing.numbering.reserve` and rendered through `billing.documents.issue_document`; no card checkout; refuses non-positive counts. The pilot price hypothesis (`20000` minor per student per year) is a default the command shows, not a constant.

- [ ] **Step 1: Failing tests:** `test_invoice_uses_the_existing_series_and_totals`, `test_zero_students_refused`, `test_invoice_requires_finance_permission`.
- [ ] **Step 2–4:** Run → FAIL; implement; run `billing` → PASS.
- [ ] **Step 5: Commit** `"Schools: yearly per-class institution invoices"`.

### Task 14: Sponsored learning tracks

**Files:** Modify: `learning/models.py` (`Track`), Create: `learning/migrations/0006_track_sponsor.py`; Modify: track template, `web/i18n.py`; Test: `learning/test_sponsor.py`

**Interfaces:** `Track.sponsor_name CharField(120, blank)`, `Track.sponsor_url URLField(blank)`, `Track.sponsor_approved_by FK user null`; DB check: name set ⇒ approver set. Track page shows "Sponsored by {name}" / "সৌজন্যে {name}" with `rel="sponsored noopener"`; worksheets print the same line.

- [ ] **Step 1: Failing tests:** `test_sponsor_label_on_page_and_worksheet`, `test_unapproved_sponsor_rejected_by_database`.
- [ ] **Step 2–4:** Run → FAIL; implement + migration; run `learning web` → PASS.
- [ ] **Step 5: Commit** `"Learning: labelled sponsored tracks"`.

## Phase 9: US and UK paying accounts (required, gated)

### Task 15: Write the Phase 9 design when the trigger is met

No code until its own design is approved. Trigger: the Indian Pass reaches the owner-set paying-member count (proposed 300), read from `revenue_report`/subscriptions, or an earlier owner decision.

- [ ] **Step 1:** When triggered, brainstorm and write `docs/superpowers/specs/<date>-us-uk-accounts-design.md` covering account service for US/GB, USD founding pricing (about USD 3.99/month, USD 39/year), the payment provider choice, overseas sales tax, and consent/privacy terms; mark it a baseline deviation needing owner approval.
- [ ] **Step 2:** After approval, write its implementation plan with superpowers:writing-plans.

## Owner actions this plan waits on (not code)

| Needed for | Action |
|---|---|
| Tasks 3, 6 | Approve clearance records and posts on the Monday page; authorize YouTube upload (G0.3) |
| Phase 5 audio | Run the monthly Colab run sheet |
| Task 7 activation | Razorpay test keys, then live sign-off and merchant approval |
| Task 9 | Confirm or change the 30% reinvestment share |
| Task 10 | Google Play Books partner account |
| Task 12 | Approve each editor engagement and the one-time legal review (reinvested money) |
| Task 13 | Pilot teachers 2 and 3; school and CSR introductions |
| Task 14 | Approve each sponsor |
| Task 15 | Set the paying-member trigger number |

## Order of execution

Tasks 1 → 2 → 3 → 5 → 6 first (the content engine), Task 4 alongside. Tasks 7–9 once Phase 5 publishes titles. Tasks 10–14 in any order as their owner actions arrive. Update the Progress table in `plans/pending/earnalism-revenue-growth.md` after each task.
