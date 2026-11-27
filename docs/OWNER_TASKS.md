# Owner tasks

Things only the owner can do. Claude keeps this list current; tick an item by telling Claude it is done.
Last updated: 26 Nov 2026.

## Approvals
- [ ] **Monday review page:** https://theearnalism.com/en/staff/review/ (signed in as account #4). Nothing is pending there now; new titles appear as they are packaged. One item was left untouched on purpose: the ক্ষুধিত পাষাণ cover provenance row (that title is already live).
- [ ] **Check the new titles while signed in** (optional): open a few of the 13 titles from Explore and try the "Side by side" toggle on ক্ষুধিত পাষাণ. Every title passed the browser check before publishing; anonymous visitors see the free preview and are asked to sign in for the rest.
- Standing instruction (25 Nov): publish every title that is ready (clearance and cover approved, browser acceptance passed, deployed). Each title you approve on the Monday page follows.

## Assets
- [ ] **Check two clauses in ক্ষুধিত পাষাণ against the 1895 scan** (published text follows the proofread transcription): open https://bn.wikisource.org/wiki/পাতা:গল্প-দশক_-_রবীন্দ্রনাথ_ঠাকুর.pdf/১৭৬ and see whether the printed line reads “…কখনো এখানে রাত্রিযাপন করিবেন।” or “…করিবেন না।” (later printings have “না”). A second likely case is “জানি” (probably “জানি না”) later in the story. If the scan has “না”, tell Claude: the transcription gets corrected and a revised edition goes to the Monday page.
- Covers already in your Cloudinary for later titles (no action needed): কাবুলিওয়ালা, পোস্টমাস্টার, ছুটি.
- [ ] **কাবুলিওয়ালা early scan:** open https://icvtesting.nvli.in/rarebooks/galapagaucacha-1ma-khanada from India; if a PDF/page images appear, put the file in Google Drive and share the path.

## Held stories
- [ ] **Five held stories (সুভা, স্ত্রীর পত্র, হৈমন্তী, একরাত্রি, খাতা; also পোস্টমাস্টার, কাবুলিওয়ালা, ছুটি re-checked):** the early-edition survey (`docs/evidence/early-edition-survey-20261125.json`) found no eligible printing. Pick a route: (1) validate the সুভা 1894 scan pp. 61–72 on Wikisource; (2) transcribe the 1914 সবুজ পত্র pages for স্ত্রীর পত্র and হৈমন্তী and decide whether a magazine issue counts as an eligible printing; (3) change the rule.

## Production runs
- [x] **Colab jobs replaced by Modal (26 Nov 2026):** Claude runs every narration/stills/music job on Modal through GitHub Actions within the $30/month and $6/title caps; no Colab runs are needed from you. বিচারক narration is done (r4); the other 13 narrations wait only for your voice approval.

## Accounts and keys
- [ ] **Rotate the Gmail SMTP app password** (`EMAIL_HOST_PASSWORD` on Render): on 26 Nov Claude's settings check printed it into the session log by mistake (nowhere else). Create a new app password for sales@ in Google Account → Security → App passwords, put it in Render, then revoke the old one.
- [x] **Modal account, token and GitHub secrets** (26 Nov 2026).
- [x] **Modal payment method** added, workspace spend limit $30/month (26 Nov 2026).
- [x] **Hugging Face read token** added as GitHub secret `HF_TOKEN` (26 Nov 2026).
- [x] **YouTube Studio sign-in** for channel UCw-UnAXdRzqij8_B2TlgQjQ (owner confirmed 26 Nov 2026).
- [ ] **YouTube upload token, at the first private upload only:** once a finished film exists (after the বিচারক Colab jobs), Claude asks through the secure credential form for a short-lived OAuth access token for `www.googleapis.com` (scope `youtube.upload`, from Google's OAuth Playground signed in to this channel). The token is never pasted in chat or stored in the repo. The bridge checks it belongs to this channel before uploading, and uploads stay private.
- [ ] **Razorpay test keys**, then live sign-off and merchant approval (founding Pass).
- [ ] **Google Play Books partner account** (store export).
- [ ] **Finance and tax profile for schools** (real institution invoices).
- [ ] **Apple Podcasts / Spotify for Creators accounts**, once the first preview episode exists (Claude will give the submission steps).

## Decisions
- [x] **Site quality decisions (26 Nov 2026):** cache public covers and serve small sizes; darken gold text only (before/after screenshots first); longer free preview (first chapter, up to ~1,500 words); one Back link in the reader.
- [ ] **Listen to বিচারক narration** (sent 26 Nov; 20.7 min; check 07:31) and say "Voice approved", "Approved, but redo 07:31", or what to change. The other 13 narrations are built and run on Modal only after this.
- [ ] **Import further approved titles as unpublished drafts** (nothing visible to readers) for their narration jobs: say so per title after you approve it on the Monday page.
- [ ] **Founding member trigger for US/UK accounts** (Phase 9): the number of paying Indian Pass members that starts it (proposed 300).
- [ ] **Standing permission start date** (`MAISON_REVIEW_STANDING_FROM`): about two months after the first Monday batch.
- [ ] **Side-by-side column width:** the reading page is capped at ~780px, so each column is ~320px on desktop; widen it (design change) or keep.
- [ ] **Classroom pilot teachers 2 and 3:** on hold by your choice.

## Done
- [x] Approved Phases 5–9 design, plan, merge and deploy (25 Nov 2026).
- [x] Approved ক্ষুধিত পাষাণ clearance and cover.
- [x] Import ক্ষুধিত পাষাণ as an unpublished draft (25 Nov 2026).
- [x] ক্ষুধিত পাষাণ published (25 Nov 2026).
- [x] Missing covers designed by Claude in the series style (প্রায়শ্চিত্ত, আপদ, ঠাকুর্দ্দা, প্রতিহিংসা), 25 Nov 2026.
- [x] D11 footnote style in the reader for মেঘ ও রৌদ্র (25 Nov 2026).
- [x] Monday-page approval of the 12 pipeline titles (clearance and cover) and The Hungry Stone (clearance, cover, AI-translation label), 26 Nov 2026; all 13 published the same day.
- [x] D8 Monday-page approval unlocks publishing; D9 two-click cancel; D10 public podcast previews.
