# Owner tasks

Things only the owner can do. Claude keeps this list current; tick an item by telling Claude it is done.
Last updated: 25 Nov 2026.

## Approvals
- [ ] **Monday review page:** open https://theearnalism.com/en/staff/review/ (signed in as staff) and approve each title's clearance **and** its cover:
  - [ ] নিশীথে (clearance + cover)
  - [ ] দিদি (clearance + cover)
  - [ ] মানভঞ্জন (clearance + cover)
  - [ ] অতিথি (clearance + cover)
  - [ ] প্রায়শ্চিত্ত (clearance; cover still needed, see below)
  - [ ] আপদ (clearance; cover still needed)
  - [ ] ঠাকুর্দ্দা (clearance; cover still needed)
  - [ ] প্রতিহিংসা (clearance; cover still needed)
- [ ] **Say which approved titles to publish.** Already publishable now: ক্ষুধিত পাষাণ (unpublished draft in production, clearance recorded; বিচারক is already live).

## Assets
- [ ] **Covers** (upload front/back pairs to Cloudinary, then tell Claude): প্রায়শ্চিত্ত, আপদ, ঠাকুর্দ্দা, প্রতিহিংসা.
- Covers already in your Cloudinary for the next batch (no action needed): মধ্যবর্ত্তিনী, শাস্তি, সমাপ্তি, মেঘ ও রৌদ্র (from *কথা-চতুষ্টয়*), কাবুলিওয়ালা, পোস্টমাস্টার, ছুটি.
- [ ] **কাবুলিওয়ালা early scan:** open https://icvtesting.nvli.in/rarebooks/galapagaucacha-1ma-khanada from India; if a PDF/page images appear, put the file in Google Drive and share the path.

## Production runs
- [ ] **বিচারক Colab jobs** (narration, stills, music): follow `production/audiovisual/bicharak/RUN_SHEET.md`, then tell Claude the job names and compute units used. This unlocks the first film, the first audio, podcast preview episodes and the founding Pass count.
- [ ] **ক্ষুধিত পাষাণ narration Colab job** (`narration-9187e43e`, forecast 4.24 CU): follow `production/audiovisual/kshudhita-pashan/RUN_SHEET.md`; can run alongside বিচারক's.

## Accounts and keys
- [ ] **YouTube upload authorization** for channel UCw-UnAXdRzqij8_B2TlgQjQ (token for `EARNALISM_YOUTUBE_ACCESS_TOKEN`, held only in memory for attended runs).
- [ ] **Razorpay test keys**, then live sign-off and merchant approval (founding Pass).
- [ ] **Google Play Books partner account** (store export).
- [ ] **Finance and tax profile for schools** (real institution invoices).
- [ ] **Apple Podcasts / Spotify for Creators accounts**, once the first preview episode exists (Claude will give the submission steps).

## Decisions
- [ ] **Import further approved titles as unpublished drafts** (nothing visible to readers) for their narration jobs: say so per title after you approve it on the Monday page.
- [ ] **Founding member trigger for US/UK accounts** (Phase 9): the number of paying Indian Pass members that starts it (proposed 300).
- [ ] **Standing permission start date** (`MAISON_REVIEW_STANDING_FROM`): about two months after the first Monday batch.
- [ ] **Classroom pilot teachers 2 and 3:** on hold by your choice.

## Done
- [x] Approved Phases 5–9 design, plan, merge and deploy (25 Nov 2026).
- [x] Approved ক্ষুধিত পাষাণ clearance and cover.
- [x] Import ক্ষুধিত পাষাণ as an unpublished draft (25 Nov 2026).
- [x] D8 Monday-page approval unlocks publishing; D9 two-click cancel; D10 public podcast previews.
