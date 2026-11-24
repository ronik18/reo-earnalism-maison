# Maison Film Delivery (R2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-in reader in a whitelisted region can watch a title's full film on Maison, with synced subtitles, served from the private R2 bucket through short-lived signed links.

**Architecture:** Video gains a second provider beside the existing, unprovisioned Stream path. A film is a progressive faststart MP4 stored as a `video` asset with `provider='r2'`, plus a WebVTT `video_captions` asset for the same unit. The existing `/media/grants` endpoint returns an entitlement-checked presigned R2 GET (≤120 s). The video page plays it in a native `<video>` element that renews the grant and resumes in place when a link expires. Captions come from a same-origin, no-store endpoint, so the bucket needs no CORS change. Films enter Maison only through an audited operations command, mirroring `attach_audiovisual_audio`.

**Tech Stack:** Django 5 + PostgreSQL (Neon) · boto3 R2 presign (`library/storage.private_url`) · TypeScript/React client built with `client/build.mjs` · ffprobe · the `earnalism-audiovisual` skill CLI (`eav`).

**Spec:** `docs/superpowers/specs/2026-11-23-earnalism-audiovisual-design.md` (owner amendment, 24 November 2026: film hosting) and `contracts/cache-policy.json` policy `private_r2_film`.

## Global Constraints

- Full films are served only from the private R2 bucket via a short-lived signed GET after an entitlement check; never cached (`Cache-Control: private, no-store, max-age=0`); the service worker never intercepts film bytes, grant responses or signed URLs.
- Signed URLs last at most 120 seconds (`library.storage.private_url` enforces 1–120).
- Cloudflare Stream stays unprovisioned. Do not delete the Stream code path; `provider='stream'` keeps working where configured.
- Publication still requires exact-edition clearance for every active region and offered format, including `video` (`contracts/publication-policy.json`, 47-region whitelist). Nothing is published without the owner's instruction.
- Synced subtitles are required: a film is publishable only with a ready `video_captions` asset for its unit.
- Lane ownership (AGENTS.md): `library/` media/commerce; `core/`, `reader/`, `accounts/` backend; `client/`, `web/`, `templates/`, `static/` frontend; `config/`, `operations/`, `contracts/`, `skills/`, docs, root. Send an interface change to its owner before altering their files. Use a distinct `MAISON_TEST_DB_NAME` per concurrent test run; constraint tests run on PostgreSQL.
- No new paid services, no provider mutations, no publication in this build. R2 bucket configuration is unchanged.

## Review Focus

1. A grant expires mid-film and the viewer then seeks: the player must fetch a new grant and resume at the same position, without a hard error. (Task 6 test `renews_expired_film_grant_and_resumes`.)
2. Safari and Chrome request byte ranges: the presigned GET must return 206 for a `Range` request. (Task 2 test `film_grant_range_supported`; R2's own 206 behaviour is already proven by `library/r2_qualification.py` `signed_get_range_exact`.)
3. A film whose duration differs from the unit's audio chapter (the film adds an end card): the film must still appear on the video page. (Task 5 test `r2_film_listed_when_duration_differs_from_unit`.)
4. A viewer outside the whitelist, or without entitlement: the grant and the captions both refuse with the same error codes as audio. (Task 2 and Task 3 tests.)
5. An MP4 whose `moov` atom sits at the end (not faststart) would make the browser download the whole file first: staging must refuse it. (Task 7 test `refuses_non_faststart_mp4`, Task 8 test `stage_refuses_non_faststart`.)

---

### Task 1: Contracts for R2 film delivery (root)

**Files:**
- Modify: `contracts/openapi.yaml` (new path; `MediaGrant` description)
- Modify: `contracts/payload-examples.json` (R2 video grant example)
- Modify: `contracts/api-contracts.md` (video section)
- Test: `client/contracts.test.mjs`, `library/test_search_contract.py` pattern (`library/validation.validate_schema`)

**Interfaces:**
- Produces: `GET /api/v1/content/video-captions/{asset_id}` where `asset_id` is the **video** asset id. 200 `text/vtt; charset=utf-8`, headers `Cache-Control: private, no-store, max-age=0`, `X-Content-Type-Options: nosniff`. Errors: 401 `authentication_required`, 404 `not_found` (no ready captions or no such video), 403 `rights_unavailable`/`entitlement_required` as for media grants, 503 `feature_disabled`.
- Produces: a `MediaGrant` example for video with `transport: "r2_s3_presigned"`, `content_type: "video/mp4"`, `sha256` set, `range_supported: true`, `quality_kbps: null`, `duration_ms` set. The `transport` enum is unchanged.

- [ ] **Step 1:** Add the payload example `video_grant_r2` and assert in `client/contracts.test.mjs` that it validates against `MediaGrant`, and that `paths["/api/v1/content/video-captions/{asset_id}"].get.responses["200"].content["text/vtt"]` exists.
- [ ] **Step 2:** Run `npm test`. Expected: FAIL on the missing path.
- [ ] **Step 3:** Add the path and the description text: "For `video` with `provider` r2, `transport` is `r2_s3_presigned`, the URL is a presigned GET of at most 120 s, and `range_supported` is true."
- [ ] **Step 4:** Run `npm test` and `python manage.py test library.test_search_contract`. Expected: PASS.
- [ ] **Step 5:** Commit `contracts: R2 film grant and captions endpoint`.

### Task 2: Asset kinds, constraints and the film grant (library)

**Files:**
- Modify: `library/models.py` (`Asset.KINDS`, constraints, `clean`)
- Create: `library/migrations/0008_r2_film_assets.py`
- Modify: `library/services.py` (`DELIVERABLE_KINDS`, `FORMAT_ASSETS`, `available_formats`, `_signed_asset`, `media_grant`, `validate_revision` media check)
- Test: `library/test_film_delivery.py` (new)

**Interfaces:**
- Produces: `Asset.KINDS` gains `'video_captions'` (not a deliverable kind, so never granted by URL).
- Produces DB constraints:
  - `maison_r2_video_bounds`: `~Q(kind='video', provider='r2') | Q(unit__isnull=False, content_type='video/mp4', duration_ms__gt=0, bytes__lte=1073741824)`.
  - `maison_video_captions_bounds`: `~Q(kind='video_captions') | Q(provider='r2', unit__isnull=False, content_type='text/vtt', bytes__lte=1048576)`.
- Produces: `library.services.video_formats_present(assets) -> bool`, true when a ready `video` asset exists with provider `'r2'` (where video is enabled for r2) or `'stream'`. `available_formats` uses it for `video` in place of the single `FORMAT_ASSETS['video']` pair.
- Produces: `media_grant` dispatches video by `asset.provider`. `'stream'` calls `stream.grant` unchanged. `'r2'` returns `{grant_id, asset_id, edition_revision_id, transport: 'r2_s3_presigned' | 'local_signed', url, issued_at, expires_at, content_type: 'video/mp4', sha256, range_supported: True, quality_kbps: None, duration_ms}`. It is built from `_asset_grant(user, asset, device_id, territory)`, so authorization (`authorize_revision(..., 'video', ...)`), device validation and the expiry cap are the same as for audio.
- Produces: `_signed_asset` refuses video only when `asset.provider == 'stream'`; `range_supported` is true for `audio_chapter` and `video`.

- [ ] **Step 1: Write the failing tests** in `library/test_film_delivery.py`, on PostgreSQL:
  - `test_r2_video_requires_unit_mp4_duration_and_cap`: saving a `video`/`r2` asset with `content_type='video/quicktime'`, with `duration_ms=None`, with `bytes=1073741825` or without a unit each raises `IntegrityError`.
  - `test_video_captions_bounds`: `text/plain` or `bytes=1048577` raises `IntegrityError`.
  - `test_film_grant_shape`: with `MEDIA_STORAGE_BACKEND='r2'`, `FEATURES={'video':True}` and `storage.private_url` patched, the grant has `transport == 'r2_s3_presigned'`, `content_type == 'video/mp4'`, `range_supported is True`, `quality_kbps is None`, the asset's `sha256` and `duration_ms`, and `expires_at - issued_at <= 120 s`; `private_url` is called with `(asset.storage_key, seconds <= 120, 'video/mp4')`.
  - `test_film_grant_range_supported`: the above field is True (pins Review Focus 2).
  - `test_film_grant_refuses_outside_whitelist_and_without_entitlement`: territory `'AE'` → 403 `rights_unavailable`; a member without entitlement → the same code `media_grant` returns for audio.
  - `test_film_grant_feature_disabled`: `FEATURES={'video':False}` → 503 `feature_disabled`.
  - `test_stream_video_grant_unchanged`: a `provider='stream'` asset still routes to `stream.grant` (patched).
  - `test_video_format_available_for_r2_film`: `available_formats` includes `'video'` for a revision with a ready r2 video and `access_policy['video'] != 'deny'`.
- [ ] **Step 2:** Run `MAISON_TEST_DB_NAME=maison_test_film python manage.py test library.test_film_delivery`. Expected: FAIL.
- [ ] **Step 3:** Implement the model constraints, the migration (Django `AddConstraint` plus the `kind` choices alteration) and the service changes listed under Interfaces.
- [ ] **Step 4:** Add `test_validation_requires_captions_for_r2_film`: `validate_revision` fails its `media` check when an r2 `video` unit has no ready `video_captions` asset, and passes once one is added. Implement it in the integrity loop at `library/services.py` (the `for fmt in formats` block).
- [ ] **Step 5:** Run the new tests plus `library.test_stream library.test_media_providers library.test_free_access`. Expected: PASS.
- [ ] **Step 6:** Commit `library: R2 film assets, captions kind and film grant`.

### Task 3: Captions endpoint (library)

**Files:**
- Modify: `library/views.py`, `library/urls.py`
- Modify: `library/services.py`
- Test: `library/test_film_delivery.py`

**Interfaces:**
- Consumes: Task 2 kinds; Task 1 path and errors.
- Produces: `library.services.video_captions(user, video_asset_id, territory) -> bytes`. It authorizes the video asset's revision for `'video'`/`'read'`, finds the ready `video_captions` asset on the same revision and unit, and returns its verified bytes through `storage.read_verified`.
- Produces: view `video_captions(request, asset_id)` mounted at `content/video-captions/<uuid:asset_id>`.

- [ ] **Step 1:** Write the failing tests:
  - `test_captions_served_no_store`: 200, `Content-Type: text/vtt; charset=utf-8`, the body equals the stored VTT, `Cache-Control: private, no-store, max-age=0`.
  - `test_captions_guest_401`.
  - `test_captions_outside_whitelist_403`.
  - `test_captions_missing_404`.
  - `test_captions_feature_disabled_503`.
- [ ] **Step 2:** Run them. Expected: FAIL (404 route).
- [ ] **Step 3:** Implement the service and view; use the existing `api_response` / `DomainError` conventions for errors.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit `library: same-origin no-store film captions`.

### Task 4: Video provider setting (root)

**Files:**
- Modify: `config/settings.py:324-355`
- Test: `operations/test_settings_video.py` (new; `config/` has no test module)

**Interfaces:**
- Produces: `settings.VIDEO_PROVIDER`, from env `MAISON_VIDEO_PROVIDER`, in `{'r2','stream'}`, default `'r2'`; any other value raises `ImproperlyConfigured`.
- Produces: when `FEATURES['video']` is set, `'stream'` keeps today's Stream checks; `'r2'` requires `MEDIA_STORAGE_BACKEND == 'r2'` unless `LOCAL`, and needs no Stream variables.
- Produces: `library.services.video_formats_present` and `media_grant` refuse a provider that does not match `settings.VIDEO_PROVIDER` (503 `provider_not_configured`).

- [ ] **Step 1:** Write the failing tests. Load settings in a subprocess (`python -c "import django; ..."` with env vars, which is how env-driven settings are tested). Cover:
  - `video_r2_without_stream_vars_ok` (with `MEDIA_STORAGE_BACKEND=r2`);
  - `video_r2_with_local_backend_in_production_refused`;
  - `video_stream_still_requires_stream_profile`;
  - `unknown_video_provider_refused`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS. Also run `python manage.py check`.
- [ ] **Step 5:** Commit `config: video provider r2 by default; Stream only when chosen`.

### Task 5: Video page data (frontend lane, `web/`)

**Files:**
- Modify: `web/views.py:631-676`
- Test: `web/test_video_film.py` (new; follow `web/test_audio_preview.py`)

**Interfaces:**
- Consumes: `settings.VIDEO_PROVIDER` (Task 4); asset kinds (Task 2); captions path (Task 3).
- Produces: each boot chapter is `{"asset_id","unit_id","duration_ms","title","provider","sha256","captions_url"}`:
  - `provider` is `"r2"` or `"stream"`;
  - `sha256` is set for r2 and `null` for Stream;
  - `captions_url` is `/api/v1/content/video-captions/<asset_id>` when ready captions exist, otherwise `null`.
- Produces: `stream_customer_host` only when the provider is `stream`.
- Rule: the row query selects `provider=settings.VIDEO_PROVIDER`. The `duration_ms=F("unit__duration_ms")` equality applies to Stream only; r2 films need only `duration_ms > 0`, because a film carries its own end card.

- [ ] **Step 1:** Write the failing tests:
  - `r2_film_listed_when_duration_differs_from_unit` (Review Focus 3);
  - `boot_chapter_has_provider_sha_and_captions_url`;
  - `no_stream_host_in_boot_for_r2`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `web: video page lists R2 films with captions`.

### Task 6: Native film player (frontend lane, `client/`)

**Files:**
- Modify: `client/media-state.ts`, `client/video.tsx`
- Test: `client/media-state.test.ts`, `client/state.test.ts` (or a new `client/video-film.test.ts` registered in `client/test.mjs`)
- Rebuild: `static/maison/dist/*` via `npm run build`

**Interfaces:**
- Consumes: the Task 5 boot chapter; the `MediaGrant` shape from Task 2.
- Produces: `export interface FilmGrant { asset_id; edition_revision_id; transport; content_type; url; expires_at; sha256; duration_ms; }`.
- Produces: `export function approvedFilmURL(grant: FilmGrant, expected: {asset_id: string; sha256: string; duration_ms: number}, revisionId: string, origin: string, now = Date.now()): string | undefined`, with the same rules as `approvedAudioURL`:
  - `content_type === "video/mp4"`;
  - `transport` is `r2_s3_presigned` over https, or `local_signed` only on localhost and same origin;
  - expiry is in the future and no more than 120 000 ms ahead;
  - `sha256` and `duration_ms` match the expected values;
  - the URL has no username or password.
- Produces: `export function shouldRenewFilm(expiresAt: string, now: number, renewing: boolean): boolean`, true when the grant is expired and no renewal is in flight.
- Behaviour:
  - When `chapter.provider === "r2"`, render `<video controls playsInline preload="metadata" src={url}>` with `<track kind="subtitles" default srcLang={locale} src={captions_url}>` when present. Keep the Stream iframe branch unchanged for `"stream"`.
  - On `error`: if `shouldRenewFilm(...)`, post a fresh `/media/grants`, validate it, set `src` and resume at the same `currentTime`, keeping the play state; otherwise show `media_retry`.
  - Progress saving reuses the current video progress calls.

- [ ] **Step 1:** Write the failing tests:
  - `approvedFilmURL` accepts a valid r2 grant and rejects each case: wrong content type, http, expiry over 120 s, sha mismatch, duration mismatch, `local_signed` on a non-localhost origin.
  - `shouldRenewFilm` cases.
  - `renews_expired_film_grant_and_resumes`: a jsdom or state-level test where the first grant is expired at the time of `error`. The second grant is requested once, `src` changes, and `currentTime` is restored (Review Focus 1).
- [ ] **Step 2:** Run `npm test`. Expected: FAIL.
- [ ] **Step 3:** Implement. Use the copy keys `video_unavailable_title`, `video_unavailable_help` and `media_retry` that already exist. Add no new user-facing strings unless the translations file gains them in both English and Bengali.
- [ ] **Step 4:** Run `npm run check` and `npm run build`. Expected: PASS, and a new `static/maison/dist/video-*.js`.
- [ ] **Step 5:** Commit `client: native R2 film player with captions and grant renewal`.

### Task 7: Film bundle in the skill (root, `skills/earnalism-audiovisual`)

**Files:**
- Create: `skills/earnalism-audiovisual/software/eav/film_bundle.py`
- Modify: `skills/earnalism-audiovisual/software/eav/cli.py` (`bundle-film` subcommand)
- Modify: `skills/earnalism-audiovisual/references/publishing.md` (film steps)
- Mirror: `.agents/skills/earnalism-audiovisual/` (byte-identical; `tests/test_skill_files.py`)
- Test: `skills/earnalism-audiovisual/software/tests/test_film_bundle.py`

**Interfaces:**
- Produces: `srt_to_vtt(text: str) -> str`: a `WEBVTT` header, comma milliseconds become dots, cue order and text are unchanged, and empty input raises `ValueError`.
- Produces: `is_faststart(path: Path) -> bool`: true when the top-level `moov` box precedes `mdat`. Read box headers only; never load the file.
- Produces: `python3 -m eav.cli bundle-film --root <root> --film <film id> --unit-id <uuid> --out <dir>` writes:
  - `<dir>/film.mp4` (copy);
  - `<dir>/film.vtt`;
  - `<dir>/film.json` `{"schema":"earnalism.audiovisual-film-bundle.v1","units":[{"unit_id","mp4":"film.mp4","vtt":"film.vtt","mp4_sha256","vtt_sha256","duration_ms","bytes"}]}`.
- Refusals: it refuses without a passing film `qc` artifact in the record, when the MP4 is not faststart, when it is not a single H.264 video stream plus a single AAC audio stream (ffprobe), or when it is over 1 073 741 824 bytes.

- [ ] **Step 1:** Write the failing tests:
  - `srt_to_vtt_converts_timestamps`;
  - `srt_to_vtt_refuses_empty`;
  - `is_faststart_true_for_faststart` and `refuses_non_faststart_mp4`, using two tiny MP4s made in the test with ffmpeg `-movflags +faststart` and without;
  - `bundle_film_writes_manifest_with_hashes`;
  - `bundle_film_refuses_without_qc`.
- [ ] **Step 2:** Run `python3 -m pytest -q -p no:cacheprovider tests/test_film_bundle.py`. Expected: FAIL.
- [ ] **Step 3:** Implement, then sync the mirror with `cp`.
- [ ] **Step 4:** Run the whole skill suite. Expected: PASS, including `test_mirror_identical`.
- [ ] **Step 5:** Commit `eav: bundle-film for Maison R2 delivery`.

### Task 8: Stage and publish films on Maison (root, `operations/`)

**Files:**
- Create: `operations/management/commands/attach_audiovisual_film.py`
- Test: `operations/test_audiovisual_commands.py` (new `FilmCommandTests` class)

**Interfaces:**
- Consumes: Task 7 bundle; Task 2 kinds; the audio command's helpers.
- Produces: `attach_audiovisual_film stage <slug> --publisher <public_id> --bundle <dir> --evidence <docs/evidence/...json>` and `attach_audiovisual_film publish <slug> --publisher <public_id> --browser-report <json>`.
- Rules:
  - Subclass `attach_audiovisual_audio.Command` and reuse `find_or_clone`, `approve_rights` and `publish`, so audio and film can be staged into the same draft and published together.
  - Evidence must list `"video"` in `formats` and carry `video_sha256` equal to the bundle's `mp4_sha256` values.
  - Each MP4 is stored with `storage.put_private_file` as `kind='video'`, `provider='r2'`, `content_type='video/mp4'`, bound to its unit, with the ffprobe-measured `duration_ms`. Each VTT is stored as `kind='video_captions'`.
  - Set `access_policy['video'] = 'free'`.
  - `publish` refuses unless the browser report names the staged revision and its video play check passed.

- [ ] **Step 1:** Write the failing tests:
  - `stage_creates_r2_video_and_captions_on_draft`;
  - `stage_refuses_non_faststart` (Review Focus 5);
  - `stage_refuses_hash_mismatch`;
  - `stage_refuses_evidence_without_video_format`;
  - `stage_rerun_is_idempotent`;
  - `publish_refuses_without_browser_report`.
- [ ] **Step 2:** Run `MAISON_TEST_DB_NAME=maison_test_filmcmd python manage.py test operations.test_audiovisual_commands`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS, with the existing audio command tests still green.
- [ ] **Step 5:** Commit `operations: attach_audiovisual_film stage/publish`.

### Task 9: Browser acceptance (root, integration)

**Files:**
- Create: `integration_tests/test_film_playback.py` (Django live server plus Playwright, following `test_first_journey.py`)
- Create: `library/fixtures/film/` (tiny synthetic faststart MP4 ≤ 256 KiB and its VTT, original and local-only)

**Interfaces:**
- Consumes: everything above, with the local storage backend (`transport: local_signed`).

- [ ] **Step 1:** Write `test_film_plays_with_captions_and_survives_grant_expiry`:
  - a verified member opens the video page and the film plays (`currentTime` advances);
  - the captions track has at least one active cue;
  - after the test forces grant expiry (patch `GRANT_SECONDS` short) and seeks, playback resumes at the sought time;
  - no response for the film or its captions is cached by the service worker.
- [ ] **Step 2:** Run it. Expected: PASS against Tasks 1–8.
- [ ] **Step 3:** Record evidence `docs/evidence/film-delivery-<date>/browser.json` (no signed URLs). Commit `integration: film playback acceptance`.

---

**Not in this plan (needs the owner):** enabling `MAISON_VIDEO=1` (with `MAISON_VIDEO_PROVIDER=r2`) in production, staging a real film, and publishing it. Each waits for the owner's instruction naming the title.
