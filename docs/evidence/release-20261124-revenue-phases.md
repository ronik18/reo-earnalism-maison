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

## Open after this release

- **Classroom island and CSS:** `classroom-ZM5NOWIS.js` and the `.reader.classroom` rules need a new static release (`prepare_public_assets`, then `publish_public_assets --execute` with the owner-held public upload key), then `STATIC_RELEASE_ID` set to its tree hash. Until then classroom mode renders the chapter but stepping and large type do not work. No teacher has the role yet, so no user sees this.
- **Rollback:** redeploy `a5fdab0` on Render; the three new tables are additive and harmless to the older code. A database restore to the recorded point is only needed if data must be removed.
- **YouTube channel** recorded for Step 2.3: `UCw-UnAXdRzqij8_B2TlgQjQ`. Upload needs the channel owner to authorize upload access, plus a finished film.
