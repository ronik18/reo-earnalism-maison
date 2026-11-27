# Film recipe: the full-length audiobook film

Landscape 1920×1080 for Maison review and YouTube. The full text, unchanged, read in the
Earnalism Voice over illustrated scenes with gentle motion and a quiet theme-fit score.
It never claims character acting: it is illustrated cinema.

## 1. Plan (`plan`)

- Scenes of 30–90 s at natural boundaries (paragraph ends; a heading opens a scene).
  A paragraph longer than 90 s splits at sentence boundaries; a single sentence longer
  than 90 s stays one scene and is flagged `over_90s_sentence`.
- One keyframe still per 8–15 s of narration (`keyframes` in each scene).
- Narration over about 40 minutes: a chapter-by-chapter **series**, one film per unit,
  sharing one world bible, voice and score palette.
- Read the flags `plan` prints. A flagged scene is reviewed, not silently re-split.

## 2. World bible (before any still)

Write it once per title and reuse it in every prompt:

- **Period and place**: era, region, architecture, clothing, objects that must be right.
- **Palette and light**: 3–5 colours, one light family (e.g. "late afternoon, warm low sun").
- **Lens and look**: "painterly illustrated cinema, soft grain, 35 mm, shallow depth".
- **Character sheets**: for each recurring person a fixed one-line description (age, face,
  hair, clothing, one distinguishing detail), repeated word-for-word in every prompt.
- **2–3 anchor stills** generated first and reviewed; later prompts quote the same bible.
- **Exclusions, said positively**: FLUX.1-schnell runs at guidance 0 with no negative prompt and
  tends to draw what a prompt names, so never write "no text, no watermark, no modern objects".
  Name what is there instead: "bare plaster wall", "plain white borderless widow's sari, bare
  wrists and ears", "1880s men's dhoti and chador", "unlettered paper". Put the same style clause
  at the FRONT of every prompt ("hand-painted gouache illustration, visible brushwork, ...") so one
  look dominates the whole film, then each character's fixed signature, then the beat.

## 3. Stills spec (`job stills --film N --spec stills.json`)

```json
{"items": [{"key": "f01s001-1", "prompt": "<bible preamble>. <what the text shows at this beat>",
            "seed": 101, "width": 1344, "height": 768}]}
```

- Keys are `<scene_id>-<k>` (k = 1..keyframes): `film` finds stills by scene id and
  spreads them evenly across the scene.
- Each prompt shows what the text says at that beat; never contradict the text. Same seed
  family per character for stability.
- After import, look at every still: anatomy, identity drift, stray text, continuity.
  Regenerate only failing stills (a new small stills job with new seeds), never the whole set.
  Per-key rule: `film`, the reel stills step and `status` take each key's still from the most
  recently **imported**, non-retired stills job (plain job or chunk) that provides it, so a small
  replacement job replaces exactly its keys; `status` lists which job supplies each key and the
  film artifact records it (`stills_by_key`). Retiring the replacement brings the earlier stills
  back. A chunk that ran but was closed needs its keys from a newer job (`--replace-chunk`, or a
  new stills job with new prompts); `film` refuses while any expected key has no imported still.
- Do not "pick a seed and regenerate it": FLUX re-runs with the same seed are not reproducible
  across batches (another batch, chunk or GPU gives another picture), so a still that was nearly
  right is not recovered that way. Fix the prompt, or retouch a small defect (below).

## 3a. Retouch (small defects only)

Some defects survive every regeneration: a bindi dot on a widow's forehead, a small earring, a
scrawled signature or lettering in a corner or on a plaster wall. Paint them over locally, at $0:

```
python3 -m eav.cli retouch <key> --root <title root> --film N \
    --region x,y,w,h[:ellipse|rect] [--region ...] --reason "<what is removed>"
```

- Coordinates are the still's own pixels; `ellipse` is the default shape. Each region is at most
  3% of the image and all of them at most 6%; the CLI refuses a region outside the image, a larger
  one, and an empty reason. Use it **only** for small defects; never to change a character, a face,
  clothing, a pose or the composition (that is a new prompt and a stills job for that key).
- The source is the still that currently supplies the key under the per-key rule. The fill is
  deterministic (numpy + Pillow): harmonic (Laplace) inpainting from the region's boundary, then
  texture sampled from a ring of untouched pixels around it with a generator seeded from the
  source's sha256, and a 3 px feathered edge; every other pixel is copied byte for byte. The same
  source and regions always give the same file.
- It writes `stills/retouch/<key>-<n>.png` and records a `still_retouch` artifact and a
  `retouch`/`applied` event: source path, sha256 and job id, the regions, the method (with its
  iteration count and noise seed), the output sha256 and the reason.
- The retouch supplies its key in place of its source while that source is still the key's current
  import. A newer stills import of the key makes it **stale**: it is no longer used and `status`
  says so (retouch the new still if it needs it). A second retouch of a key starts from the first.
  `retouch-undo <key> --root ... --film N --reason "..."` retires the newest (kept on record); the
  key falls back to the retouch before it, else to the import. A retouched file that no longer
  matches its recorded sha256 stops `film`.
- Look at the retouched still before the film uses it. `status` lists the retouched keys; the film
  artifact's `stills_by_key` gives a retouched key as `{job_id, retouch: {path, sha256, n, reason,
  source_path, source_sha256, ...}}` and `retouched_keys` lists them.

## 4. Score

Default: the cleared VCSL original-composition route of `earnalism-audiobook-score`
(`editorial_score.py`), cues at measured boundaries. Richer colour (strings, flute,
tanpura/sitar textures): ACE-Step instrumental cues from a theme brief (`job music`,
`"lyrics": "[instrumental]"`), arranged at scene starts with `film --cues-job <id>`.
No drums or vocals under narration; silence at turns.

## 5. Assembly (`film --film N --logo ... --end-card ... --score ...`)

What the CLI does, in order:

0. Refuses a narration group with a `suspect_truncated` unit (≥ 29.0 s, or > 1.6 x the
   job's median characters per second: Parler's ~30 s cut-off) unless the owner listened
   and names it with `--accept-qc <unit_key,...>` (see `earnalism-voice.md`).
1. Concatenates the imported narration WAVs with the voice pauses and **measures** every
   unit boundary (`eav.film.narration_track`, ffprobe) → `film/film-NN/timing.json` with
   a provenance block (method, measured_with, WAV hashes, narration job id).
2. Writes SRT subtitles from that measured timing.
3. Trims the score bed to the narration and masters with `eav.mix.duck_and_master`:
   score ducked 19 dB under speech, −16 LUFS integrated, true peak ≤ −1 dBTP. A miss is a
   QC failure, not a warning.
4. `eav.film.assemble`: slow push-in on each still, cross-dissolves on narration
   boundaries, the approved Earnalism logo lockup top-right (from `earnalism-video`, no
   backing box), the approved END card once.

## 6. Review

`qc` checks loudness and peak and writes a contact sheet; look at it. It also lists any
`suspect_truncated` narration units (advisory, with the owner's `--accept-qc` list). Then the
candidate-bound review: opening, every join, the climax and the full ending. The end card
and description credit AI-generated illustration.
