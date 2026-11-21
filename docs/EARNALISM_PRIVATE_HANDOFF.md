# Earnalism private production handoff

Use [the production notebook](../notebooks/Earnalism_Production_Orchestrator.ipynb)
for the final-five voice plan and the common private-delivery CLI in one place.
It extends the retained final-five notebook; the original nine cells and voice
evidence are preserved. Its embedded ZIP contains verified Python source and a
file manifest, without model weights, media, credentials or installed packages.
Matching source files are reused. Changed files, unknown work, symlinks and loaded
modules from another snapshot are preserved and held for review.

The saved notebook has empty production inputs, all execution flags false, zero
generation calls and publication disabled. **Run All does not authenticate,
install anything, mount Drive, allocate a GPU, load a model or contact a provider.**
Supplying a bundle with staging disabled runs local preparation only. Social video
preparation uses the runtime's existing `ffprobe`; nothing installs it automatically.

The fixed roster is `en_mary`, `en_raghav`, `en_tisha`, `bn_arnav`, `bn_riya`.
These are owner-selected base-model speaker presets. Neither this bridge nor the
notebook creates newly trained weights. The retained sustained narration has ASR
warnings and unassessed accent, naturalness, expression and spoken fidelity.
Profile selection is final; new-recording acceptance remains separate. Do not
describe this source implementation as live-qualified or release-ready.

## Prepare one exact candidate

1. Use the existing source-bound book/voice/score/video workflows to produce and
   retain the candidate. Preserve exact narration, soundtrack, original WAV and
   selected visual style. This handoff does not generate media from a book name.
2. Supply a local `earnalism.production_bundle.v1` JSON manifest and its asset root.
   An already connected private Drive folder may serve as that root; the notebook
   never requests Drive access itself.
3. Set `PRODUCTION_BUNDLE_PATH` and `PRODUCTION_ASSET_ROOT`. Leave
   `ENABLE_PRIVATE_STAGING = False` and run the final dispatch cell. The notebook
   calls the same common CLI used outside Colab:

   ```sh
   python -m operations.production_delivery prepare \
     --bundle /private/candidate/production-bundle.json \
     --assets /private/candidate
   ```

4. Retain its exact candidate SHA and preparation result. An optional
   `PRODUCTION_RECEIPT_PATH` must name a new file; existing receipts are not replaced.

The manifest binds the following information. The root-owned
[`production_bundle.py`](../operations/production_bundle.py) is authoritative for
field names, enums, paths and reference validation.

| Field | Required meaning |
| --- | --- |
| `schema`, `project_id`, `private` | `earnalism.production_bundle.v1`, a stable project ID and `true` for this lane. |
| `content` | Exact revision text SHA, English/Bengali language and one final voice profile. Maison also needs current edition/revision UUIDs and a strong starting ETag. |
| `assets` | Unique contained paths, exact bytes/SHA/MIME and roles. Media binds its unit and measured duration. MP3 audio references its retained `native_audio` WAV by `native_wav`. |
| `evidence` | IDs of QA and rights files; optional measured-map and caption IDs. References do not create approval. |
| `social` | Exact platform/account, video ID, title/copy and applicable caption, thumbnail and audience fields. No credentials, provider URLs or authority grants. |

Full local preparation hashes every declared file. The server separately validates
metadata and verifies only its own staged objects. Native WAVs and source material
that are not uploaded remain provenance references; the API labels that limitation.

## Explicit private staging

Only an authorized operator should set `ENABLE_PRIVATE_STAGING = True`. Choose one
`PRIVATE_DESTINATION` and retain `PRIVATE_JOURNAL_PATH` across runs. Existing access
must already be available in runtime memory. There is no credential discovery,
account creation, subscription purchase or automatic consent flow.

For Maison, the common CLI reads `MAISON_ORIGIN`, `MAISON_SESSION_COOKIE` and
`MAISON_CSRF_TOKEN` only for an executing operation. Use an existing verified staff
session with the normal publisher permission and applicable MFA. Never put these
values in the manifest, notebook source, saved outputs or journal. If entering an
existing credential interactively, use a private password prompt and keep it only
in the current runtime environment.

```sh
python -m operations.production_delivery maison-stage \
  --bundle /private/candidate/production-bundle.json \
  --assets /private/candidate --journal /private/candidate/journal --execute
```

The client checks the private draft identity/ETag, stages supported assets through
the existing upload API and calls the private `production-handoffs` endpoint.
Audio goes to immutable private R2 objects. Video uses the shared managed Stream
TUS client and the server-reserved private UID. Proof/caption files are private
evidence. The server checks owned bytes, actual MP3 metadata, source/map bindings
and canonical paragraph coverage, then uses existing revision receipts and media
verification. It does not create Rights grants, mark a revision ready or publish.

Platform staging is bounded to 100 uploaded assets, at most 64 MiB of staged R2
bytes and a bounded metadata request. Stream video is excluded from the R2 download
budget. Larger works need source-bound unit bundles; they are not silently trimmed.
New-book HTTP import remains the reviewed `EN-071` packet. This bridge targets
existing exact drafts and does not invent a general book-import endpoint.

For social staging, select `SOCIAL_PLATFORM` and the exact `SOCIAL_ACCOUNT_ID`.
`SOCIAL_ACTION = "private-upload"` performs the finite supported sequence in one
common CLI process so temporary upload capabilities stay in memory. The existing
provider token is read only for that selected destination. Instagram/Facebook
also require the operator's explicit `META_GRAPH_API_VERSION`.

```sh
python -m operations.production_delivery social-stage \
  --bundle /private/candidate/production-bundle.json \
  --assets /private/candidate --journal /private/candidate/journal \
  --platform youtube --account EXISTING_CHANNEL_ID \
  --action private-upload --execute
```

YouTube uploads are private. Instagram creates a nonpublic media container; X stages
media without creating a Post. Facebook's supported Reel route finishes as DRAFT;
it is limited to the adapter's measured portrait/duration constraints. Instagram/X
staging may expire and is not a permanent private review player. Supplied sidecars
or separate covers are not silently declared delivered where unsupported. See the
[social adapter guide](../operations/social_delivery/README.md) for exact boundaries.

## Finish with evidence, not automatic retries

Keep the journal and immutable receipts. Known writes reuse their results. A lost
response is not permission to create another upload. `RECONCILE_PRIVATE_ONCE` maps
to the common CLI's explicit `--reconcile`; only the supported same-operation or
offset/status reconciliation may proceed. Preserve a held result if a capability
has expired or been lost. Do not reset counters, delete a journal or start a second
candidate to hide an unknown outcome.

`PROCESSING` means exactly that. Technical upload/processing is not human listening,
rights clearance, audiovisual acceptance or a GO LIVE decision. Live account access,
provider privacy/readback/playback, matching server deployment and exact-candidate
quality remain separately evidenced. The notebook contains **no publication route**;
its common CLI exposes private actions only. Root Integration controls any later
release through the existing publication policy and accepted candidate evidence.

When bridge source changes, reseal the notebook's source snapshot after review and
repeat the offline disabled Run All check. Never replace extracted source in place
or silently reuse imported modules from a different snapshot.

```sh
python -m operations.build_production_notebook
python -m operations.build_production_notebook --check
python -m unittest operations.test_production_notebook -v
```

The maintenance builder reads only the current repository's source allowlist and
the existing checked-in notebook. It preserves the first nine voice cells and all
other notebook logic, changes only the embedded bridge snapshot/checksums, and
refuses to reseal a notebook containing executed outputs. The tests compare the
ZIP with actual canonical source and run the saved defaults in an isolated Python
process with model imports, HTTP, credential prompts and child processes blocked.
