# Owner tasks

Things only the owner can do. Claude keeps this list current; tick an item by telling Claude it is done.
Last updated: 27 Nov 2026.

## Approvals
- [x] **Monday review page** (27 Nov, 18:54Z): you approved the ক্ষুধিত পাষাণ correction and its cover. It is live (revision 335dd363, published 19:33Z); readers' places and notes moved with it. New titles will appear on https://theearnalism.com/en/staff/review/ as they are packaged.
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
- [ ] **Google Play Books partner account** (checked 28 Nov): Reo Enterprise account active (ID 279083731878610190), catalog 0 books. Before the first store export, fill in the payment profile, bank account and tax information yourself; Google runs a preliminary policy review when a book is ready to publish.
- [ ] **Finance and tax profile for schools** (real institution invoices).
- [x] **Apple Podcasts / Spotify for Creators accounts** (checked 28 Nov): Apple Podcasts Connect works for "Earnalism by Reo Enterprise", with no shows and no pending agreement ("Add a Legal Entity" left untouched). Spotify for Creators is signed in, with no shows yet. Nothing is created until the first preview episode exists; Claude will then give the submission steps.

## Decisions
- [x] **Colours and icons approved** (28 Nov IST): the gold fill #D8B25E and the new site icon and share card are live (#78).
- [x] **Site quality decisions (26 Nov 2026):** cache public covers and serve small sizes; darken gold text only (before/after screenshots first); longer free preview (first chapter, up to ~1,500 words); one Back link in the reader.
- [x] **বিচারক voice, music and film** (28 Nov IST): "Voice approved" (covers the 07:31 line), "Music approved" for বিচারক and ক্ষুধিত পাষাণ, "Film approved" for the বিচারক review film; "Preview approved" for its 1:53 public preview clip. The 12 other narrations are done on Modal (28 Nov).
- [x] **Possibly clipped narration lines** (28 Nov IST): "Redo" for all four lines in the listening set (দিদি f01s006-005 and f01s023-003, মধ্যবর্তিনী f01s015-002, মানভঞ্জন f01s022-001). Four more lines (নিশীথে f01s019-011 and f01s024-002, অতিথি f01s034-001, মেঘ ও রৌদ্র f01s042-003) were plainly cut off (under 0.5 s) and are redone without a listening check. Claude re-voices these 8 lines alone on Modal; any redone take that is still flagged comes back to you.
- [x] **Narration voices** (28 Nov IST): owner asked for 2 male + 2 female voices chosen per story, a second voice for dialogue, and narration with natural pauses, clarity and emotion themed to each story. Decisions: বিচারক keeps its approved Arnav-only audio; all 13 other stories are recast; characters never share the narrator's voice; voices picked from a six-voice audition (audition-15a5c974, $0.11): **male Arnav (main) and Arjun, female Aditi (main) and Riya** ("I would like to go with your suggestion"). Claude annotated every story (narrator gender, speaker of each spoken line, story tone, scene moods, line emotions). Next: a short style sample for the owner to hear before the full re-voicing (about $8–12 on Modal, within the caps); each recast story then comes back for approval.
- [x] **বিচারক public preview** (28 Nov IST): "Preview approved" is recorded against the exact 1:53 clip (sha256 979938aa…). The site had no step to attach it (the preview page returned 404); PR #81 adds `stage-preview`; after deploy Claude stages it, runs the browser check and publishes.
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
