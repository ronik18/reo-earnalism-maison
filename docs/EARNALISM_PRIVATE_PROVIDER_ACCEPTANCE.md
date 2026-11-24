# Private provider acceptance preparation

Use the same production notebook and common private-delivery CLI. This preparation
does not allocate a runtime, authenticate, inspect credentials, upload, generate,
encode, purchase or publish. It verifies retained bytes and local container
metadata and names the exact missing evidence. **Execution remains disabled.**

```sh
python -m operations.production_delivery provider-acceptance \
  --bundle /private/candidate/production-bundle.json \
  --assets /private/candidate
```

The pure `operations.provider_acceptance.prepare_acceptance(manifest, asset_root,
observations=None)` function has no execute path. The common CLI must reject an
executing acceptance request rather than forward it to private staging. Staging is
a separate, explicitly authorized operation. The saved notebook defaults stay
disabled; preparation does not manufacture an upload authority.

## Retained packet prepared on 21 November 2026

This preparation reuses one byte-unchanged motion trial for **transport-only** preparation:

| Property | Retained value |
| --- | --- |
| Source | `open-window-owner-revision-20261114-v1/drive-colab-runtime-v1/execution-v1/motion-import-v1/outputs/framton-torso-fear-v2.mp4` |
| SHA256 | `9cc3f6a696a18fc29c7a55156c11f9648db28c39707fa6b58916db9c03802ad5` |
| Bytes | 1,876,037 |
| Measured container | MP4, H264, 1280×704, 5.041667 seconds; rounded duration 5042ms |
| Audio streams | Zero; no narration or soundtrack is present |
| Original manuscript | 7,078 bytes; SHA256 `f43d04cc2097668e91190ada89e283ad4908c360c4d7f6011a44b8f83d9659be` |
| Original provenance | Retained motion job, export manifest and import receipt; their output/source hashes match |

The private packet contains independent, byte-identical copies of that video,
the manuscript and the three provenance JSON files. Originals were hashed before
and after copying. No transformation or new media generation occurred. The four
source/QA objects total 16,056 bytes for a future positive R2 byte-transfer check.
Those raw files do not certify the separate general-title import source schema.

The prepared candidate hash is
`20babcae0e798d0a5f6e246fb657a98bbae47501f8f7d189213a651669b8431a`.
The preparation-only ZIP contains 1,890,858 bytes with SHA256
`663c05ce6ddc4a7a4ee84635083c61b6213128f812469be0795f056ef1f54db1`.
These are private retained artifacts, not a book release or commercial clearance.
Existing motion/quality and rights holds remain. `en_tisha` in the manifest is
fixed-roster routing metadata only; there is no Tisha recording in this clip.

No account, edition, revision or unit ID was invented. Before a future Maison
operation, use actual identities, current ETag and canonical revision content hash
from the completed general import, with the actual unit binding. Write a new bound
manifest and rerun preparation: changing identity changes its candidate hash even
when all retained media stays byte-identical. The current unbound packet's text
hash identifies the manuscript bytes, not a future revision's structured hash.

## Finite future scope

This is a proposal to make a later explicit execution request concrete. It grants
no spending or provider-write authority and does not treat historical access as
current. Keep the same retained candidate, existing accounts and original assets.

| Provider | Proposed maximum and actual evidence required |
| --- | --- |
| Private R2 | Four exact source/QA objects, 16,056 bytes total. Bound draft intents, create-once uploads, completion, authenticated hash readback and independently established nonpublic storage. No new bucket or account. |
| Private Stream | One UID/source upload, 1,876,037 bytes. Existing permitted draft/unit and managed private TUS intent; signed URLs required before grant, exact offset transfer, completion, private metadata/readiness/duration and actual signed/unsigned/expired playback checks. Source SHA identifies uploaded source, not adaptive rendition bytes. |
| YouTube | One private video, 1,876,037 source bytes. Actual channel identity, access/quota, exact copy and explicit audience selection; one resumable upload, processing/saved-private readback and actual playback. No public transition. |
| X | One media-only upload, 1,876,037 source bytes. Actual account/access/quota, initialize/append/finalize and processing/privacy readback. No Post. Media staging is not permanent private review storage or publication acceptance. |
| Facebook | Held. This 1280×704 source fails the existing Page Reels adapter's portrait geometry rule. No crop, new rendition or transfer is prepared. |
| Instagram | Held for actual account/permission binding and current adapter/provider-format acceptance. The current adapter does not reject landscape solely by aspect; this preparation does not invent a contrary provider requirement or an account to force preflight. |

The retained file fits one current configured upload chunk per Stream, YouTube or
X transfer. There are no automatic retries or processing polls. Missing access,
quota, privacy or unknown-write evidence produces a named hold, not another
session/object. Preserve durable journals and reconcile the exact known operation;
do not reset counters or start another candidate to hide an outcome.

Maison playback additionally needs existing permitted private playback authority.
A general source import deliberately denies every format and creates no Rights
approval, so it cannot authorize that playback. If a qualified private test scope
is absent, a future transport pass must stop at provider/source/privacy metadata
and mark application playback unperformed. Never relax rights or enable an
offered format merely to make a transport check pass.

The five-second video cannot exercise long playback or grant renewal. The earlier
original silent 180-second technical fixture has a historical private application
receipt at `docs/evidence/stream-20261119/qualification.json`, including two grant
renewals. Its original source MP4 was not located in this preparation. Reuse that
receipt only within its actual asset/deployment scope. Old temporary token expiry,
permissions, provider state and fixtures do not qualify the new upload bridge.

## Audio, rights and account observations

One retained Mary tutorial listening derivative was measured as a negative profile
case: SHA256 `697baef0dd889e002a1b3313b796bd5efa79a0ace00255180a3b5713cf7fc411`,
1,050,469 bytes, 82.686259 seconds and reported 101576bps. It does not meet the
existing Maison 48/96kbps distribution profile. It was held, not re-encoded or
selected for positive audio acceptance. Its fidelity, naturalness and expression
are not established by measurement. The final roster remains unchanged.

Optional observations must use
`earnalism.private_provider_observations.v1`, bind the exact candidate SHA and
contain only allowlisted provider/check/result labels, UTC time and a SHA256 of
the private read-only evidence. They never contain credentials, signed URLs or
raw provider payloads. They remain operator-supplied observations; this local
function does not independently verify them or turn them into execution, rights,
performance or publication approval.

Root's eventual read-only preflight should establish actual existing account and
destination identity, currently available access/quota and matching deployed
bridge source. Preserve metadata receipts without secrets. Do not request new
permissions, credentials, products or purchases during preparation. Genuine
account/authentication or broader-access decisions belong to the owner.

Actual quality/listening, complete source and rights for every offered format and
the full active publication whitelist remain separate. A transport test cannot
accept Open Window's soundtrack/style, a voice, a full film or GO LIVE. No customer
publication or physical-device acceptance is implied by fixtures or protocol tests.

## YouTube OAuth setup — 25 November 2026 (read-only verification passed)

- Project: **Earnalism** (`earnalism`, number `620834018736`); YouTube Data API v3 enabled. The original web sign-in client is preserved; a separate Desktop client, **Earnalism private YouTube delivery**, is used.
- Consent remains External/Testing with `sales@reoenterprise.org` as a test user. Exactly `https://www.googleapis.com/auth/youtube.upload` and `https://www.googleapis.com/auth/youtube.force-ssl` were granted. [Google documents](https://developers.google.com/identity/protocols/oauth2) that Testing refresh tokens for these scopes expire after seven days; this setup is not an indefinite production grant.
- Local helper: `/Users/ronikbasak/bin/earnalism-youtube-token.py` (700). Client and refresh credentials: `/Users/ronikbasak/.config/earnalism/youtube-client.json` and `/Users/ronikbasak/.config/earnalism/youtube-refresh.json` (600, parent 700). Downloaded client originals were preserved and secured with mode 600. No credentials are stored in this repository.
- **PASS:** OAuth authorization and a separate refresh-based verification both returned exactly `UCw-UnAXdRzqij8_B2TlgQjQ` using only `GET channels?part=id,snippet&mine=true`. Refresh-based verification timestamp: `2026-11-24T18:42:30.279721+00:00`. Secret-free local receipt: `/Users/ronikbasak/.config/earnalism/youtube-verification.json`. Unexpected scopes/channel are rejected. Local shell capture of helper `--export` supplies `EARNALISM_YOUTUBE_ACCESS_TOKEN`; never log its output. No upload, video mutation, channel-settings change or paid resource was performed.
- Audit: no form submitted in this task; prior status unverified. Review the [YouTube audit form](https://support.google.com/youtube/contact/yt_api_form) before public release. [Current quota documentation](https://developers.google.com/youtube/data/guides/quota_and_compliance_audits) describes 100 daily `videos.insert` calls plus 10,000 units for other endpoints, and says unaudited projects are not automatically private-only. Explicit private upload settings remain necessary; check project-specific quota before execution. This PR does not authorize an upload or public release and must remain unmerged.
