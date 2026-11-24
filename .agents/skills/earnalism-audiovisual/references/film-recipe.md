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
- **Lens and look**: the house style ([visual-style.md](visual-style.md)), 2D animated feature-film
  illustration; the job builder appends it to every prompt, so never write a second style.
- **Character sheets**: for each recurring person a fixed one-line description (age, face,
  hair, clothing, one distinguishing detail), repeated word-for-word in every prompt.
- **2–3 anchor stills** generated first and reviewed; later prompts quote the same bible.
- **Negative list**: no text, letters, logos, watermarks, extra fingers, modern objects.

## 3. Stills spec (`job stills --film N --spec stills.json`)

```json
{"items": [{"key": "f01s001-1", "prompt": "<character lines>. <what the text shows at this beat>. <period, palette, light>",
            "seed": 101, "width": 1344, "height": 768}]}
```

- Keys are `<scene_id>-<k>` (k = 1..keyframes): `film` finds stills by scene id and
  spreads them evenly across the scene.
- Each prompt shows what the text says at that beat; never contradict the text. Same seed
  family per character for stability.
- After import, look at every still: anatomy, identity drift, stray text, continuity.
  Regenerate only failing stills (a new small stills job), never the whole set.

## 4. Score

Default: the cleared VCSL original-composition route of `earnalism-audiobook-score`
(`editorial_score.py`), cues at measured boundaries. Richer colour (strings, flute,
tanpura/sitar textures): ACE-Step instrumental cues from a theme brief (`job music`,
`"lyrics": "[instrumental]"`), arranged at scene starts with `film --cues-job <id>`.
No drums or vocals under narration; silence at turns.

## 5. Assembly (`film --film N --logo ... --end-card ... --score ...`)

What the CLI does, in order:

1. Concatenates the imported narration WAVs with the voice pauses (the narration job's own
   voice style: a `--expressive` job's grouped units and varied pauses; an `import-take`
   ElevenLabs job's `continuous` style adds nothing inside a scene and 1200 ms between scenes,
   references/earnalism-voice.md) and **measures** every unit boundary (`eav.film.narration_track`, ffprobe) → `film/film-NN/timing.json` with
   a provenance block (method, measured_with, WAV hashes, narration job id).
2. Writes SRT subtitles from that measured timing.
3. Trims the score bed to the narration and masters with `eav.mix.duck_and_master`:
   score ducked 19 dB under speech, −16 LUFS integrated, true peak ≤ −1 dBTP. A miss is a
   QC failure, not a warning.
4. `eav.film.assemble`: slow push-in on each still, cross-dissolves on narration
   boundaries, the approved Earnalism logo lockup top-right (from `earnalism-video`, no
   backing box), the approved END card once.

## 6. Review

`qc` checks loudness and peak and writes a contact sheet; look at it. Then the
candidate-bound review: opening, every join, the climax and the full ending. The end card
and description credit AI-generated illustration.
