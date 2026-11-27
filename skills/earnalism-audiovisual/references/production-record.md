# Production record

One title root, one record, one writer. `record.json` (schema
`earnalism.audiovisual_record.v1`) is written atomically by `eav.record.Record`.

## Title root layout

```
<root>/record.json          source binding, artifacts (path, sha256, bytes, meta), events
<root>/source.json          the exact Maison export (edition, revision, content_sha256)
<root>/plan.json            scene plan + the voice preset used
<root>/jobs/<job_id>/       inert Colab/Modal bundle: notebook, inputs zip, build-manifest.json
<root>/narration|stills|music/<job_id>/   verified Colab or Modal outputs
<root>/reel_clips/<job_id>/ verified Wan clips + import receipt
<root>/film/film-NN/        narration.wav, timing.json (+provenance), .srt, mix.wav, film-NN.mp4
<root>/reels/reel-N/        script.json, caption.txt, narration.wav, shots.json (planned from the
                            measured narration by --plan-shots), reel-N.mp4
<root>/qc/                  report.json, contact sheets
<root>/maison/              audiovisual-clearance-evidence.draft.json
<root>/../allowance-ledger.json   shared CU ledger (all titles)
```

## What must be in it before release

- **Source**: edition id, revision id, content_sha256, export sha256, rights at export.
- **Voice**: model repo and revision, preset key and the exact description, clause if any.
- **Every generator output**: job id, model and revision (resolved at run time for FLUX and
  ACE-Step), seeds and prompts (inside the inputs zip), output hashes, forecast and actual CU (for a Modal run, the ledger's `modal_spend` rows: usd, seconds, status).
- **Score**: route (VCSL editorial or ACE-Step cues), licence, cue hashes.
- **Measured timing**: `timing.json` with `provenance` = {method `eav.film.narration_track`,
  measured_with `ffprobe`, WAV sha256s, narration job id}; for a chunked narration job the
  id is the group id plus `narration_chunk_job_ids` (every chunk, in order).
- **Chunks**: a chunk's `colab_job` artifact, `job/built` and `cli/job_target` events, `job.json`
  and build manifest carry `chunk: {index, of, group}`.
- **Retouches**: a `still_retouch` artifact (`stills/retouch/<key>-<n>.png`) and a
  `retouch/applied` event per retouch, holding target, key, source path, sha256 and job id, the
  source retouch when chained, regions, method, output sha256 and reason; `retouch/undone`
  retires one. The film artifact's `stills_by_key` names each retouched key's retouch.
- **Renditions**: film and reel hashes, durations, loudness, true peak, loop score.
- **Review**: QC report, owner review result, everything not reviewed marked `unassessed`.
- **Licences**: Apache-2.0 (Parler, FLUX.1-schnell, Wan, ACE-Step), CC0 (VCSL).

Job endings are events too: `import/accepted`, `job/superseded` (never ran, 0 CU),
`job/closed` (ran, not imported, actual CU; for a job that ran on Modal its Colab CU and its Modal `usd`) and their pending forms `job/superseding`,
`job/closing` while one is under way. A rebuilt chunk (`--replace-chunk`) is a new job
`<chunk id>-r<k>` with its own `job/built` event; the closed chunk stays in the record. Reel planning adds `reel/scripted`,
`reel/narration_misfit` and `reel/shots_planned`.

## Correcting a published text

An owner-approved correction of the edition's text is a new revision of the same edition, so it
stays on this root (one record per edition; `init` refuses a second one):
`rebase-source <corrected export.json> --root <dir> --reason "<owner approval>"`.

- It validates the export as `init` does and refuses (start a new root instead) a different
  edition, language, unit count or paragraph count per unit, or a paragraph that changed kind.
  It also refuses while film narration built from the old text ran on Modal without being
  imported (import or `close` it first), and a correction that changes the sentence count of a
  paragraph split across scenes.
- `source.json` becomes the new export; the old one stays as `source-<old revision id>.json`
  (artifact `source_previous`). The record's source fields take the new revision, content sha,
  state, rights and export sha.
- `plan.json`: every anchor and unit id is mapped by position (unit, paragraph); block, scene
  and voice text is refreshed from the new source. Scene ids, structure, keyframes and flags
  stay, so still keys, imported stills, retouches and music stay valid.
- `rebases/<old revision>-to-<new revision>.json` (artifact `source_rebase`) and the
  `rebase_source/ok` event hold the old and new revision ids and content shas, the changed
  paragraphs (ordinal, unit, position, old and new anchor and text), the full anchor mapping by
  unit and paragraph position, the scenes and voice units whose text changed, and the narration
  jobs superseded or made stale.
- Film narration built before a text-changing rebase is stale: a never-run job is superseded
  (`source rebased to <new revision>`, 0 CU), an imported one is never current again (`film`,
  `bundle-audio` and `preview` refuse it; `status` marks it STALE), and a stale chunk group is
  never `--replace-chunk`ed. Reel narration speaks the reel script and is unaffected.
- `status` and `Next:` then point to `job narration`, built as usual from the refreshed plan.

Events are append-only. Failed and held attempts stay in the record; never delete or
rewrite them to make the history look clean.
