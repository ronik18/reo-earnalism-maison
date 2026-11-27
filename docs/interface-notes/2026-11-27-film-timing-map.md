# Interface note: film timing map in the film bundle (27 Nov 2026)

From: media lane (library/). To: the controller, for routing to the film skill (`skills/earnalism-audiovisual`,
`eav bundle-film`) and to root (`operations/management/commands/attach_audiovisual_film.py`).

Why: spec `2026-11-27-earnalism-cinematic-film-design.md` §10 item 5 (owner-approved 27 Nov): the reader's Watch
switch must open the film at the reader's exact place. `/content/switch-position` now maps reader <-> video and
audio <-> video (library/timing.py), but only for a film that carries a measured film timing map. Today
`eav bundle-film` writes only `film.mp4`, `film.vtt` and `film.json`, so no film has one yet; until a film has a map,
switching returns `unmapped` and the client keeps its part-start fallback.

## 1. What the film bundle must add (skill)

Per unit, one more file, listed in `film.json`. The unit row gains two keys:

```json
{"schema": "earnalism.audiovisual-film-bundle.v1",
 "units": [{"unit_id": "<live unit id>", "mp4": "film.mp4", "vtt": "film.vtt",
            "mp4_sha256": "<hex>", "vtt_sha256": "<hex>", "duration_ms": 1303961, "bytes": 205967288,
            "timing": "film.timing.json", "timing_sha256": "<sha256 of film.timing.json bytes>"}]}
```

`film.timing.json` (UTF-8 JSON, at most 1 048 576 bytes, exactly these keys, nothing else):

```json
{
  "schema": "earnalism.audiovisual-film-timing.v1",
  "unit_id": "<live unit id, the same as film.json>",
  "mp4_sha256": "<film.json mp4_sha256>",
  "text_sha256": "<content_sha256 of the live revision the narration speaks (the exported source)>",
  "measurement_evidence_ref": "<non-blank, <= 500 chars: e.g. 'eav film --shots film-01: scene-timing of voice <sha256...>, title card 4000 ms, scene starts frame-aligned at 24 fps'>",
  "maps": [
    {"precision": "paragraph",
     "segments": [{"anchor_id": "<live paragraph anchor>", "start_offset_chars": 0, "end_offset_chars": <len(text)>,
                   "start_ms": <film ms>, "end_ms": <film ms>}, ...]},
    {"precision": "sentence",
     "segments": [{"anchor_id": "<live anchor>", "sentence_index": 0, "start_offset_chars": 0, "end_offset_chars": 47,
                   "start_ms": <film ms>, "end_ms": <film ms>}, ...]}
  ]
}
```

Rules (the importer refuses the whole film otherwise, before any write):

- Times are milliseconds on the FILM timeline, title card included. For `film --shots` this is
  `round((film.TITLE_S + scene_start + clause_time) * 1000)`, where `scene_start` is the frame-aligned scene start
  (`sum(scene_frames[:k]) / SHOT_FPS`) and `clause_time` comes from the scene's scene-timing clauses: exactly the
  numbers `_film_shots` already feeds to `film.captions(..., offset=film.TITLE_S)`.
- The paragraph map is required: one segment per paragraph of the unit, in paragraph order, `start_offset_chars` 0
  and `end_offset_chars` the paragraph length; `start_ms` is its first clause's start and `end_ms` its last clause's
  end (as `_write_audio_bundle` builds audio `segments`, with the film offset instead of the audiobook offset).
- The sentence map is optional. Per anchor it holds either that paragraph's single paragraph segment (no
  `sentence_index`) or one segment per sentence of `eav.text.sentences` / `library.sentences.split_sentences`,
  `sentence_index` 0..n-1, with exactly those character offsets. Paragraph maps never carry `sentence_index`.
- Both maps follow `library.timing.validated_segments`: segments ordered in time and text, never overlapping,
  `end_ms > start_ms`, every `end_ms` within the ffprobe-measured film duration, and together covering every
  paragraph of the unit exactly. Gaps between segments (scene lead-ins and tails, credits) are fine.
- Only two shapes per anchor are accepted; any other split is refused:
  - whole paragraph: exactly one segment, offsets `0..len(text)`, no `sentence_index`. Every anchor of the paragraph
    map has this shape, and so does a sentence-map anchor whose sentences were not measured;
  - sentences (sentence map only): exactly the `split_sentences` spans with `sentence_index` 0..n-1. An anchor never
    mixes indexed and unindexed rows, and each sentence's `start_ms`/`end_ms` lies inside that anchor's
    paragraph-map time span.
- Character offsets count Unicode code points (Python `len`, not UTF-8 bytes or UTF-16 units) of the paragraph text
  exactly as Maison stores it (NFC, as exported by `export_audiovisual_source`).
- Hex values (`mp4_sha256`, `text_sha256`, `timing_sha256`) are 64 lowercase hex characters (`[a-f0-9]{64}`).
- Integers only; anchors and unit id are the live ids `export_audiovisual_source` wrote.
- Only measured clause times; never estimated or proportional positions.
- `measurement_evidence_ref` is validated (non-blank, at most 500 characters) and returned by `read_film_timing`, but
  it is NOT stored on the `TimingMap` row (the row has no field for it, and no migration is proposed). Root's
  importer should record it in the `timing_map.create` audit metadata and in the revision's `media_assets` evidence
  for the film (next to `measurement_evidence`), so each map stays tied to its measurement receipt.
- Gap rule (what the server does with the map): a film position inside a segment maps to that segment; a position
  between segments (scene lead-in or tail, credits) maps to the segment narrated last before it; a position before
  the first segment (title card) is `unmapped`. Reader -> film opens at the segment's `start_ms` (narration start).

## Rollout order

The new keys go into `earnalism.audiovisual-film-bundle.v1` without a version bump, and today's `read_film_bundle`
refuses any unit key outside `UNIT_KEYS`. So:

1. Root ships the importer change first (§2), accepting `timing`/`timing_sha256` as optional.
2. Only then does the skill emit them. A bundle from an older skill still imports (film without a map; Watch falls
   back to the part start).
3. Once every film to be published is re-bundled with a map, root may make the keys required.

## 2. What the importer must do (root, attach_audiovisual_film)

`library/film_timing.py` is the accepting side; the importer calls it:

1. `read_film_bundle`: allow `timing` and `timing_sha256` in `UNIT_KEYS` (both required once the skill ships them;
   accept their absence during the transition, which stages the film without a map), list the file, check
   its sha256, and fold `timing_sha256` into `bundle_sha256`.
2. Before mutation: `parsed = read_film_timing(raw, unit_id=row["unit_id"], mp4_sha256=row["mp4_sha256"],
   text_sha256=live.content_sha256)`; map `FilmTimingError` to `CommandError`.
3. In `attach`, inside the atomic block after the video asset is saved:
   `for m in film_timing_maps(current, video, parsed, anchor_map_by_ordinal(live_unit, unit)): m.save()`, plus an
   `audit(actor, "timing_map.create", m, {"asset_id": str(video.id), "asset_sha256": video.sha256, "precision": m.precision, "measurement_evidence_ref": parsed["measurement_evidence_ref"]})` row and the map ids in the stage output, as the audio importer does.

The maps are ordinary `TimingMap` rows on the film asset (`asset.kind = video`); no migration. They are never listed
by `/content/mappings` (audio only) and are served only through `/content/switch-position` to a member who may open
both formats of the LIVE revision in their territory.
