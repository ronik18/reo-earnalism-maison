# Campaign links and the acquisition funnel

Every link Earnalism posts outside the site (YouTube descriptions, Reels, posts, newsletters, school handouts) points at a **title page** and carries three tags. When a visitor signs up after arriving through such a link, the account records where they came from. No cookie or tracker is involved: the tags travel inside the existing `return_to` link through sign-in and sign-up.

## Link format

```
https://<site>/en/titles/<edition-slug>/?utm_source=<source>&utm_campaign=<title-slug>&utm_content=<asset>
```

| Tag | Allowed values | Example |
|---|---|---|
| `utm_source` | `youtube`, `instagram`, `facebook`, `x`, `whatsapp`, `newsletter`, `google_play`, `podcast`, `school`, `partner` (anything else is stored as `other`) | `youtube` |
| `utm_campaign` | lowercase letters, digits and hyphens, up to 64 characters; use the title slug | `selfish-giant` |
| `utm_content` | same rules; name the asset | `film`, `reel-1`, `quote-card` |

Values that break these rules are dropped, never stored. Do not put names, emails or other personal details in a link.

The podcast feed (`/podcast/en.xml`, `/podcast/bn.xml`) lists each cleared, free-audio edition with a title-page link tagged `utm_source=podcast&utm_medium=feed&utm_campaign=<edition-slug>`. Region limits on each podcast platform are set by hand in that platform; a platform that cannot limit listings to the 9 regions is not used.

**Limitation:** The feed has no audio enclosures because full narration is members-only. Apple Podcasts, Spotify and most directories require an audio enclosure per episode, so the feed will likely be rejected or show no episodes until the owner approves public audio (e.g. a cleared CDN-hosted preview or full episode).

## Reading the funnel

```bash
python manage.py funnel_report --weeks 8 --by-campaign
```

It prints signup cohorts by week and source (and campaign), counted through: signed up → verified → started reading → completed a story → Pass started. Members without a tagged link show as `direct`. Any count below 5 prints as `<5`, so the report never singles anyone out. `--json` gives the same data as JSON.

## Privacy handling

- The record holds only source, campaign, content, landing path and time.
- It appears in the member's data export and is removed when the account is deleted.
- Abandoned unverified signups are still cleaned after 7 days.
- Guardian-managed (younger reader) accounts get no attribution record.
