# Owner tasks

Things only the owner can do. Claude keeps this list current; tick an item by telling Claude it is done.
Last updated: 27 Nov 2026.

## Approvals
- [ ] **Monday review page:** https://theearnalism.com/en/staff/review/ (sign in as account #4). **Pending: the ক্ষুধিত পাষাণ correction.** You told Codex "Approve these two insertions" ("না" in paragraphs 6 and 37), but the staff page needed sign-in, so nothing is recorded yet. Sign in and press Approve on that item yourself; Claude then publishes the corrected revision, and readers' places, notes and bookmarks move with it. The cover provenance row was left untouched on purpose.
- [ ] **Check the new titles while signed in** (optional): open a few of the 13 titles from Explore and try the "Side by side" toggle on ক্ষুধিত পাষাণ. Every title passed the browser check before publishing; anonymous visitors see the free preview and are asked to sign in for the rest.
- Standing instruction (25 Nov): publish every title that is ready (clearance and cover approved, browser acceptance passed, deployed). Each title you approve on the Monday page follows.

## Assets
- [x] **ক্ষুধিত পাষাণ scan check** (27 Nov 2026): the 1895 print has "করিবেন না" (p. ১৭৬) and "জানি না" (p. ১৮২). Claude is preparing the corrected text; it will appear on the Monday page for your approval. The English edition already reads both correctly.
- Covers already in your Cloudinary for later titles (no action needed): কাবুলিওয়ালা, পোস্টমাস্টার, ছুটি.
- [ ] **কাবুলিওয়ালা early scan:** 27 Nov 23:50 IST: Codex's automated browser on an Indian network (ipinfo IN) timed out after 10 s, which is its own limit; the site was not shown to be down. Open https://icvtesting.nvli.in/rarebooks/galapagaucacha-1ma-khanada yourself in an ordinary browser tab and give it a minute. If that address is dead, search https://nvli.in for "কাবুলিওয়ালা" or "গল্পগুচ্ছ ১ম খণ্ড". If page images or a PDF open, save them to Drive at Earnalism/scans/kabuliwala-nvli.

## Held stories
- [ ] **Five held stories (সুভা, স্ত্রীর পত্র, হৈমন্তী, একরাত্রি, খাতা; also পোস্টমাস্টার, কাবুলিওয়ালা, ছুটি re-checked):** 27 Nov: keep them held and keep the eligibility rule. Next: validate the সুভা 1894 scan (pp. 61–72), and transcribe the 1914 সবুজ পত্র pages separately; whether a magazine issue counts as an eligible printing is still your decision.

## Production runs
- [x] **Colab jobs replaced by Modal (26 Nov 2026):** Claude runs every narration/stills/music job on Modal through GitHub Actions within the $30/month and $6/title caps; no Colab runs are needed from you. বিচারক narration is done (r4); the other 13 narrations wait only for your voice approval.

## Accounts and keys
- [x] **Gmail SMTP app password rotated** (27 Nov 2026): new `earnalism-smtp-2026-11` in Render (deploy `dep-dc4gof6i0phs73a6bgag`), old one revoked; Render job `job-dc4hje49v7es73f0ntng` logged in to SMTP successfully (no email sent).
- [x] **Modal account, token and GitHub secrets** (26 Nov 2026).
- [x] **Modal payment method** added, workspace spend limit $30/month (26 Nov 2026).
- [x] **Hugging Face read token** added as GitHub secret `HF_TOKEN` (26 Nov 2026).
- [x] **YouTube Studio sign-in** for channel UCw-UnAXdRzqij8_B2TlgQjQ (owner confirmed 26 Nov 2026).
- [ ] **YouTube upload token, at the first private upload only:** once a finished film exists (after the বিচারক Colab jobs), Claude asks through the secure credential form for a short-lived OAuth access token for `www.googleapis.com` (scope `youtube.upload`, from Google's OAuth Playground signed in to this channel). The token is never pasted in chat or stored in the repo. The bridge checks it belongs to this channel before uploading, and uploads stay private.
- [x] **Razorpay test keys and webhook** (27 Nov 2026): test key, key secret and webhook secret in Render; webhook `payment.captured` + `order.paid` → /api/v1/webhooks/razorpay; Render job `job-dc4hje6q1p3s73e2mnng` authenticated against the Razorpay test API.
- [ ] **Turn purchases on** (later decision; 27 Nov: not now): checkout is disabled by design while free access is on, so Razorpay stays switched off until you end free access (G0.5 threshold). Then Claude sets `RAZORPAY_MODE=test`, the merchant configuration version and `RAZORPAY_ENABLED=true` and runs a sandbox payment; live mode needs merchant approval and your live sign-off.
- [ ] **Google Play Books partner account:** the existing Reo Enterprise account is active (account ID 279083731878610190, 27 Nov). Its next requirements are a payment profile, bank account and tax information, which you fill in yourself before the first store export (Claude prepares the export bundle for the 9 regions).
- [ ] **Finance and tax profile for schools** (real institution invoices).
- [ ] **Apple Podcasts / Spotify for Creators accounts:** sign in at https://podcastsconnect.apple.com/ and https://creators.spotify.com/ when convenient, to check whether accounts or shows exist (not verified on 27 Nov). Nothing is created until the first preview episode exists.

## Decisions
- [x] **Site quality decisions (26 Nov 2026):** cache public covers and serve small sizes; darken gold text only (before/after screenshots first); longer free preview (first chapter, up to ~1,500 words); one Back link in the reader.
- [ ] **Listen to বিচারক narration** (sent 26 Nov; 20.7 min). At 07:31 (unit f01s007-007), check that every word of this line is spoken: "সে জানিত না এই জগৎযন্ত্রটার কলকারখানা অত্যন্ত জটিল এবং লৌহকঠিন,— সুখে দুঃখে সম্পদে বিপদে, সংশয়ে সঙ্কটে ও নৈরাশ্যে পরিতাপে বিমিশ্রিত।" It runs about 1.7 times faster than the rest, so words may be missing. The film assembly waits for your answer. Say "Voice approved" (the line is complete), "Approved, but redo 07:31", or what to change. The other 13 narrations run only after this.
- [ ] **Import further approved titles as unpublished drafts** (nothing visible to readers) for their narration jobs: say so per title after you approve it on the Monday page.
- [x] **Founding member trigger for US/UK accounts** (27 Nov 2026): **10** paying Indian Pass members starts the US/UK accounts design (Phase 9, T15). Purchases are still off while free access is on.
- [x] **Standing permission start date** (27 Nov 2026): `MAISON_REVIEW_STANDING_FROM=2027-11-30T00:00:00+05:30`, set on Render; it takes effect at the next deploy. Until then every title needs your Monday approval.
- [x] **Side-by-side column width** (27 Nov 2026): widen the desktop side-by-side reader to about 1,040 px (about 450 px per column); mobile and single-language reading unchanged. Ships with the next release.
- [ ] **Classroom pilot teachers 2 and 3:** still on hold until teacher 1's feedback is reviewed (27 Nov).

## Done
- [x] Approved Phases 5–9 design, plan, merge and deploy (25 Nov 2026).
- [x] Approved ক্ষুধিত পাষাণ clearance and cover.
- [x] Import ক্ষুধিত পাষাণ as an unpublished draft (25 Nov 2026).
- [x] ক্ষুধিত পাষাণ published (25 Nov 2026).
- [x] Missing covers designed by Claude in the series style (প্রায়শ্চিত্ত, আপদ, ঠাকুর্দ্দা, প্রতিহিংসা), 25 Nov 2026.
- [x] D11 footnote style in the reader for মেঘ ও রৌদ্র (25 Nov 2026).
- [x] Monday-page approval of the 12 pipeline titles (clearance and cover) and The Hungry Stone (clearance, cover, AI-translation label), 26 Nov 2026; all 13 published the same day.
- [x] D8 Monday-page approval unlocks publishing; D9 two-click cancel; D10 public podcast previews.
