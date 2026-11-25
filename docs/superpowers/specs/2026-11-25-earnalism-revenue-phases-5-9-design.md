# Earnalism revenue growth, Phases 5–9: the content engine and recurring income

Status: **draft for owner approval** (brainstormed with the owner 25 Nov 2026; all owner questions answered). Extends `docs/superpowers/specs/2026-11-24-earnalism-revenue-strategy-design.md` (market research, strategies S1–S3) and `plans/pending/earnalism-revenue-growth.md` (Gate 0 and Phases 1–4). Nothing here authorizes spending, publication or a provider change by itself; each still needs the approval this document names.

## 1. Intent

**The owner's goal, in their words:** "Earn steady monthly revenue from subscriptions, schools and licensing, social-media, Google Playbooks and every single scope possible."

Read as: income that arrives every month and can be counted on, from as many independent sources as possible, so no single source decides the month. Every phase therefore switches on or grows a source of **recurring** income, and is "verified" by money received, not by features shipped.

**Why now:** Phases 1–4 built the measurement, the flywheel tools, the Pass split, certificates and classroom mode, and they are live. What stalls revenue today is not missing code but missing supply (2 published titles, no finished film) and owner-time bottlenecks (each post, title and run waits on a separate owner action). The owner's Cloudinary already holds about 150 finished covers, so cover art is no longer the constraint; cleared text, audio and approvals are.

## 2. Decisions made with the owner (25 Nov 2026)

| # | Question | Owner's choice | Consequence |
|---|---|---|---|
| D1 | Growth spending | **Reinvest a share of revenue.** Starts at INR 0; spends only from money earned | Proposed share 30% of each month's receipts (Claude's proposal; owner may change the number). Every individual spend still needs owner approval; anything that does not pay back within 60 days stops |
| D2 | When the paid Pass starts | **Founding member Pass soon**, once about 8–10 titles have full audio, instead of the 10,000-visit trigger (supersedes G0.5) | Reading stays free. Early payers keep INR 99/month or INR 999/year for life |
| D3 | Overseas Bengali families (US/UK) | **Stores only for now** (Google Play Books, other stores); **US/UK paying accounts are a MUST later** | A required phase (9) with a measurable trigger; a baseline deviation needing owner approval at that time |
| D4 | English translations | **AI draft + credited human editor for licensing titles; AI-only, labelled "AI translation", for the rest** | Licensing titles become human-authored works Earnalism owns; the rest give fast bilingual reading with honest labels |
| D5 | How much needs the owner | **Weekly batch approval for two months, then standing permission with limits** | One Monday review page; after two months, anything passing every automatic check goes out on schedule, new or unusual items still wait |
| D7 | Where we sell and post | **Keep the 9 active regions for now** | Every store listing, podcast and licence is restricted to IN, US, GB, BR, SG, MY, ID, PH, TH; a channel that cannot restrict regions is skipped. Widening the list is a later, separate owner decision (policy amendment plus term rules per new region) |
| D6 | Shape of the work | **A content engine that never stops, with income sources switched on as soon as each can pay; phases overlap** | Phase 5 runs continuously; 6–9 each switch on a group of income sources |

## 3. Goals, non-goals, anti-goals

**Goals (12 months from approval):**
- Recurring income every month from at least **five** sources: Pass subscriptions, store sales (Google Play Books), YouTube/social ads and memberships, school licences/CSR, and licensing or sponsorship.
- **Catalogue supply:** 4–6 newly cleared titles a month, each with your cover, labelled AI translation, and audio within the compute allowance.
- **Owner time:** about 20 minutes a week in the batch period; less after standing permission.
- A monthly revenue report that shows every source, and the reinvestment record.

**Non-goals:** regions beyond the 9 (a later owner decision); a phone app before the web funnel converts; serialized drama or coins; competing with Storytel or Pocket FM on catalogue size; Bangladesh as an active region (still deferred).

**Anti-goals (failure even if money arrives):** publishing anything not cleared for its exact edition in all active regions; presenting an AI translation as human work or an AI voice as a human narrator; dark patterns (fake urgency, hard cancellation, pre-ticked consent); spending money that was not earned first or not approved; student or child accounts; licensing a translation we do not own.

## 4. Constraints carried forward

- The 9-region publication whitelist and exact-edition clearance (`contracts/publication-policy.json`, `docs/BOOK_PUBLICATION_POLICY.md`). Safe pool: published before 1931, author died 1955 or earlier; term screen `library/term_check.py`.
- The approved stack and design (Django, PostgreSQL/Neon, Render, R2, Razorpay); no new service without owner approval. Account service India-only until Phase 9 is approved.
- Compute: Colab Pro allowance (100 CU/month) for narration, stills and music; nothing paid beyond it without D1 money.
- Privacy: first-party aggregate analytics only; no third-party trackers on the Reader; no student data.
- Truth: quote cards and posts use the book's exact words; AI voices and translations are labelled.

## 5. Approaches considered

| Approach | Trade-off | Verdict |
|---|---|---|
| One stream at a time (5 then 6 then 7…) | Simple to follow; money starts late and arrives in steps; licensing and schools wait behind everything | Rejected |
| **Continuous content engine + income switched on as each can pay, overlapping phases** | More things running at once; needs the weekly review page to keep the owner's load small | **Chosen by the owner** |
| Fastest cash first (Play Books and school deals before scaling the catalogue) | Earlier first rupee, but few titles to sell, so small and not steady | Rejected |

## 6. The phases

Each phase has: what it switches on, what it needs, and **verified when** (money or a measured outcome). Phases overlap; the order is the order they start.

### Phase 5: Content engine and the Monday review page (starts first, never ends)

**Switches on:** the steady supply every other source needs, and the posting schedule for YouTube and social (S1).

- **5.1 Title pipeline as a batch.** From the shortlist and the owner's Cloudinary covers, produce intake packets (exact source revision, conversion rules, term screen, clearance draft, cover pair with provenance) for 4–6 titles a month. Reuse the ক্ষুধিত পাষাণ packet pattern and `operations/test_intake_packets.py`. Cover matching from Cloudinary (title lettering, front/back pairing by asset id) is recorded in each packet.
- **5.2 Import and publish cleared titles** through the existing audited command (`publish_cleared_editions`), generalized from its two hard-coded books to any packet whose clearance record is owner-approved.
- **5.3 AI translations, labelled.** An English edition per Bengali title (and Bengali per English where useful), marked "AI translation" on the edition and in its metadata; licensing titles are flagged for the editor path (Phase 7).
- **5.4 Audio and films within the compute allowance.** The `eav` run-sheet flow, batched monthly; narration first (it unlocks the Pass), films and reels second.
- **5.3a Who translates (Claude's call):** Claude, inside these working sessions, which adds no paid API call or compute-unit use; the model and date are recorded in each edition's "AI translation" metadata. A paid translation API would be a D1 spend proposed separately.
- **5.5 The Monday review page.** One staff page listing everything waiting: clearance records, cover matches, new editions, the week's posts. Approve or reject per item or all at once; every decision audited. After two months of batch use, a **standing permission** applies: items that pass every automatic check (cleared in all 9 regions, owner cover, exact book words, labelled AI, no claims) go out on schedule; the owner gets a weekly report and can pull anything back. New authors, sponsored items and anything failing a check still wait. **Scope of standing permission (Claude's call, keeping the publication policy):** it covers scheduling and posting films, reels and quote cards of editions that are already cleared, with owner covers. It never clears a new title, a new edition (including an AI translation) or a new format: each clearance record stays an owner decision bound to its exact hashes, batched onto the Monday page.
- **5.6 Scheduled posting** to YouTube (long film + Shorts) first, from approved items, using the existing `operations/social_delivery` upload path; receipts recorded. **How it runs (Claude's call):** Claude starts each posting batch as an attended run (a Render one-off job or a session run, as for migrations and teacher grants today); no stored refresh tokens and no new scheduler service. Instagram and Facebook are added only after the owner names and authorizes those accounts, and their missing public-publish steps are built then. Unattended scheduling with stored tokens would be a separate design change for owner approval.

- **5.7 Covers (answered):** the owner stated on 25 Nov 2026 that the covers in their Cloudinary are their own designs. Each title's pair is exported once into its intake packet (originals' public id, version, bytes and sha256 recorded; 800x1200 JPEG delivery copies), as done for ক্ষুধিত পাষাণ. Cloudinary stays a source the owner uses, not a live integration of the stack.

**Needs from the owner:** YouTube upload authorization (G0.3, already named); approval of the review page as the approval channel; the Colab runs until a cheaper path is approved; Instagram/Facebook account authorization when those are wanted.
**Verified when:** for 4 consecutive weeks, at least 1 new cleared title is published and at least 3 posts go out each week, with the owner spending about 20 minutes a week.

### Phase 6: Founding member Pass and the money dashboard

**Switches on:** subscriptions (S2), the steadiest source.

- **6.1 Founding member plan.** A `BillingPlan` per price (INR 99/month, INR 999/year). Because each `Subscription` is tied to its plan, founding members keep that price for life; a later price change is a new plan. Free reading unchanged; audio, bilingual switch, offline and certificates behind the Pass (the per-format split proven in Phase 3).
- **6.2 Start condition:** about 8–10 titles with full audio (D2). **"Full audio" (Claude's call):** complete Bengali narration of every chapter, published as the title's audio format; English narration is a later addition, not a start condition (the bilingual switch is a text feature). Then: Razorpay sandbox journey (Step 3.5), then live mode with owner sign-off and merchant re-qualification.
- **6.3 Honest Pass page** (Step 3.4) with founding-member wording, real competitor anchors with sources, one-step cancel.
- **6.4 Monthly revenue report** across every source (Pass, stores, YouTube, schools, licensing, sponsorship), entered from provider statements where there is no API, plus the **reinvestment record**: receipts, the share set aside (D1), each approved spend and whether it paid back in 60 days.

**Needs from the owner:** Razorpay test keys, then live sign-off; the reinvestment share (30% proposed).
**Verified when:** the first 3 consecutive months each have Pass revenue, and churn and month-2 retention are reported.

### Phase 7: Stores, licensing and podcast

**Switches on:** store income in the 9 regions, including US and UK families (D3, D7), and partner licensing.

- **7.1 Google Play Books** (52% share): Bengali and English audiobooks and ebooks, sold in the 9 active regions only (D7), with Earnalism as publisher and AI narration disclosed per the store's rules. Other stores (Apple Books, Kobo, Audible/ACX) only where their AI-narration rules allow; checked per store before submitting.
- **7.2 Licensing titles:** AI draft plus a credited human editor (D4), paid from the reinvestment share. The edited translation and its audiobook form a catalogue offered to Storytel, Kuku FM or Pocket FM, licensed for the 9 regions only. A one-time legal review of the licence template is a D1 spend.
- **7.3 Podcast feed** of narrations (YouTube Podcasts, Spotify), with availability limited to the 9 regions where the platform allows it, otherwise not used, as discovery and ad income, served from the existing public asset storage.

**Needs from the owner:** a Google Play Books partner account (G0.4); approval of each editor engagement and the legal review; signature on any licence.
**Verified when:** the first store payout arrives, and at least one licensing proposal is sent with a priced catalogue.

### Phase 8: Schools, CSR and sponsorship, paid

**Switches on:** institutional income (S3) and sponsorship.

- **8.1 Pilot to paid:** a yearly per-class licence (pricing hypothesis INR 200 per student per year, validated with pilots), offered to pilot teachers after 4 weeks of use; manual invoices using the existing numbering (Step 4.3).
- **8.2 CSR and NGO programmes** that fund licences for government schools; a one-page offer and an impact summary from `classroom_report` (aggregate only).
- **8.3 Sponsored learning tracks**, clearly labelled, sold to publishers or English-learning brands; the owner approves each sponsor.

**Needs from the owner:** pilot teachers 2 and 3 (currently on hold), school and CSR introductions, each sponsor approval.
**Verified when:** the first paid institution invoice is settled, and one sponsored track is live.

### Phase 9: US and UK paying accounts (required)

**Switches on:** direct subscriptions from overseas Bengali families (D3: a MUST).

- **Trigger:** starts when the Indian Pass reaches **a paying-member count the owner sets** (Claude proposes 300 paying members), or earlier by owner decision.
- **Scope:** account service for US and GB, USD pricing (about USD 3.99/month or USD 39/year, founding terms), international card payment (Razorpay international or a second processor, owner's choice at that time), overseas sales-tax handling, and the consent and privacy terms those regions need.
- **This is a baseline deviation** (account service beyond India, a possible new payment provider) and needs explicit owner approval of its own design before building.

**Verified when:** the first 3 consecutive months each have USD subscription revenue.

## 7. How the owner's time is kept small

- One weekly sitting (the Monday review page) replaces scattered approvals.
- Run sheets are batched monthly; one Colab session per batch where the allowance permits.
- Spending is proposed with its expected payback, in the monthly report, never ad hoc.
- After two months, standing permission removes routine items from the owner's queue.

## 8. What is left to the builder

- Exact page design of the Monday review page (follow the existing staff and reader patterns; ui-consistency process).
- Per-store AI-narration rules and metadata formats (research at Step 7.1).
- The revenue-report data entry format for providers without an API.
- Which shortlist titles go first in each monthly batch (prefer titles with an owner cover already in Cloudinary).
- Licence template terms (after the legal review).
