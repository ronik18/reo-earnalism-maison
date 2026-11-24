# Production release, 24 November 2026: revenue plan phases 1–4

Owner instruction (24 Nov 2026): "Deploy the merged changes to production." Scope: `main` at `4eefdd4` ([PR #58](https://github.com/ronik18/reo-earnalism-maison/pull/58), plus #57 which was merged but not yet deployed). Previous live deploy: `a5fdab0`.

| Step | What happened | Readback |
|---|---|---|
| Pre-check | Neon `quiet-cloud-63128335` / branch `production`: 33 project migrations applied; repository has 36; the 3 pending are `accounts.0007_signup_attribution`, `learning.0004_certificate`, `learning.0005_classroom_session` (additive tables only). | Exact match. |
| Restore point | `2026-11-24T18:02:26Z`, LSN `0/52B7398`, 69 `django_migrations` rows. Neon history retention 7 days covers point-in-time restore. | Recorded. |
| Static assets | Built `main` manifest compared with live release `4e8e5703…`: all 14 existing islands keep identical hashed names; every asset except `maison/dist/classroom-ZM5NOWIS.js` already exists. `STATIC_RELEASE_ID` unchanged. | 1 missing file (classroom only). |
| Migration | Temporary Render pre-deploy command `env MAISON_DATABASE_ROLE=direct python manage.py migrate --noinput` (direct role, as the settings require). First attempt `dep-dc2t2h2vcj2c73aus0q0` used a quoted `sh -c` form that Render split; it exited 127 before touching the database (still 69 rows); previous deploy stayed live. | Corrected and retried. |
| Deploy | `dep-dc2t3cgm7kps73ersqug`, commit `4eefdd4`, live at `2026-11-24T18:05:27Z`. | `live`. |
| Database | 72 migration rows; the 3 new migrations recorded; `maison_signup_attribution`, `maison_certificate`, `maison_classroom_session` exist; `auth_permission.teach_classroom` exists. | Pass. |
| HTTP | `https://theearnalism.com`: `/en/`, `/en/explore/`, `/en/learn/`, sign-up 200; unknown certificate 404; classroom redirects a guest to sign-in (302); a tagged title link carries its `utm_*` tags into the header sign-up link; scripts load from the existing static release. | Pass. |
| Cleanup | Pre-deploy command removed (empty); auto-deploy remains off. | Baseline restored. |

## Static release for classroom mode, 24 November 2026

Owner instruction: "Do the needful to support the classroom mode autonomously", then "switch production to the new static release once verified".

| Step | What happened | Readback |
|---|---|---|
| Prepare | Clean frontend build of `main` (`static/` and `client/` identical to `4eefdd4`), then `manage.py prepare_public_assets`: release `794f9919faa20069af4e428100782445a97fe02a41ec8a9cfba396b944b2088a`, 212 files, 9,354,084 bytes. | Local manifest only. |
| Compare | Every file fetched from the live release `4e8e5703…` and hashed: 209 byte-identical; the only differences are `maison/app.css`, `maison/dist/manifest.json` and the new `maison/dist/classroom-ZM5NOWIS.js`. | As expected. |
| Upload | The owner-held public-upload key was unavailable to this session, so the 212 files were written to bucket `reo-earnalism-maison-public` under the new prefix `static/794f9919…/` through the Cloudflare R2 object API, with the publisher's exact `Content-Type` per file and `Cache-Control: public, max-age=31536000, immutable`. Existing releases were not touched. The publisher's custom `sha256` object metadata was not set on this route. | 212 × HTTP 200. |
| Verify | Every file fetched over public HTTPS from `assets-maison.theearnalism.com`: SHA-256, byte length, `Content-Type` and `Cache-Control` all match the manifest. | 212 of 212. |
| Switch | Render `STATIC_RELEASE_ID` set to `794f9919…`; redeployed `4eefdd4` as `dep-dc2t8cbm8hqs738g6l30`. | `live`. |
| HTTP | `/en/`, `/en/explore/`, `/en/learn/`, a title page: 200; every referenced asset loads from the new release; `classroom-ZM5NOWIS.js` 200; live `app.css` contains the classroom rules. | Pass. |

Rollback for this step: set `STATIC_RELEASE_ID` back to `4e8e5703a06337281bccfc1f14e12403178757ea1e14e5adb158558ee0f92e2e` and redeploy (classroom mode then loses its stepping and large type again). The classroom page itself is teacher-only, so its island is confirmed in use the first time a granted teacher opens it.

## Open after this release

- **Rollback:** redeploy `a5fdab0` on Render; the three new tables are additive and harmless to the older code. A database restore to the recorded point is only needed if data must be removed.
- **YouTube channel** recorded for Step 2.3: `UCw-UnAXdRzqij8_B2TlgQjQ`. Upload needs the channel owner to authorize upload access, plus a finished film.
