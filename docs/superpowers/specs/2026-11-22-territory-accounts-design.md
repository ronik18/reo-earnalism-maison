# Territory accounts, notices, publication scope and legacy URLs — design

Owner decisions, 22 November 2026. This narrows `docs/superpowers/plans/2026-11-22-global-readiness.md` (D1–D6). Research below is from public secondary and regulator sources; it is engineering input, **not legal clearance**. A territory is switched on only after the owner signs its notice row.

## Owner directions after approval (22 November 2026)

- No unnecessary guardrails or blockers: notice rows ship without an `approved_by` sign-off gate; production only refuses to start if an active territory has no notice row.
- One English interface; the library holds every book language and readers filter by language themselves.
- Books and audiobooks are onboarded from scratch; the legacy platform is retired after cutover (plan Phase 5).

## Intent

All-ages, general content. Accounts need no age question where the law of the visitor's country does not require parental permission for a child's account; elsewhere accounts are adult-only (self-declared 18+). Reading content itself stays as approved (signed-in, free). Launch territories: IN, US, GB, BR, SG, MY, ID, PH, TH. Books publish when cleared for those nine countries only.

## Per-territory account rule (my call from the research; owner signs off)

| Territory | Parental-permission rule found | Account mode |
|---|---|---|
| IN | DPDP s.9 child consent not yet in force (commences ~13 May 2027 per repo evidence) | `open` — no age question; switch to `adult_only` or guardian before commencement |
| US | COPPA consent for under-13 if child-directed or actual knowledge; a library with children's classics risks "mixed audience" | `adult_only` |
| GB | UK GDPR Art. 8: under-13 consent needs parental authorisation; Children's code for services likely accessed by children | `adult_only` (can move to `open` after a Children's-code DPIA) |
| BR | LGPD Art. 14: specific parental consent for children's data; ECA Digital enforceable 17 Mar 2026 | `adult_only` |
| SG | PDPC guidelines: parent consents for under-13 | `adult_only` |
| MY | PDP Regulations: parent consents for under-18 | `adult_only` |
| ID | PDP Law Art. 25 and GR 17/2025: parent approval for children | `adult_only` |
| PH | Parental consent for under-18 | `adult_only` |
| TH | PDPA s.20: parent consent for minors (under 10 compulsory) | `adult_only` |

`open`: signup asks no age or capacity question. `adult_only`: signup requires the neutral declaration "I am 18 or older"; no date of birth is stored, only the declaration and notice version (existing audit pattern). India's existing guardian path is retired from signup while India is `open`; existing guardian code stays for the 2027 switch.

## Approaches considered

1. **Per-territory mode in config (chosen).** One setting per territory read by enrollment; laws change by configuration, not code. Smallest change to existing `accounts/enrollment.py`.
2. Hard-coded country lists in views — rejected: every legal change becomes a code release.
3. One global rule (all adult-only, or all open) — rejected: open everywhere contradicts the parental-permission rules found; adult-only everywhere contradicts the owner's "no age question where permitted".

## Notices (D6)

`contracts/territory-notices.json` holds one row per active territory: notice version, required privacy sections (controller identity and contact; purposes and legal bases; recipients and cross-border transfers to Render/Neon/Cloudflare; retention; rights and how to exercise them; grievance/DPO contact; children statement matching the account mode), I draft each row's text from the regulator sources; production refuses to start with an active territory that has no row (no sign-off gate, per owner direction).

## Publication scope

`contracts/publication-policy.json` active whitelist becomes IN, US, GB, BR, SG, MY, ID, PH, TH; the other 38 regions move to a recorded "deferred" list (not out-of-scope). `docs/BOOK_PUBLICATION_POLICY.md` records the owner amendment. The Selfish Giant (Oscar Wilde, d. 1900, pub. 1888) and Bicharak (Rabindranath Tagore, d. 1941, pub. 1890s) are public domain in all nine under life+70/life+60/life+50 and the US pre-1931 rule; per-territory evidence is still recorded before publishing.

## Legacy URLs (D4, brainstormed)

Approaches: (a) 301 static pages and **410 Gone** for unpublished book slugs, explicit redirect once a title is republished; (b) redirect everything to Home (search engines treat it as a soft 404 and users lose context); (c) redirect books to Explore (soft 404 for 96 titles). **Chosen (a)**, per LLD §4. `/book/the-selfish-giant` and `/reader/the-selfish-giant` redirect 301 to the new Maison title once published; Bicharak had no legacy slug.

## Non-goals

No identity or age-verification vendor, no date-of-birth collection, no new spend, no change to reading authorization, no Vietnam/Timor-Leste.
