# Earnalism revenue strategy: market research and three strategies

Status: **proposal for owner decision**. Nothing in this document reactivates paid billing, publishes a title, posts to social media or authorizes spending. Each of those still needs the owner approval that AGENTS.md and APPROVED_BASELINE.md require.

Date: 24 November 2026. Research method: public web sources (cited inline). The Hyper MCP competitor-intel tools (HyperSEO, Firecrawl, social scrapers) could not connect from this session, so there is no scraped baseline yet. All figures below are third-party or company-reported and are labelled as such.

## 1. Where Earnalism stands today (from the repository)

- **Product:** one Django app with a Reader (Bengali/English editions, paragraph-level `TimingMap` for synchronized audio), a Player, learning `Track`/`Lesson`/`Quiz`, collections and search. Free for verified members in India (`contracts/india-first-service-policy.json`, `MAISON_FREE_ACCESS=true`).
- **Paid billing is built but switched off:** Razorpay checkout, mandates, subscriptions, invoices and refunds exist in `billing/`. Planned Earnalism Pass prices are **INR 99/month and INR 999/year**, shown struck through (`docs/FREE_ACCESS_ROLLOUT.md`).
- **Content engine:** the `earnalism-audiovisual` skill turns one book title into an audiobook film plus one or two story reels at zero extra spend (Colab Pro, five-voice roster). `operations/social_delivery` can stage private uploads to YouTube, Instagram, Facebook Page and X, but nothing is published.
- **Catalogue:** two titles (The Selfish Giant, বিচারক) and learning tracks for both.
- **Territories:** account service is India only. Book publication is limited to **9 active regions: IN, US, GB, BR, SG, MY, ID, PH, TH** (`contracts/publication-policy.json`, owner amendment 22 Nov 2026). **Bangladesh is deferred**, not active.

## 2. Market research

### 2.1 Market size and demand

| Signal | Figure | Source and confidence |
|---|---|---|
| India audiobook market, 2025 | USD 322M–443M; ~7–11% CAGR | Paid-report estimates that disagree by ~35% ([Research and Markets](https://www.researchandmarkets.com/reports/6095691/india-audiobooks-market-report-forecast), [Expert Market Research](https://www.expertmarketresearch.com/reports/india-audiobooks-market), [Zorba Books](https://www.zorbabooks.com/the-rise-of-audiobooks-should-you-publish-audio-versions-of-your-book/)) |
| Indic-language preference | 98% of Indian internet users access Indic-language content; ~57% of urban users prefer it | IAMAI/Kantar, via [Business Standard](https://business-standard.com/india-news/india-s-internet-users-to-exceed-900-mn-in-2025-driven-by-indic-languages-125011600835_1.html) |
| Bengali speakers in India | ~97M (Census 2011) | [UNESCO](https://ar.wal.unesco.org/index.php/countries/india/languages/bengali) |
| Bangladesh internet users | 77.7M (44.5% penetration), start of 2025 | [DataReportal](https://datareportal.com/reports/digital-2025-bangladesh) |
| Bengali diaspora demand | ShunBoi (Bangla audiobook app) reports >70% of listeners are expatriates in US, UK, Canada, Australia, Middle East | Company-reported, [TBS News](https://www.tbsnews.net/features/panorama/shunboi-startup-feeding-hunger-bangla-audiobooks-589362) |
| English-learning demand | ~250M learners claimed; SpeakX charges ~INR 300/month and reports 10M+ learners | Company-reported, [NITI Frontier Tech](https://frontiertech.niti.gov.in/story/ai-native-platform-enables-10-million-indians-to-learn-spoken-english-anytime-anywhere), [Entrepreneur](https://india.entrepreneur.com/?p=89023) |
| Free public alternative | Rashtriya e-Pustakalaya: free books in 23 languages, 2 lakh+ users | [Organiser](https://organiser.org/2025/02/13/277809/bharat/rashtriya-e-pustakalaya-indias-first-digital-library-transforming-education/) |

**Reading:** the audio market is real but mid-sized and dominated by a few players. Bengali is a large language with a proven appetite for audio stories (see 2.2), and a diaspora that pays. English-learning is the largest willingness-to-pay pool among Earnalism's adjacent markets.

### 2.2 Competitor intelligence

| Competitor | Model and price | Scale | What it means for us |
|---|---|---|---|
| **Pocket FM** | Pay per episode (coins) + ads; ~USD 415M of ~USD 500M run-rate from unlocks | ARR ~USD 430M (Mar 2026); ~98% revenue outside India | Micro-transactions work for serialized drama, mostly abroad. ([Inc42](https://inc42.com/buzz/pocket-fm-claims-ebitda-profitability-crosses-400-mn-arr/), [TechCrunch](https://techcrunch.com/2025/10/15/indias-kuku-snags-85m-as-mobile-content-wars-intensify/)) |
| **Kuku FM / Kuku TV** | Subscription only: INR 899/year, INR 399/quarter | FY26 revenue reported INR 1,484 Cr; 2.5M–10M payers (contested); >60% usage now video | Annual subscription at < INR 1,000 converts in India; the market is moving from audio to video. ([Inc42](https://inc42.com/buzz/ipo-bound-kuku-technologies-turns-profitable-in-fy26-revenue-surges-6x-to-₹1484-cr/), [Inc42](https://inc42.com/buzz/after-2-5-mn-paid-subscribers-kuku-fm-25-mn-fuel-expansion/)) |
| **Storytel India** | INR 149 (Select) / INR 299 (Unlimited) per month | 400,000+ titles; has a Bengali category | Our INR 99 sits 34% below the cheapest big-catalogue plan; we cannot win on catalogue size. ([Storytel](https://www.storytel.com/in)) |
| **Pratilipi** | Premium subscription + coins + author "Superfan" plans; ~90% of revenue from renewals | FY26 revenue expectation ~INR 188 Cr | Renewal-driven subscriptions are the revenue engine for Indic stories. ([Inc42](https://inc42.com/startups/pratilipi-content-ip-stack-profitability)) |
| **Sunday Suspense (Mirchi Bangla)** / **Goppo Mir-er Thek** | Free on YouTube; ads + sponsorship | ~3M and ~2M YouTube subscribers (company/2023 figures) | Bengali dramatized classics have a proven mass audience on YouTube. ([EdTimes](https://edtimes.in/terribly-underrated-tales-of-horror-are-on-the-radio-in-bengal/), [Outlook](https://www.outlookindia.com/amp/story/culture-society/artist-mir-afsar-ali-explores-sound-and-stories-in-a-world-which-only-wants-to-see)) |
| **Bengali Fairy Tales** and peers | Free animated kids' stories; YouTube ads | 10.4M subs (Sep 2026); peers 1.3M–2.2M | Bengali story video at scale exists; it is ad-funded and has no learning layer. ([vidIQ](https://vidiq.com/youtube-stats/channel/@bengalifairytales/), [vidIQ](https://vidiq.com/youtube-stats/channel/UCGLigkqc6NUy9ZAFNpConhg)) |
| **Amar Chitra Katha / Tinkle apps** | ~INR 399/year (discounted from 899) | Legacy Indian story IP | Indian parents pay a few hundred rupees a year for story apps. ([ACK](https://www.amarchitrakatha.com/?p=89787)) |
| **SpeakX** | ~INR 300/month | 10M+ learners claimed | English learning carries roughly 3× our planned price. ([Mint via Magzter](https://www.magzter.com/de/stories/newspaper/Mint-Ahmedabad/STARTUPS-HELP-SMALLTOWN-INDIA-BREAK-BIGCITY-ENGLISH-BARRIER)) |

**The gap no competitor fills:** a **bilingual Bengali ⇄ English** library where the same classic is a cinematic audiobook film, a synchronized read-along text and a quiz-backed learning track. Pocket FM, Kuku and Storytel sell listening. Bengali Fairy Tales and Sunday Suspense sell free, ad-funded viewing. SpeakX sells English drills without literature. Earnalism already has the data model (`Edition` per language, `TimingMap`, `Track`/`Quiz`) to own the overlap: **"learn and love stories in two languages."**

### 2.3 Platform monetization economics (India)

| Channel | Realistic yield | Source and confidence |
|---|---|---|
| YouTube long-form | ~INR 30–150 RPM; education at the top, Hindi/vernacular entertainment at the bottom; English earns 2–4× Hindi; Bengali not measured | Creator-economy blogs, inconsistent ([upgrowth](https://upgrowth.in/youtube-cpm-india-guide-2026/), [fluxnote](https://fluxnote.io/guides/youtube-cpm-rates-india-by-niche-2026)) |
| YouTube Shorts | ~INR 3–30 per 1,000 views; ~INR 3,000–12,000 per 1M views | Same caveats ([digitalnest](https://www.digitalnest.in/blog/how-much-does-youtube-pay-in-india/), [lilachbullock](https://www.lilachbullock.com/youtube-1-million-views-income-india-long-vs-shorts/)) |
| Instagram Reels (India) | No standard per-view payout; income is brand deals and affiliates | Third-party, unconfirmed by Meta ([lilachbullock](https://www.lilachbullock.com/how-much-does-instagram-pay-for-reels-views-in-india/)) |
| Facebook | Content Monetization is invite-only; Meta paid ~USD 3B to creators in 2025 | [Meta newsroom](https://about.fb.com/news/2026/03/creator-fast-track-grow-your-audience-earn-money-on-facebook/) |
| Google Play Books audiobooks | **52% revenue share** to the publisher; India-based publishers eligible | [Google Play](https://play.google.com/books/publish/autonarrated) |

**Conclusion:** short-form social video is a **discovery channel, not an income channel**, in India. Meaningful money comes from (a) YouTube long-form ads and memberships, (b) owned subscriptions, (c) institutional licences and (d) selling or licensing the audiobooks we already produce.

### 2.4 Content-rights opportunity (the moat)

Every published title must be cleared in all 9 active regions. The binding rules are the UK and Brazil (life + 70 years) and the US (works published before 1931 are public domain). In practice, original works **published before 1931 by authors who died in 1955 or earlier** are the safe pool, still subject to per-edition clearance under `BOOK_PUBLICATION_POLICY.md`. This pool includes Tagore (d. 1941), Upendrakishore Ray Chowdhury (d. 1915), Sukumar Ray (d. 1923), Bankim Chandra (d. 1894), Sarat Chandra (d. 1938), Abanindranath Tagore (d. 1951) and Bibhutibhushan's *Pather Panchali* (1929; d. 1950).

**The key point:** an existing English translation is usually still under copyright, but **a new Earnalism translation is a new copyrighted work that Earnalism owns**. Each bilingual title therefore produces owned IP (an English text, an English audiobook and a film) that can be licensed to stores and platforms. No competitor in section 2.2 holds a bilingual catalogue of this pool. This is legal reasoning for planning only; each edition still needs the policy's exact-edition assessment.

## 3. Statistical model

A Monte Carlo simulation (20,000 runs, triangular distributions) of first-12-month revenue. The script is `docs/superpowers/specs/2026-11-24-revenue-model.py`. Every input is an **assumption range drawn from section 2**, not a measured Earnalism number: Earnalism has no traffic, conversion or willingness-to-pay data yet.

| Strategy | P10 | **P50** | P90 | Main drivers (widest input ranges) |
|---|---|---|---|---|
| S1 Content flywheel | INR 2.4 L | **INR 4.0 L** | INR 6.6 L | views per film, month of YouTube Partner Program eligibility, RPM |
| S2 Bilingual Pass (B2C) | INR 2.0 L | **INR 4.9 L** | INR 10.6 L | MAU reached (fed by S1), free-to-paid conversion (1–6%), churn |
| S3 Classroom licences + CSR | INR 1.7 L | **INR 3.3 L** | INR 5.7 L | institutions signed, price per seat (**no market data found**) |
| **All three together** | INR 8.7 L | **INR 12.9 L** | INR 19.2 L | |
| S2 annualized run-rate in year 2 | INR 18 L | **INR 45 L** | INR 98 L | MAU 20k–400k × 1–6% × INR 70–99 |

Notes on reading the model:

- **Year 1 is an audience-building year.** About INR 13 lakh at the median is not yet a business. The value is in the year-2 subscription run-rate, which compounds only if S1 builds the audience. The three strategies are **one flywheel, not alternatives**.
- **What would invalidate the model:** a published film averaging under 2,000 monthly views after 3 months, or Pass conversion under 1% of MAU. Both are measured in the first phases of the plan, so the model gets replaced by real data within about 90 days.
- **Not modelled:** Bangladesh and diaspora USD pricing (Bangladesh is a deferred region), IP licensing deals with Storytel, Kuku or Pocket FM (no basis to estimate), and the cost of owner time.

## 4. The three strategies

### Strategy 1: "One story, seven earnings": the content flywheel

**Behaviour to cause:** a viewer who meets a story on Shorts or Reels watches the full film on YouTube, then opens the read-along on Earnalism.
**Obstacle:** nobody has seen the stories yet (traffic, not conversion). Per the marketing skill, this is a traffic problem: do not tune pages before traffic exists.

From every title the `earnalism-audiovisual` pipeline already produces, derive:

1. **YouTube long-form audiobook film** (AdSense; channel memberships once eligible). Bengali and English versions are two videos and two audiences.
2. **2–4 Shorts / Reels / Facebook Page Reels** per title, for discovery, each linking to the title page.
3. **Quote cards and carousel posts** from `Paragraph` text, for Instagram, Facebook and Pinterest (free reach).
4. **Google Play Books audiobook** (52% revenue share), plus other stores where their AI-narration policy allows it.
5. **Licensing the owned English translation and audiobook** to Storytel, Kuku FM or Pocket FM as a catalogue deal.
6. **Sponsored learning tracks** (for example, a reading-week track sponsored by a publisher or an English-learning brand), clearly labelled as sponsored.
7. **Podcast feed** of the narration (Spotify and YouTube Podcasts) as a further discovery surface.

Cadence target: **2–3 titles a month** within the 100 CU/month compute allowance.
Proof metric: views per film at day 30, and click-through from YouTube to the Earnalism title page (UTM-tagged).

### Strategy 2: the Bilingual Earnalism Pass (freemium B2C)

**Behaviour to cause:** a member who finished one free story starts the Pass.
**Obstacle:** the value of paying is unclear when the story is already free on YouTube.

- **Free forever:** reading every released edition, and the first chapter of every audiobook. This keeps the current free promise honest.
- **Pass (INR 99/month, INR 999/year, as already planned):** full audio and read-along with paragraph highlighting (`TimingMap`), ad-free films, the Bengali ⇄ English parallel switch, offline downloads, learning tracks with quizzes and a completion certificate, and new titles one week early.
- **Anchor honestly** against real alternatives: Storytel INR 149, Kuku INR 899/year, SpeakX ~INR 300/month. No decoy tier, no fake countdown, and cancelling takes one confirmed step (marketing-skill honesty rules).
- **Later, with an owner decision:** a diaspora tier priced in USD for US and GB families ("Bengali for your children"), the market ShunBoi reports as >70% of its listeners. US and GB are already active publication regions, but account service is India-only today.

Proof metric: free-to-paid conversion among members who completed at least one story, and month-2 retention.

### Strategy 3: Classroom licences for schools, tuition centres and CSR programmes

**Behaviour to cause:** an English or Bengali teacher uses an Earnalism story in class every week.
**Obstacle:** schools buy through relationships and slow procurement, and student accounts would mean processing children's data.

- **Teacher-only licence (recommended):** the teacher's account projects the read-along film in class and downloads printable worksheets and quiz sheets. **No student accounts**, so no new child-data processing, which matches the existing no-child-directed-service scope and DPDP caution.
- **Pricing hypothesis:** about INR 200 per student per year, billed per class. There is **no public market data** on this price, so validate it in free pilots before quoting it.
- **Channels:** Bengali-medium and low-fee English-medium private schools and tuition centres in West Bengal; NGO and CSR reading programmes that fund licences for government schools (the free e-Pustakalaya has no narration, film or quiz layer).

Proof metric: weekly classroom sessions per pilot teacher across 4 weeks, then pilot-to-paid conversion.

### How they connect

```
S1 films and reels ──► YouTube ad revenue + store/licensing revenue
        │  (UTM links)
        ▼
Earnalism free reader ──► S2 Pass (B2C)  ──► diaspora tier (later)
        │
        └──► teachers discover it ──► S3 classroom licences / CSR
```

## 5. Goals, non-goals and anti-goals

- **Goal (12 months):** about INR 13 L median total revenue, 1,000+ paying Pass members and 5+ paying institutions, with real funnel data replacing every assumption in section 3 by day 90.
- **Non-goals:** competing with Storytel or Pocket FM on catalogue size; serialized drama; an Android or iOS app before the web funnel converts.
- **Anti-goals (failure even if revenue appears):** publishing a title that is not cleared in all active regions; dark patterns (fake urgency, hard cancellation, pre-ticked opt-ins); collecting children's data without a qualified consent design; paid spending without the owner's budget authority.

## 6. Approaches considered

| Approach | Trade-off | Verdict |
|---|---|---|
| **A. Flywheel first, then monetize owned channels (S1 → S2 → S3)** | Slower first revenue; builds owned audience and IP; uses the existing pipeline | **Recommended** |
| B. Turn on the paid Pass now | Fastest to "revenue switched on", but only 2 titles and no traffic, so near-zero conversion; uses up the launch moment | Rejected for now |
| C. Pocket FM-style coins per episode | Proven at scale for serialized drama; poor fit for short classics and learning; needs a new billing model (a baseline deviation) | Rejected |
| D. Ads on the Earnalism site | Low India RPMs; hurts the calm reading-room design; adds third-party trackers that conflict with the privacy posture | Rejected |

## 7. What is left to the builder

See `plans/pending/earnalism-revenue-growth.md` for phases, steps, verification and the owner-decision gate.
