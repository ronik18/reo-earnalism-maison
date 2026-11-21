# Source-bound social delivery

This module adds provider protocol steps to the common Earnalism production handoff. It does not run a queue, discover credentials, create accounts, render media or publish on import. The current work is private: only local and mocked HTTP tests have run. Account permissions, real upload/processing, saved privacy, playback and publication remain unqualified.

`prepare(manifest, asset_root)` uses `operations.production_bundle.verify_bundle`, checks the selected local MP4 and measures video geometry with local-only ffprobe. It returns the candidate SHA, explicit destination/account/copy, measured aspect and companion-asset delivery requirements. The verifier confirms bytes and references; it does not grant rights, listening acceptance or owner approval.

```python
from operations.social_delivery import prepare
plan = prepare(manifest, asset_root)  # No provider requests or credential access.
```

The integrating caller constructs `Delivery(plan, journal, token_for, authorize)` using the root `OperationJournal`, an in-memory token callback, and an independent authorization callback. Meta destinations additionally require the operator's explicit `graph_version`; there is no guessed default. YouTube/X require no unrelated Meta setting. `run(destination_key, action)` is prepare-only by default. An executing step requires `execute=True`, a separate `Authority` bound to this candidate SHA, destination, account and action, and `authorize(...) is True`. An Authority object/reference is not proof that consent occurred. Root's current private CLI exposes no public publication action.

All executing steps recheck bundle bytes and destination bindings, then confirm provider account identity. All writes fsync an intent through the shared journal before dispatch. Acknowledged operations reuse their recorded result; uncertain writes are held for reconciliation and are never retried automatically. Status queries do not clear uncertainty or manufacture success. Ready means provider processing only, never audiovisual acceptance.

| Destination | Explicit protocol actions | Private behavior and outstanding constraints |
| --- | --- | --- |
| YouTube channel | `start`, `upload`, `reconcile_upload`, `resume_upload`, `captions`, `status`, `thumbnail` | Resumable video upload explicitly sets private. Audience choice is required. Caption upload/readback and native custom thumbnail are implemented. Thumbnail waits for completed processing, including Shorts; current API allows JPEG/PNG up to 50 MB. |
| Instagram professional account | `start`, `upload`, `status` | Binary resumable Reel container, using Facebook Login for Business and an existing Page access token. The token's `/me` Page must link to the requested Instagram account; a readable unrelated account node is insufficient. No feed post is created. Explicit `cover_timestamp_ms` maps to a frame within the measured video; no public image URL is exposed. Containers expire; staging is not a permanent private review player. |
| Facebook Page | `start`, `upload`, `status`, `stage_draft` | Page Reels only; exact 9:16, at least 540×960, 3–90 seconds checked. Finish uses DRAFT. Page publication has public scope. Long landscape Page videos use a separate, unimplemented route. |
| X account | `start`, `upload`, `finalize`, `status` | Current v2 dedicated initialize/append/finalize endpoints with 4 MiB multipart chunks. Stages media only; no Post is created. Existing account/API entitlements and media expiry still apply; successful media upload does not establish permission to attach it to a Post. |

`publish` exists for future integration only. A private candidate always rejects it before any provider request. For a future nonprivate candidate it additionally requires independent exact-action authorization and provider processing evidence. The result is an acknowledgement requiring readback, never a GO LIVE verdict. Instagram/X have no private feed-post step in this workflow. Facebook's final DRAFT acknowledgement still needs provider readback before claiming a saved private draft.

Caption sidecars for Instagram/Facebook/X and separate cover-image uploads for those destinations are not implemented by this adapter. This is an implementation boundary, not a claim that every provider lacks those APIs. Prepare reports burned-caption/cover handoffs as pending and unverified. Future publication rejects supplied but undelivered sidecars or cover assets. An Instagram frame selection does not pretend to deliver a separately supplied cover image. No source WAV, soundtrack, selected visual style or master is modified.

The standard-library HTTPS client is production code with fixed API origins, TLS, bounded replies and file streaming. It does not follow redirects, retry, log tokens or persist upload URLs. YouTube and Facebook resumable capabilities live only in the running object. In-process YouTube recovery needs an explicit status query and separately authorized resume action. If that capability is lost on restart, a cached session-start receipt cannot recreate it: hold and reconcile; do not start a duplicate upload. Provider IDs and safe status fields are the only journal results.

Every completed YouTube upload, resumed upload or completed-upload reconciliation also retains one source-bound `completed-upload` receipt containing only the video ID and completion flag. Fresh processes can use that ID for status and skip known completed transfers, including dynamic resume offsets. Processing readiness and upload URLs are never reconstructed from this receipt.

Run the finite offline suite from the repository root:

```sh
python3 -m unittest operations.social_delivery.test_bridge -v
```

Official protocol references checked 2026-11-21:

- [YouTube video insert](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert), [resumable upload](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol), [caption insert](https://developers.google.com/youtube/data/reference/rest/v3/captions/insert), [thumbnail set](https://developers.google.com/youtube/data/reference/rest/v3/thumbnails/set), [video update](https://developers.google.com/youtube/data/reference/rest/v3/videos/update).
- [Instagram content publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing), [Reel container and thumb_offset](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media).
- [Instagram Facebook Login Page/account linkage](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/get-started). This narrow Page-token route does not silently accept Unified Login/system-user credentials.
- [Facebook Page Reels publishing and draft state](https://developers.facebook.com/documentation/video-api/guides/reels-publishing).
- [X v2 chunked upload](https://docs.x.com/x-api/media/quickstart/media-upload-chunked), [Post creation](https://docs.x.com/x-api/posts/create-post).

These links define protocols, not evidence that Earnalism's live accounts or this candidate have passed them.

