# বিচারক scene 14 v7 (28 Nov 2026: new shot 1 night-lane still and new shot 7 paan take bound, scene cut rebuilt and checked)

Operator run, `eav` commands only. The code ran from a clean worktree of HEAD `3576cd1` (`claude/great-gates-tpoz8n`,
scratchpad `wt-v7`) against the working root `R` = `V/root` in the main checkout. `B` = `production/audiovisual/bicharak`,
`V` = `B/pilot/v5`. Nothing was spent: no GPU, no Colab, no ElevenLabs. The source transcript (`source.json`,
`12fc3cb0…`), the source media, the official logo file (`951d21e8…`, overlaid by eav, no pixel edited) and the END
(`landscape.mp4`, `443be73b…`) are unchanged (sha256 checked before and after). No signed URL or `exchange.json` is in
any tracked file.

**Status: DONE. `qc` passes every gate, with no override. The v7 cut exists.**
- Outputs: `B/pilot/v7/scene14-v7.mp4` (sha256 `9a4b90ed…`) and `B/pilot/v7/scene14-v7.burned.mp4` (`4d70595b…`),
  gitignored byte copies of `R/film/film-01/film-01-f01s014{,.burned}.mp4`.
- Duration: 66.583 s (as v6) = 4 s title card + the 54.59 s scene + 5 s credits + 3 s END. −16.1 LUFS, −3.8 dBTP.
- Caption text unchanged: the soft track of v7 is byte-identical to v6's (extracted SRT compared with `cmp`).
- The owner's review (listening and viewing) is still open; the frame notes below are Claude's.

## What changed from v6 (owner, 28 Nov)

1. **Shot 1:** the still is the owner's pick `stills-f01s014-fix-r1` c3 (`R/film/film-01/stills/f01s014-1.png`,
   sha256 `7ad9cfe0…`, picked and recorded earlier in `picks/`); its depth map is the one made in
   `clips-f01s014-fix-r1`. No new binding was needed: `film --shots` takes the scene's pick and the map of exactly that
   still.
2. **Shot 7:** take `f01s014-14x` (`clips-f01s014-fix-r1`, start image the round-faced mother still c2; motion gate
   pass, no review notes) bound with `R/film/film-01/clip-picks.json` `{"f01s014/7": "f01s014-14x"}` (force-added).
3. **Plan:** shot 7's subject now ends "(take f01s014-14x)" instead of 14w, and
   `approval_record.owner_decisions_28_nov_2026_fix` records the three changes (shot 1 still, shot 7 take, the world
   bible's North Calcutta lanes). `plan-shots --root R --film 1 --scene f01s014 --bible B/specs/world-bible.json`:
   exit 0, "12 shots, 54.6 s, 5 Wan clip(s); rules R1-R3 pass". Re-approved with `--approve --by Claude --reviewer
   "<the v6 approval text, unchanged>; plus the owner fixes of 28 Nov 2026: shot 1 the new North Calcutta night-lane
   still (stills-f01s014-fix-r1 c3), shot 7 the new paan take f01s014-14x (round-faced mother, from
   stills-f01s014-fix-r1 c2), the world bible describes North Calcutta lanes"`: exit 0, new input sha256
   `62fa11c4…`. The plan's shots differ from v6 only in shot 7's subject text.

Everything else is as in v6: the shot 4 LED touch-up (12a touched), shot 11 captions at the top, the readable burned
caption style, sounds, music, waivers and overrides.

## Rebuild

- `film --root R --film 1 --shots --scene f01s014 --logo skills/earnalism-video/software/assets/standard-intro/v1/production-lockup.png --end-card skills/earnalism-video/software/assets/standard-intro/v1/landscape.mp4 --title বিচারক --author "রবীন্দ্রনাথ ঠাকুর" --narrator "Subhajit – Grounded Bengali Storyteller" --burn`:
  exit 0 (about 4 min CPU), "66.6 s, 12 shots at 24 fps, −16.1 LUFS, TP −3.8 dBTP"; motion-review notes for 12a
  (shot 4) and 9p (shot 11), as in v6. None for 14x.
- `qc --root R`: exit 0, **every gate passes** (below).
- Copied to `B/pilot/v7/`. Frames of the burned cut at every shot boundary, through shots 1 and 7, and of shots 10 and
  11 for the mother's face (scratchpad `v7/fr`).

## QC (`qc --root R`, `R/qc/report.json`, result `pass`, `failed` empty)

| Gate | Result | Measured |
|---|---|---|
| loudness | pass | −16.1 LUFS integrated, LRA 4.9 LU |
| true_peak | pass | −3.8 dBTP |
| new_info (R1) | pass | no gaps |
| holds | pass | none |
| black_bars | pass | none |
| hitches | pass | none |
| flashes (R10) | pass | max 1/s; one jump at 63.583 s (into the END card), planned |
| sound_on_picture (R4) | pass | every listed sound placed over its shot |
| captions (R5) | pass | no problems |
| margin | pass | voice over music 17.0 dB; voice over everything else 15.7 dB |
| peak_silence | pass | music bus −200 dB on the peak window |
| digital_zero | pass | none |

Overrides: none. Advisories as v6: motion review of 12a and 9p (G13), word check not run for `f01s014-p01`.

## Frame review (Claude, v7 burned cut)

- **Shot 1 (film 4.0–9.6 s):** a moonlit lane with lit wall-bracket lanterns, louvred shutters, wooden/iron
  balconies and arched doorways; **one moon**; **no wires or cables**; the closed black carriage is seen from behind.
  Problems:
  - **The horse is on the wrong side of the carriage.** Its rump and tail are nearest the camera, overlapping the
    carriage's back, with its head peeking out at the carriage's left side: it reads as a horse behind (pushing) the
    carriage, not one pulling it away.
  - **Not fully North Calcutta.** The near houses are plausible, but the background houses have pitched red-tile
    roofs and chimneys (a European look; the prompt asked for flat roofs with parapets). A house number ("12") is on
    the right pillar.
  - The shot is a depth glide (a push-in), so the carriage itself does not move; "moving away" is only implied.
- **Shot 1→2 (dissolve, about 9.2–10.0 s):** during the dissolve the lane's moon and the bedroom window's moon are
  both on screen, offset, so for under a second the frame shows **two moons**. Shot 2 alone has one. Not new: v6's
  1→2 dissolve shows two moons the same way.
- **Shot 7 (film 27.9–31.3 s):** the mother now has a **round face**, full cheeks, big open eyes, head covered, white
  sari with a red border, red bindi, small gold earrings; she folds betel leaves; an empty brass tray on the mat
  beside her keeps Hem's place empty. The face shape now agrees with shots 10 and 11 (round, broad jaw). But she is
  drawn much **younger and more childlike** than in 10 and 11: large chibi eyes, smooth unlined face, small body,
  where 10 and 11 show a careworn woman with forehead lines and eye bags. Costume and veil are consistent. Motion is
  gentle hand work, no warping seen. She sits centre-left rather than at the right of the room.
- **Shot 6→7 (hard cut, 27.924 s):** clean, no stray frame. **Shot 7→8 (dissolve, about 31.0–31.7 s):** the mother
  fades under Hem in the carriage as planned; no artefact. Captions in shot 7 bottom centre, legible on the pale
  wall and sari.
- Other boundaries, shot 4 (no LED), shot 11 (top captions clear of the pot), cards, END and logo: as in v6.

---

# বিচারক scene 14 v6 fixes (28 Nov 2026: owner review of v5, three picture fixes, scene cut rebuilt and checked)

Operator run, `eav` commands only, in the main checkout. `B` = `production/audiovisual/bicharak`, `V` = `B/pilot/v5`,
`R` = `V/root`. Nothing was spent: no GPU, no Colab, no ElevenLabs. The source transcript (`source.json`), the source
media (the adopted 12a take included), the official logo file (sha256 `951d21e8…`, overlaid by eav, no pixel edited)
and the END (`landscape.mp4`, `443be73b…`) are unchanged. No signed URL or `exchange.json` is in any tracked file.

**Status: DONE. `qc` passes every gate, with no override. The v6 cut exists.**
- Outputs: `B/pilot/v6/scene14-v6.mp4` (sha256 `a3eef13a…`) and `B/pilot/v6/scene14-v6.burned.mp4` (`3f37439d…`),
  gitignored byte copies of `R/film/film-01/film-01-f01s014{,.burned}.mp4`.
- Duration: 66.583 s (as v5) = 4 s title card + the 54.59 s scene + 5 s credits + 3 s END. −16.1 LUFS, −3.8 dBTP.
- The caption **text** is the book's, unchanged: the soft track (`mov_text`, `ben`) of v6 is byte-identical to v5's
  (extracted SRT compared with `cmp`), and `R/film/film-01/film-01-f01s014.vtt` has the same cues. Only the burned
  captions' position (shot 11) and look changed.
- The owner's review (listening and viewing) is still open; the frame notes below are Claude's.

## Fix 1 (V1): the LED-like cyan rectangle in shot 4 (take f01s014-12a)

**Measured** on all 121 frames of the 12a take (1280×704, sha256 `aee267a8…`):
- A cyan rectangle (G and B over R by > 40) at **x 200–241, y 214–237** (42 × 24 px), the same bounding box in every
  frame (centroid 219.4–220.3, 225.6–225.9): it never moves. A pale glow spreads above it to about x 280, y 200.
- It sits in the dark gap between two slats, just above the lit tan edge of the lower slat; the slat edges run down
  to the right at a slope of 0.31 (17.2°), measured on the edge at x 164–298.
- The background round it is static: every frame is within 2.8 levels (mean) of the per-pixel temporal median.
- In the v5 cut it showed through the whole of shot 4 (film 16.38–20.41 s).

**New eav feature: `clip-touchup`** (`eav/cliptouch.py`, `cmd_clip_touchup` in `eav/cli.py`; the skill's `touchup`
covers stills only). It repaints one recorded mask in every frame of an imported Wan clip into a **new** clip:
- mask: a box narrowed by hue/saturation/lightness rules, computed once on the clip's temporal median, grown and
  feathered, recorded as a PNG; fill: `along` (each pixel from the nearest unmasked pixels on both sides along a
  direction, blended by distance, so edges running that way survive) or OpenCV `telea`/`ns` inpaint;
  mode `plate` (the fill is made once on the median and composited into every frame; refused if the ring round the
  mask moves more than 4 levels) or `each`.
- filed as an imported `clip_touchup` job (0 CU): manifest with the reason, source path and sha256, output sha256,
  mask, fill, measurements and the motion gate verdict of the touched clip; `adopt` accepts it as a clip source.
- Tests: `tests/test_cliptouch.py` (fill rebuilds slat edges better than inpaint, the source is never written, the
  rectangle is gone from every frame, no flicker, plate mode refuses a moving background, record + adoption).

**Commands** (from `skills/earnalism-audiovisual/software`, `python3 -m eav.cli …`):
1. `clip-touchup --root R --film 1 --spec V/clip-touchup-f01s014-12a.json --job-id clip-touchup-f01s014-12a-noled`:
   exit 0. Mask box [192, 194, 300, 246], select hue 150–270° with lightness ≥ 0.2 (the cyan rectangle and its
   bluish-white glow; the tan slat edge is excluded by hue), grow 3, feather 2; fill `along` 17.2°; mode `plate`.
   - Mask: 3289 px in [192, 194, 300, 243]. Output `R/clip_touchup/clip-touchup-f01s014-12a-noled/f01s014-12a.mp4`,
     sha256 `10b422b2…`, 121 frames, libx264 crf 12. Source unchanged (`aee267a8…` before and after).
   - Outside the mask: PSNR 44.1 dB against the source, mean abs difference 1.23 levels (re-encode only).
   - Flicker: inside the mask the per-frame mean varies by 0.03 levels (std over time) after, 0.5 before; the
     frame-to-frame difference inside the mask is at most 0.11 levels. No cyan pixel is left in the box.
   - **Motion gate on the touched clip: pass, needs review**: the same blink-and-turn spikes as the original
     (frames 21, 28, 31, 63, 65, 68, 71, 80; the original also had 23), so the touch-up adds no motion.
2. `V/adopt-f01s014.json`: shot 4 now names `{"job": "clip-touchup-f01s014-12a-noled", "takes": ["f01s014-12a"]}`
   (the 7-c1 still pattern: touch up, then adopt). `adopt --root R --spec V/adopt-f01s014.json`: exit 0.
   - New clips job `adopt-f01s014-clips-6e17b18a0a` (12a touched, 14w and 9p as before, the shot 9 depth map).
   - Because the plan had been re-approved after the 27 Nov adoption, the adoption id (which hashes the plan) also
     re-bound the same stills and music as `adopt-f01s014-stills-84844ba15d` and `adopt-f01s014-music-9794ac599f`:
     the same files and sha256, 0 CU; the older adoptions stay on record. The scene mix was not re-made.

**Before/after (full size, frames 0, 60, 120 of the take and the cut at 18.0 s):** before, a bright cyan bar with a
white halo in the slat gap; after, the dark teal gap runs on unbroken between the slats, the lit tan slat edge and
its ink line are straight and continuous under where the bar was, the slat above has no glow. No smear, no seam at
the feather, no flicker; the rest of the frame (her face, hair and eyes, the other slats) is untouched.
Review crops: `R/clip_touchup/clip-touchup-f01s014-12a-noled/f01s014-12a.{before,after,mask}.png`.

## Fix 2 (V4): the shot 11 caption crossed the falling brass pot

**Measured** on every frame of shot 11 in the v5 cut (film 48.715–52.859 s; brass = HSV hue 18–32, S and V > 150,
right of x 700 so the earring is excluded): the pot is in her hands at y 881–964 and falls to the floor at
x 1189–1436, y 972–1080. **Its whole path: x 832–1448, y 840–1080**, the lower 22 % of the frame. v5's bottom
captions sit at y 960–1016 (one line) and crossed it for both cues of the shot ("তখন সেখানে সহসা", 49.065–50.460;
"কি লজ্জা প্রকাশিত হইয়া পড়িবে,", 50.640–52.508).

**New eav feature: a per-shot caption position in the shot plan.** `shots[].caption`: `"top"` or `"bottom"`
(default), validated by `shotplan.plan` and shown in the AV script. `film --shots` turns the top shots into
film-time spans; a burned cue that is on screen during such a span is drawn at the top (`film.caption_position`):
its first line's top 7 % of the height from the top edge, centred, clear of the logo's column (a line too wide for
the space beside the logo starts under it, `film.caption_baselines`). The soft track has no position and is
unchanged. Tests in `test_shotplan.py` and `test_film.py`.
1. `R/film/film-01/shots/f01s014.input.json`: shot 11 `"caption": "top"` and
   `approval_record.owner_decisions_28_nov_2026_review` (before-copy in the scratchpad).
2. `plan-shots --root R --film 1 --scene f01s014 --bible B/specs/world-bible.json`: exit 0, "12 shots, 54.6 s,
   5 Wan clip(s); rules R1-R3 pass". The same with `--approve --by "Claude" --reviewer "<the 27 Nov approval text>;
   plus the owner review of 28 Nov 2026: …"`: exit 0, new input sha256 `8469814b…`. The plan changed only in
   shot 11's `caption` and the approval.

**After:** in v6 the burned caption footprint (text, halo and band) during shot 11 is **x 615–1310, y 62–160**,
680 px above the pot's highest point; the pot falls and lands uncovered. R5 is untouched (same cues: ≤ 2 lines,
≤ 42 characters per line, 1–7 s, ≤ 15 cps; `qc captions` pass). Shots 10 and 12 keep bottom captions; the cue
before shot 11 ends at 48.364 s, before the cut, so no cue jumps position mid-cue.

## Fix 3: captions weak on the pale backgrounds of shots 7, 10 and 11

**New burned caption look** (`film.caption_image`): the same ivory Maison ink (250, 242, 228) and font size, a thin
dark outline, a **soft dark halo** hugging the glyphs (grown by px/6, blurred by px/9, 92 % at the glyph edge) and a
**subtle translucent band** behind each line (Maison canvas colour (25, 18, 22) at 60 %, rounded, blurred edges, no
hard box; it covers under 6 % of the frame). Test: `test_burned_caption_holds_4_5_to_1_on_white_and_pale_pictures`
(≥ 4.5:1 on white, pale cream and black, top and bottom).

**Measured** (WCAG luminance contrast, ink pixels of the burned frame against the ring 3–12 px outside the glyphs,
which takes in the outline, halo and band and the picture right behind them; "plain bg" = the picture behind the
text with no caption):

| Shot (time) | plain bg L | v5 ring mean | v5 ring p90 | v6 ring mean | v6 ring p90 |
|---|---|---|---|---|---|
| 7 (29.5 s) | 0.19 | 3.37:1 | 1.43:1 | **8.83:1** | 5.73:1 |
| 7 (30.6 s) | 0.19 | 3.39:1 | — | **8.78:1** | 5.64:1 |
| 10 (40.5 s) | 0.15 | 4.09:1 | 2.09:1 | **9.77:1** | 7.19:1 |
| 10 (44.0 s) | 0.14 | 4.28:1 | 2.24:1 | **10.01:1** | 7.30:1 |
| 10 (47.0 s) | 0.18 | 3.66:1 | 1.78:1 | **9.14:1** | 6.51:1 |
| 11 (49.8 s) | 0.38 → 0.42 (top) | 1.94:1 | 0.87:1 | **7.34:1** | 4.11:1 |
| 11 (51.5 s) | 0.51 → 0.54 (top) | 1.94:1 | 0.87:1 | **5.95:1** | 3.48:1 |

Every shot is now at or above 4.5:1 on average (the p90 column is the brightest tenth of the ring, the worst case;
in v5 it fell below 1:1 in shot 11, i.e. the picture next to the letters was brighter than the letters).
Script: `<scratchpad>/v6/contrast.py` (frames from the plain and burned cuts at the same time).

## Rebuild

3. `film --root R --film 1 --shots --scene f01s014 --logo skills/earnalism-video/software/assets/standard-intro/v1/production-lockup.png --end-card skills/earnalism-video/software/assets/standard-intro/v1/landscape.mp4 --title বিচারক --author "রবীন্দ্রনাথ ঠাকুর" --narrator "Subhajit – Grounded Bengali Storyteller" --burn`:
   exit 0 (3.4 min CPU), "66.6 s, 12 shots at 24 fps, −16.1 LUFS, TP −3.8 dBTP"; motion-review notes for 12a
   (shot 4, the touched take) and 9p (shot 11), as G13.
4. `qc --root R`: exit 0, **every gate passes** (below).
5. Copied to `B/pilot/v6/scene14-v6.mp4` and `scene14-v6.burned.mp4`.
6. Frames of the burned cut at every shot boundary, the peak (49.1 s), shots 4, 7, 10 and 11 (full size) and the
   cards; contact sheet in the scratchpad.

## QC (`qc --root R`, `R/qc/report.json`, result `pass`, `failed` empty)

| Gate | Result | Measured |
|---|---|---|
| loudness | pass | −16.1 LUFS integrated, LRA 4.9 LU |
| true_peak | pass | −3.8 dBTP |
| new_info (R1) | pass | no gaps |
| holds | pass | none |
| black_bars | pass | none |
| hitches | pass | none |
| flashes (R10) | pass | max 1/s; one jump at 63.583 s (into the END card), planned |
| sound_on_picture (R4) | pass | every listed sound placed over its shot |
| captions (R5) | pass | no problems |
| margin | pass | voice over music 17.0 dB; voice over everything else 15.7 dB |
| peak_silence | pass | music bus −200 dB on the peak window |
| digital_zero | pass | none |

Overrides: none. Advisories as v5: motion review of 12a and 9p (G13), word check not run for `f01s014-p01`.

## Frame review (Claude, v6 burned cut)

- Shot 4: the slats are clean through the whole shot; Hem's face, eyes (brown) and hair are as in v5; no mole.
- Shot 11: both cues at the top centre, over the plain wall and the top of her veil, never over her face, hands or
  the pot; the pot's fall and landing are uncovered. The logo (top right) is clear of the caption band.
- Shots 7, 10, 12 and the rest: captions bottom centre, ivory on the soft dark band, clearly legible on the pale
  wall, sari and floor; on the dark night shots (1–5) the band is barely visible.
- Joins, cards, END and logo as in v5.
- New, for the owner: the burned captions jump from the bottom (shot 10) to the top (shot 11) at the hard cut into
  the peak and back down at shot 12. This is intended (the pot), but the owner may want to judge the jump.

---

# বিচারক scene 14 v5: finish run (28 Nov 2026, sounds synthesized, scene cut built and checked)

Operator run, `eav` commands only, in the main checkout (`claude/great-gates-tpoz8n`). `B` = `production/audiovisual/bicharak`,
`V` = `B/pilot/v5`, `R` = `V/root`. Nothing was spent: no GPU, no Colab, no ElevenLabs. The source transcript
(`source.json`), the source media, the official logo file and the earlier sound files are unchanged. No signed URL
or `exchange.json` is in any tracked file.

**Status: DONE. `qc` passes every gate, with no override. The scene cut exists.**
- Outputs: `V/scene14-v5.mp4` and `V/scene14-v5.burned.mp4` (gitignored byte copies of
  `R/film/film-01/film-01-f01s014{,.burned}.mp4`).
- Duration: 66.583 s = 4 s title card + the 54.59 s scene + 5 s credits + 3 s END.
- The owner's review (listening and viewing) is still open. Everything below that is not a measurement is Claude's
  frame review, not the owner's.

## Owner decision applied (28 Nov 2026)

"Synthesize CC0 hooves (shot 1) and morning birds/crows (shots 9–10) ourselves, the same way the wheels, breeze and
broom were made; drop a sound that still sounds fake after a fair attempt; never use a third-party clip without a
verified CC0 record."

- **Hooves and morning birds: both kept.** Neither was dropped, so the plan's SFX lists are unchanged: no
  `plan-shots` re-run and no re-approval was needed. The approval of 27 Nov stands.
- Both were judged by measurement and by spectrogram only. **No human has listened to them yet**: their realism is
  an owner-review item (below).

## Sounds made (S1 and S3 resolved)

Generator: `B/pilot/v4/tools/synth_sfx_v5.py` (sha256 `569b8977…`).
- A sibling of `synth_sfx.py` (`18d2e096…`), reusing its filter, envelope and writer helpers and its `broom()`.
- Numpy plus OpenCV. No input recording. Deterministic: a re-run gives byte-identical files.
- Command: `python3 pilot/v4/tools/synth_sfx_v5.py pilot/v5/sfx --sweep
  pilot/v5/root/film_clips/clips-f01s014-door-r3/clips/f01s014-13s.mp4`.

Each new file has a `V/sfx/licences.json` entry: `CC0-1.0`, `basis.rule` `cc0-synthesis`, script and helper
sha256, seed, command, and output sha256. `cue --fx` accepted all 13 placements as `cc0-synthesis`.

| File | Length | Peak | RMS | Measured | sha256 |
|---|---|---|---|---|---|
| `hooves.wav` (shot 1) | 6.400 s, 48 kHz stereo, 24-bit | −3.0 dBFS | −23.0 dBFS | 18 beats; inter-onset 0.354 s ± 0.011 s (CV 3.1 %, 2.83 beats/s, a trot); a second hoof 13–45 ms after each beat (a clear re-attack ≥ 6 dB on 14 of 18); beat levels alternate strong and weak; spectral centroid 480–1200 Hz per 250 ms | `1ec043af…` |
| `crows.wav` (shots 9–10) | 14.500 s, 48 kHz stereo, 24-bit | −3.0 dBFS | −25.7 dBFS | 9 caws in 4 series (spans in `crows.caws.json`); caw centroids 973–1294 Hz, with **98–100 % of caw energy in 500–2500 Hz**; chirps of 2.6–4.2 kHz about 20 dB under the caws; an open-air bed about 30 dB under the caws keeps the gaps out of digital silence (centroid 650–900 Hz, about −58 dBFS) | `b7d8064e…` |
| `broom-13s.wav` (shot 10) | 9.600 s, 48 kHz stereo, 24-bit | −2.6 dBFS | −26.3 dBFS | 6 strokes, timed to the 13s sweep (below); centroid about 6 kHz in each stroke, silent after 5.1 s (13t has no strokes) | `1ba9e6c9…` |

- **Hooves:** one horse at a trot.
  - Each beat is a diagonal pair of hooves, a "clip-clop" flam of 18–42 ms.
  - Each hit is a shoe click, a hard knock with 3 random brick/hoof modes, and a small body thump.
  - Timing jitters by ±2.5 % and level by ±1.2 dB.
  - The lane is modelled as wall reflections at 11–67 ms plus a 0.45 s tail. A light room tone sits 24 dB under
    the trot. The level swells by 5 dB as the carriage draws near.
- **Birds:** each caw is a harmonic source falling about 16 % in pitch, with 5 % pitch jitter, shimmer, a weak
  subharmonic and a strong breathy noise component.
  - It passes through three formants (about 0.9, 1.5 and 2.2 kHz) and is band-limited to 450–2600 Hz, so nothing is
    harsh. The far crow is low-passed at 1.8 kHz.
  - The first series is placed in the narration's pause after "প্রভাত হইবে," (scene 32.69–33.34 s).
  - A first version had cleaner harmonics and read more like a horn than a crow, so the noise and jitter were
    raised. Its sha256 was never recorded.
- **Broom re-timed (S3).** Stroke peaks were taken from the 13s take itself (sha256 `d32cb44f…`).
  - Method: the per-frame mean absolute difference in the lowest 29 % of the frame (where only the broom pole
    swings), a 5-frame median (the take's 20-frame keyframe blips are single frames), a 3-frame mean, and maxima at
    least 10 frames apart above the median.
  - Peaks at 0.458, 1.375, 2.000, 2.917, 3.500 and 4.833 s of the clip. Each stroke sound starts 0.18 s before its
    peak.
  - These match the pole's swing in the contact sheet and the raw difference curve (frames 11, 33, 47, 69, 84 and
    113–115).
  - Recorded in `V/sfx/broom-13s.times.json`. The old `broom.wav` (v2 timing) is kept on file and not placed.

## Commands, in order

All from `skills/earnalism-audiovisual/software` as `python3 -m eav.cli …`.

1. `python3 B/pilot/v4/tools/synth_sfx_v5.py V/sfx --sweep R/film_clips/clips-f01s014-door-r3/clips/f01s014-13s.mp4`
   (above). Then `V/sfx/licences.json`, `README.md` and `fx-f01s014.json` were written.
   - In `fx-f01s014.json`, the broom starts on shot 10's first frame (35.20 s).
   - The pot is placed at 45.17 s: in 9p the pot leaves her hands at frames 10–11 and is on the floor by frame 12,
     so the impact falls inside the music's 0.4 s silence from 45.065 s.
   - Hooves and wheels (−44) play under shot 1, and the crows run from 30.69 s (the dissolve into shot 9) to the
     hard cut into shot 11.
2. `status --root R --scene f01s014`: exit 0, `Next:` = `cue --pick`.
3. `cue --root R --film 1 --scene f01s014 --stems adopt-f01s014-music-f5b90329a1 --pick --tonic D`: exit 0, picked
   drone `p3-drone-2`, solo `p3-esraj-4`, phrase `p3-sunrise-3`.
4. `cue --root R --film 1 --scene f01s014 --stems adopt-f01s014-music-f5b90329a1 --fx V/sfx/fx-f01s014.json`:
   exit 0, −15.9 LUFS, −3.9 dBTP, voice 17.0 dB over the music.
5. `film --root R --film 1 --shots --scene f01s014 --logo skills/earnalism-video/software/assets/standard-intro/v1/production-lockup.png --end-card skills/earnalism-video/software/assets/standard-intro/v1/landscape.mp4 --title বিচারক --author "রবীন্দ্রনাথ ঠাকুর" --narrator "Subhajit – Grounded Bengali Storyteller" --burn`:
   exit 0 (6 min CPU), "66.6 s, 12 shots at 24 fps, −16.1 LUFS, TP −3.8 dBTP".
   - The logo and END are the ones v4 used (v4 ACCEPTANCE §11). The logo file is unchanged (sha256 `951d21e8…`); eav
     overlays it, and no pixel of it was edited.
   - It printed motion-review notes for 12a (shot 4) and 9p (shot 11), the known G13 items.
6. `qc --root R`: exit 0, **every gate passes** (table below).
7. Frame extraction (`ffmpeg -ss`) of the burned cut at the start and end of every shot, the peak, mid and late
   shot 10, title, credits and END, followed by the frame review and listening measurements below.
8. Copied to `V/scene14-v5.mp4` (sha256 `2e026f92…`, the qc'd cut) and `V/scene14-v5.burned.mp4` (`6b66f6e2…`).

## QC (`qc --root R`, `R/qc/report.json`, result `pass`, `not_run` empty, `failed` empty)

| Gate | Result | Measured |
|---|---|---|
| loudness | pass | −16.1 LUFS integrated, LRA 4.9 LU |
| true_peak | pass | −3.8 dBTP |
| new_info (R1) | pass | no gaps |
| holds | pass | none |
| black_bars | pass | none |
| hitches | pass | none |
| flashes (R10) | pass | max 1/s; one jump at 63.583 s (into the END card), planned |
| sound_on_picture (R4) | pass | every listed sound placed over its shot, hooves (1) and crows (9, 10) included |
| captions (R5) | pass | no problems |
| margin | pass | voice over music 17.0 dB (16–18 dB); voice over everything else 15.7 dB (≥ 15) |
| peak_silence | pass | music bus −200 dB on [45.065, 45.465] |
| digital_zero | pass | none |

- **Overrides: none.** No gate failed, so none of the owner's accepted items had to be cited. Those items are shot
  3's Western cot and doorknob, shot 8's slats and its plain dissolve, the 4 s waivers and no mole.
- Advisories: the motion review of 12a (shot 4) and 9p (shot 11), as G13; the word check was not run for passage
  `f01s014-p01` (no transcript); contact sheet `R/qc/film-01--f01s014-contact.jpg`.

## Listening (measured; not an owner listening)

- **Delivered film:** −16.1 LUFS integrated, LRA 4.9 LU, sample peak −3.8 dBFS, astats flat factor 0, so **no
  clipping**. The burned rendition measures the same.
- **Scene mix:** −15.9 LUFS, −3.9 dBTP, flat factor 0.
- **Narration clarity:** the voice was fitted into the scene mix, and the margin is voice over everything else in
  speech.
  - Per shot: 1 15.9, 2 15.7, 3 19.2, 4 17.7, 5 17.1, 6 19.7, 7 19.6, 8 17.4, 9 17.4, **10 13.4, 11 13.0**,
    12 14.3 dB.
  - The narration stays on top everywhere.
  - Closest under speech: the broom in shot 10 (−33 dB placement), the pot drop at the peak (−24 dB, as in v4) and
    the murmur in shot 12.
  - The one 1 s window at 7.4 dB (18.25 s) is the narration fading at the end of "নাই!" over a steady −34.6 dB
    background, not masking.
- **Not assessed by ear:** whether the synthetic hooves, caws and broom sound real.

## Frame review (Claude, burned cut, at the start and end of every shot, the peak, title, credits and END)

- **Veiled mother: consistent.** In shots 7 (paan), 10 (door beat), 11 (peak) and 12 (neighbours) she wears a white
  sari with a red border, her head covered by the sari, a red blouse and a bindi.
  - Her face is drawn more gaunt in shot 7 (14w) than in shots 10 and 11. It is the same costume, so the owner may
    want to compare the faces.
- **Hem: no mole** in shots 4 (12a), 5 (the retouched eye still) and 8 (slats). Brown eyes throughout.
- **Anachronisms:** there are no modern objects. Shot 1 shows a horse carriage, cobbles and a lamp post; shot 9 a
  birdcage; shot 11 a brass pot.
  - Shot 3: the Western cot and round doorknob are accepted. The rectangle on the wall beside the door is the cot's
    shadow, not a switch plate.
  - Shot 8: the horizontal slats are accepted.
  - **Finding V1: shot 4 (12a) shows a small cyan glowing rectangle between the slats** (left, upper third, visible
    through the whole shot). It is probably meant as moonlight, but its colour and shape read like an LED. It was
    not hand-patched.
- **Captions:** readable throughout: white Bengali with a dark stroke at the bottom centre, one or two lines,
  correct conjuncts.
  - On the pale backgrounds of shots 7, 10 and 11 they are weaker but still legible.
  - At the peak, the shot 11 caption ("তখন সেখানে সহসা") crosses the falling brass pot.
- **Joins:** dissolves 1→2, 3→4, 5→6, 7→8 and 8→9 blend cleanly, as does the plain dissolve 8→9. Cuts land on
  their shots. Shot 12 drains and fades into the credits card.
  - Title card "বিচারক — রবীন্দ্রনাথ ঠাকুর"; credits with the author, the narration voice and the AI disclosure
    in both languages; then the approved END lockup. The logo is top-right throughout the scene.
- **Shot 10:** the mother really sweeps for the first 5 s, then stands and turns her head to the door. The broom's
  strokes follow the pole's swings.

## Findings

- S1 resolved: hooves and crows synthesized (CC0, recorded). S3 resolved: broom re-timed to 13s. S2 (the
  motion-pilot4 Commons records) still stands as a record. S4 (`night2.wav` and `pot-drop.wav` rest on the
  `pilot/sfx/README.md` declaration, and no generator script is on file) still stands.
- **V1 (picture, new): the cyan glowing patch in shot 4's slats** (12a). The owner decides whether to accept it or
  fix it through an eav route (`touchup` on the take is not available for a clip; a re-take would cost CU).
- **V2 (sound): realism unassessed by ear.** The hooves, caws and broom pass every measurement, but they are
  synthetic. The caws are the riskiest, because a formant-synthesized crow can sound like a toy.
- **V3 (mix): the broom (shot 10) and pot (shot 11) sit about 13 dB under the narration,** above the scene's 15 dB
  gate overall but closer than in the other shots. Lowering them is an fx gain change and a `cue --fx` re-run if the
  owner wants it.
- **V4 (caption placement):** the peak caption crosses the falling pot (shot 11).

## Remaining owner-review items

1. Listen to the cut. In particular: are the hooves (shot 1), crows (shots 9–10) and broom (shot 10) convincing? If
   one is not, drop it through `plan-shots` and re-approve, as the 28 Nov rule says.
2. Shot 4's cyan patch (V1).
3. The broom and pot levels against the narration (V3); the peak caption over the pot (V4).
4. The mother's face in shot 7 against shots 10 and 11 (same costume, more gaunt face).
5. The motion-review advisories for 12a and 9p (G13), and the word check that was not run (no transcript).
6. Owner approval of the finished reference scene (owner decision 3, 27 Nov).

---

# Earlier record: 27 Nov 2026 finish run (stopped at sound effects; superseded by the run above)


Operator run, `eav` commands only, from a clean worktree of HEAD `e3e19c2` (`claude/great-gates-tpoz8n`), at
`<scratchpad>/wt-s14e`. `B` = `production/audiovisual/bicharak`, `V` = `B/pilot/v5`, `R` = `V/root`. Nothing was
spent: no GPU, no Colab, no ElevenLabs. The source transcript (`source.json`) and all source media are unchanged. No
signed URL or `exchange.json` is in any tracked file.

**Status: STOPPED AT STEP 1 (sound effects). Two sounds the plan lists have no CC0 / author-released PD clip.**
`cue`, `film --shots`, `qc` and the frame review were **not run**, so `scene14-v5.mp4` and
`scene14-v5.burned.mp4` do not exist. Every other input of the scene is ready (`status --scene f01s014` exit 0,
`Next:` = `cue`).

## Commands, in order

All from `skills/earnalism-audiovisual/software` as `python3 -m eav.cli …`.

1. `status --root R --scene f01s014`: exit 0. Every job of the scene is imported or adopted;
   `Next:` = `cue … --stems adopt-f01s014-music-f5b90329a1 --pick --tonic <note>`, then `cue … --fx`.
2. Recorded the owner decisions of 27 Nov in `R/film/film-01/shots/f01s014.input.json` (the documented planner
   input; before-copy kept in the scratchpad): the 4 s minimum waived for shots **2, 3, 5, 6, 7 and 8**
   (`fidelity` sentence and `approval_record.owner_waivers`; the old `not_waived_under_4s` entry removed), and a new
   `approval_record.owner_decisions_27_nov_2026_finish` (the waiver; f01s014-5 = the retouched 7-c1 with its
   override reason; the accepted flaws of shots 3 and 8; the broom kept on shot 10). The accepted flaws of
   shots 3 and 8 were already in `accepted_flaws_for_frame_review`.
3. `plan-shots --root R --film 1 --scene f01s014 --bible B/specs/world-bible.json`: exit 0, "12 shots, 54.6 s,
   5 Wan clip(s); rules R1-R3 pass".
4. The same with `--approve --by "Claude" --reviewer "<the existing approval text> … plus the owner decisions of
   27 Nov 2026 at the finish: the 4 s minimum waived for shots 2, 3, 5, 6, 7 and 8; f01s014-5 is the retouched
   7-c1 (no mole); shot 3 cot/doorknob and shot 8 horizontal slats accepted for frame review; broom kept on shot
   10"`: exit 0. New input sha256 `eb7b54c3…`.
5. `R/picks/gate-overrides.json`: added `"f01s014-5": "owner: no mole; retouched 7-c1 so shots 4 and 5 match
   (27 Nov)"` (the owner's words).
6. `status --root R --scene f01s014`: exit 0, same `Next:` (the re-approval left every job bound).
7. Sound inventory and licence check (below). Made `V/sfx/`: byte copies of the six licensed synthesis files,
   with `licences.json` in the skill's synthesis format (`licence` `CC0-1.0`, `basis.rule` `cc0-synthesis`, source
   path, declaring README and sha256 per file) and a `README.md`.
8. Wikimedia Commons from this container: 4 requests to `commons.wikimedia.org/w/api.php` (the first metadata
   query for the motion-pilot4 bird files, then retries after the server's `retry-after`), **all HTTP 429**
   ("You are making too many requests to the API"). Stopped there, as instructed. The other CC0 hosts tried
   (opengameart.org, archive.org, bigsoundbank.com, api.wikimedia.org) are refused by this container's proxy
   (one HEAD each, no body fetched).

Not run (each comes after the stop): `cue --pick --tonic D`, `cue --fx`, `film --shots --scene f01s014`, `qc`,
frame extraction and review, the copy to `V/scene14-v5*.mp4`.

## Sound effects (R4)

| Sound | Shots | Clip | Licence record | Verified |
|---|---|---|---|---|
| night | 1, 2, 3 | `V/sfx/night2.wav` (= `pilot/sfx/night2.wav`, `95577e82…`) | CC0-1.0, original synthesis | `pilot/sfx/README.md` declares original synthesis, no third-party recording, CC0 1.0. No generator script is on file for it. |
| wheels | 1, 4, 5, 8, 12 | `V/sfx/wheels.wav` (= `v4/sfx`, `b36dd28b…`) | CC0-1.0, original synthesis | `v4/sfx/README.md` + `v4/tools/synth_sfx.py` (numpy noise, no input recording) |
| breeze | 6, 7, 9, 10 | `V/sfx/breeze.wav` (= `v4/sfx`, `6e87be47…`) | CC0-1.0, original synthesis | same |
| broom | 10 | `V/sfx/broom.wav` (= `v4/sfx`, `f414a078…`) | CC0-1.0, original synthesis | same. **Its strokes are timed to the old v2 6 + 6x take, not 13s/13t** (see S3) |
| pot | 11 | `V/sfx/pot-drop.wav` (= `pilot/sfx`, `7cacc212…`) | CC0-1.0, original synthesis | `pilot/sfx/README.md` |
| murmur | 12 | `V/sfx/murmur.wav` (= `v4/sfx`, `a1881bd6…`) | CC0-1.0, original synthesis | `v4/sfx/README.md` + `synth_sfx.py` |
| **hooves** | 1 | **missing** | none | no clip on file anywhere in the pilot |
| **crows / morning birds** | 9, 10 | **missing** | none | see below |

Rejected (no usable licence record): `motion-pilot4-f01s014/out/sfx-licences.json`.
- Every entry says only `"licence": "Public domain"` with no `basis`; `cue` (`licence_ok`) needs
  `basis.rule` `author-release` for PD, and the author-release categories could not be checked (Commons 429).
- The content does not fit either: `sfx-broom-1/2` are "Brushing ones teeth.ogg" / "Brushing teeth.ogg";
  `sfx-crowd-1` is a Berlin shopping mall and `sfx-crowd-2` church footsteps; `sfx-birds-2`
  ("En-us-dawn chorus.oga", CC0) is a Wiktionary pronunciation of the words "dawn chorus", not birds.
- `sfx-birds-1` ("Dawnchorus-uk.ogg", Silas S. Brown, "Public domain") is the only plausible birds clip; its
  author-release basis is unverified, and it is a UK dawn chorus (period/place fit for Calcutta crows unreviewed).

**Would a CPU-only Colab SFX cell get them?** Probably, at about 0 CU, but there is no eav route for it today.
- Colab has its own IP, so the Commons rate limit that stops this container should not apply there, and the
  skill's own sfx cell (`eav/templates/sfx_cell.py.txt`) already checks exactly the needed rule (CC0, or PD with a
  PD-self / author-release category and no country- or age-limited category; keyword as a whole word in the title).
- Whether Commons holds a CC0/PD-self "hooves" and a "crow" recording that passes that filter is not known until it
  runs.
- The gap: `job film_clips` refuses a job with no clip or depth item (`colab_jobs.py:977`: "needs at least one
  item (or depth_stills only)"), and its notebook asks for a GPU (`gpuType` L4/A100). An `sfx`-only, CPU-runtime
  film_clips job is a code change for the skill owner, not an operator step. Running the sfx cell by hand outside
  an eav job would not be an import eav can verify.
- Until then the other route the skill allows is original synthesis dedicated to CC0 (as v4 did for wheels and
  broom), which this run was not asked to make.

## QC

**Not run**: there is no scene cut. All gates (loudness, true_peak, new_info, holds, black_bars, hitches,
flashes, sound_on_picture, captions, margin, peak_silence, digital_zero, licences) are not run. Nothing is
listened to or frame-reviewed; everything is **unassessed**.

## Findings

- **S1 (blocker): no CC0 / author-released PD clip for hooves (shot 1) or crows/morning birds (shots 9, 10).**
  R4 (`qc sound_on_picture`) needs every listed sound placed over its shot, and `cue --fx` refuses a clip without a
  licence record. Commons is rate-limited (429) from this container; other CC0 hosts are blocked by its proxy.
- **S2 (record): the motion-pilot4 Commons fetch has unusable licence records and mismatched content** (above).
  It predates the sfx cell's author-release check.
- **S3 (sync): `broom.wav` is timed to the old sweeping take** (motion-pilot2 6 + 6x, v4 shot 10). Over 13s/13t
  its strokes will not land on the mother's strokes. It is licensed and can be placed, but the sync needs review
  (or a new broom clip timed to 13s).
- **S4 (verification limit): `night2.wav` and `pot-drop.wav`** rest on the `pilot/sfx/README.md` declaration;
  no generator script for them is on file.
- **Tonic for the cue: D.** Every stem of `adopt-f01s014-music-f5b90329a1` (music-pilot3b) was generated on
  "tonic D" / "drone on D" (its adoption.json items). That is what `cue --pick --tonic` should be given.

## Owner-review items

1. **Sounds:** choose how hooves and crows are obtained: a CPU-only Commons fetch cell in Colab (needs an
   `sfx`-only film_clips route in eav, ~0 CU), CC0 original synthesis, or drop the sounds from shots 1, 9 and 10
   (a plan change and re-approval).
2. Whether `sfx-birds-1` (UK dawn chorus) should be checked for author release, or a crow recording sought instead.
3. The broom sync over 13s/13t (S3).
4. Still open for the frame review once the film exists: the veiled mother's continuity (white sari, red border,
   head covered); no mole on Hem (shots 4, 5, 8); shot 3's Western cot and round doorknob and shot 8's horizontal
   slats (owner-accepted); captions; anachronisms (gate advisories on shots 1, 2 and 12).

## Next, once the two sounds exist with records

`cue --root R --film 1 --scene f01s014 --stems adopt-f01s014-music-f5b90329a1 --pick --tonic D`, then
`cue … --fx V/sfx/fx-f01s014.json` (music silent 0.4 s on the cut into shot 11, then low drone; the sunrise phrase
cut dead at the peak), then `film --root R --film 1 --shots --scene f01s014 --logo
skills/earnalism-video/software/assets/standard-intro/v1/production-lockup.png --end-card
…/standard-intro/v1/landscape.mp4 --title বিচারক --author "রবীন্দ্রনাথ ঠাকুর" --narrator "Subhajit – Grounded Bengali
Storyteller" --burn`, then `qc`.

---

# Earlier v5 record (superseded by the run above; kept for history)

# বিচারক scene 14 v5: acceptance test of the fixed `earnalism-audiovisual` skill (eav commands only)

Built 27 Nov 2026 in a scratch title root, `pilot/v5/root`. Everything ran locally. No Colab or GPU job was
built, staged or run, no ElevenLabs generation happened, and nothing was spent. No signed URL or `exchange.json`
was written. The source clips, stills, the v4 take, the real record (`../../record.json`), `film/film-01/` and the
shared allowance ledger were not touched; the scratch ledger was never written (no job was reserved). No skill code
was changed. No fallback driver was written.

**Result: BLOCKED before the first GPU job. There is no film and `eav qc` has nothing to check.**
`scene14-v5.mp4` and `scene14-v5.burned.mp4` do not exist.

The eav route ran through the voice import, the clause timing and the paper edit (`plan-shots`: 12 shots, R1–R3
pass). It stops at two points the operator may not cross alone:

1. **R11 approval.** The paper edit needs Claude plus an independent reviewer (and, for the reference scene, the
   owner). No independent reviewer was available to this run, and no approval was recorded.
2. **The first GPU job.** The approved picks cannot enter the scene's cinematic flow (G1). Every shot needs media
   from new, scene-bound GPU jobs (forecasts below). By the hard limits, this run stops there.

Even without the blocks, the imported narration is degraded (G3) and the v4 model id is unrecorded (G2). The voice
must be re-imported before any approval.

## Outputs (this folder; gitignored media)

| File | What |
|---|---|
| `root/` | Scratch title root: `record.json`, `plan.json`, `voice.json` (placeholder id, G2), `film/film-01/voice/f01s014.{wav,passages.json}`, `voice/passages/` (retimed passage, voicecheck, profile), `shots/f01s014.{input.json,json,av.md,timing.json}` |
| `take-scripts/f01s014-p01.txt` | The scene's untagged text, exactly the plan's (one passage) |
| `takes/f01s014-p01.wav` | Byte copy of `pilot/voice/v2/v4-retimed.wav` (sha256 `b644a867…`) |
| `passages/` | `split-passages` output for all of film-01 (41 untagged passage scripts) |
| `motion/` | Standalone `motiongate` verdicts and contact sheets of the five picked Wan takes |

## Paper edit (`plan-shots`, not approved)

Scene 55.171 s: a 0.85 s lead-in, speech from 0.85 s to 53.171 s, and a 2.0 s tail.

| n | start–end (s) | len | picked media | motion | layer | in | narration |
|---|---|---|---|---|---|---|---|
| 1 | 0.00–2.52 | 2.52 | night lane (still) | glide push 0.16, ease in | present | cut | মনে হইতে লাগিল, |
| 2 | 2.52–8.38 | 5.86 | daughter asleep (still) | glide push 0.12 | imagined | dissolve | পৃথিবীতে … নিমগ্ন। |
| 3 | 8.38–12.31 | 3.93 | Hem's empty bed, **PLANT** (still) | glide push 0.10 | imagined | cut | সেই আপনার ঘরে … মধ্যে |
| 4 | 12.31–16.73 | 4.42 | **12a** (motion-pilot4), Hem turns into the moonlight | Wan 1280×704 | present | dissolve | নিস্তব্ধ … তাহা |
| 5 | 16.73–20.09 | 3.37 | v6 `f01s014-7` (7-c1, corrected eye) | glide flat 0.15, ease out | present | cut | ইতিপূর্ব্বে … নাই! |
| 6 | 20.09–23.77 | 3.68 | **new still needed**: a grown daughter of the lane wakes at dawn | glide push 0.10 | imagined | dissolve | ঘরের মেয়েরা … উঠিবে, |
| 7 | 23.77–27.06 | 3.29 | **14w** (motion-pilot6), paan place, Hem's place empty | Wan 1280×704 | imagined | cut | নিঃসঙ্কোচে … হইবে, |
| 8 | 27.06–30.83 | 3.77 | **new still needed**: Hem in the slat of moonlight | glide flat 0.08, ease out | present | dissolve | আর গৃহচ্যুতা … রাত্রি |
| 9 | 30.83–35.76 | 4.92 | sunrise wall (still) | glide push 0.10, sweep down-left, ease in | imagined | **match** | কোন্‌খানে … প্রভাতে |
| 10 | 35.76–45.28 | 9.53 | **door beat 13q→13r** (motion-pilot6), veiled mother, 2 declared actions | Wan 1280×704, chain of 2 (241 frames for 230 needed) | imagined | cut | তাহাদের … পতিত হইবে |
| 11 | 45.28–49.44 | 4.15 | **9p** (motion-pilot6), pot drop: **PEAK** at 45.65 s (82.7 %), plants 3 and 10 | Wan 1280×704 | imagined | cut | তখন সেখানে সহসা … পড়িবে, |
| 12 | 49.44–55.17 | 5.74 | neighbours (still) | glide pull −0.12, zoom0 1.17, drain, ease out | imagined | cut | কি লাঞ্ছনা … উঠিবে! |

- **Shots:** 12 (the spec says 11, see G8). Four of them are Wan shots with five clips, which is 33 % of the shots.
- **Planning estimate:** "5 Wan clip(s), about 3.0 CU" (G9).
- **R7 and R8:** no soft flags. The fidelity note and the motifs are declared.

## Commands run

All `eav` commands ran from `skills/earnalism-audiovisual/software` as `python3 -m eav.cli …`.
`B` = `production/audiovisual/bicharak`, `V` = `B/pilot/v5` and `R` = `V/root`.

1. `init B/source.json --root R --ledger V/allowance-ledger.json --slug bicharak`: exit 0.
2. `plan --root R`: exit 0. It produced 19 scenes, and scene f01s014 is identical to the real `plan.json`.
3. `status --root R`: exit 0. `Next:` asks for `voice.json`.
4. Wrote `R/voice.json` = `{"model_id": "unrecorded-eleven-v4"}`. This is a deliberate placeholder: no Eleven v4
   model id is recorded anywhere (G2).
5. `split-passages film-01 --root R --out V/passages`: exit 0. It splits f01s014 into two passages, but the take on
   file is one 51.9 s scene take (G4).
6. Copied `v4-retimed.wav` to `V/takes/f01s014-p01.wav` (byte copy), and wrote the scene text unchanged to
   `V/take-scripts/f01s014-p01.txt`.
7. `import-take film-01 --root R --scene f01s014 --scripts V/take-scripts --audio V/takes --engine elevenlabs
   --model unrecorded-eleven-v4 --voice-id j5PhP1QJv2DvlhRv3mEv --voice-name "Subhajit – Grounded Bengali
   Storyteller" --credits 0`: exit 0.
   - Voicecheck WARNING `no_breath` 9.0122 against the uncalibrated limit 9. This is a warning, not a redo, so
     `--accept` was not needed.
   - `duration` is a warning (a run of one passage). The word check was NOT RUN (no transcript).
   - Joined to `film/film-01/voice/f01s014.wav`: 55.171 s, lead-in 0.85 s, tail 2.0 s.
   - **The re-retime moved the take's pauses (G3).** 0 credits.
8. `scene-timing --root R --film 1 --scene f01s014`: exit 2, "11 pause(s) of at least 0.3 s for 7 clause
   boundaries".
9. `scene-timing … --min-pause 0.35` and `… --min-pause 0.4`: exit 2 (10 pauses each).
10. `scene-timing … --min-pause 0.45`: exit 0 and wrote `f01s014.timing.json`. **Its mapping is wrong (G5),** so the
    file is not used.
11. Following that command's own `Next:` ("or time this scene's clauses by ear into the planner input's
    `timing`"), wrote `shots/f01s014.input.json`, Claude-authored, with 14 timing entries:
    - Times are measured pauses of the joined wav: `retime.detect_pauses` at −38 dB/0.15 s, plus the in-clause
      breaths at 12.22, 15.82 and 47.02 s at −34 dB.
    - Word placement at the three unpunctuated breaths is **estimated** (no ASR), and agrees with the v4 pilot's
      clause split within 0.4 s.
    - `length_s` is 55.171.
12. `plan-shots --root R --film 1 --scene f01s014 --bible B/specs/world-bible.json`: exit 0, "12 shots, 55.2 s, 5
    Wan clip(s), about 3.0 CU; rules R1-R3 pass, ready for approval".
13. `motiongate <13q> <13r> <14w> <9p> <motion-pilot4 12a> --out V/motion`: exit 0.
    - 13q and 14w pass.
    - 13r, 9p and 12a are REVIEW (spikes classed as motion). None fails.
14. Looked at the 13q/13r/9p/14w contact sheets. Shot 10's subject and `actions` were corrected to what the takes
    show: she pauses with the broom, then turns her head toward the door. She does not walk to it.
15. Re-ran step 12 with the corrected input: exit 0, the same result. The plan is **not approved** (G7).
16. `status --root R`: exit 0. `Next:` asks for scene **f01s001**'s voice (G6).
17. `film --root R --film 1 --shots --logo <production-lockup.png> --end-card <standard-intro landscape.mp4> --title
    বিচারক --author "রবীন্দ্রনাথ ঠাকুর" --narrator "Subhajit – Grounded Bengali Storyteller" --burn`: exit **2**,
    "scene f01s001 has no shot plan" (G6).
18. `qc --root R`: "STOP: nothing assembled yet".

The following were **not run**: approval, `job stills`, `pick`, `job film_clips`, `job music`, `cue`, a real
`film --shots`, `qc` on a film and frame extraction. Each comes after a block.

## GPU stop point (not built, staged or run)

The next eav step after approval is the scene-bound `job stills`. Then come `pick`, `film_clips` (Wan clips plus
depth), `music`, `cue`, `film --shots` and `qc`.

Forecasts come from `production/audiovisual/rates.json` through `eav.budget.forecast` (arithmetic only; no job
was built):

| # | Job | Contents | Forecast |
|---|---|---|---|
| 1 | **`job stills --spec` (`"scene": "f01s014"`)**, the first stop | 8 glide shots (1, 2, 3, 5, 6, 8, 9, 12) × 3 candidates = 24 stills, gated | **1.47 CU** (2721 s at 1.94 CU/h) |
| 2 | `job film_clips` (Wan) | 5 HD clips: shot 4, shot 7, shot 10 (2-clip chain), shot 11 | L4 6195 s is over the 4200 s session limit, so it splits 3 + 2 clips: 2.75 + 2.06 = **4.81 CU**. On an A100: **2.82 CU** |
| 3 | `job film_clips` (depth only, after the pick) | 6 non-flat glide picks (1, 2, 3, 6, 9, 12) | **0.76 CU** |
| 4 | `job music` (`"scene"`, roles) | drone / solo / phrase × 3 seeds | about **1.6 CU** (music-pilot3b, a job of the same kind, forecast 1.60) |

The total is about **8.6 CU on L4**. Most of it would regenerate media the owner has already picked (12a, 13q→13r,
9p, 14w, and the v6 stills), because of G1. Only shots 6 and 8 need genuinely new stills.

## Measurements (scene voice, `film/film-01/voice/f01s014.wav`)

- **Length:** 55.171 s. The first word lands at 0.85 s (R9: 0.5–1 s) and speech ends at 53.171 s, leaving a
  2.0 s tail.
- **Voicecheck:** pass `null`. Warnings: `no_breath` 9.0122 against 9 (uncalibrated) and `duration` (expected
  46.15 s from the 13 cps estimate). Words: not run.
- **Pauses at −34 dB, original take → re-retimed passage (G3):**

  | Place in the text | Original take | After re-retime |
  |---|---|---|
  | after "তাহা" (no punctuation) | 15.42–15.80 (0.38 s) | 15.35–16.87 (**1.51 s**) |
  | after "নাই!" | 18.04–19.67 (**1.63 s**) | 19.11–19.56 (**0.46 s**) |
  | after "রাত্রি" (no punctuation) | 30.18–30.44 (0.26 s) | 29.84–30.30 (0.46 s) |
  | after "প্রভাত হইবে," | 31.91–32.59 (0.68 s) | 31.77–33.17 (**1.39 s**) |

## QC result

**Not run: there is no film** (`qc`: "nothing assembled yet"). The gates (loudness, true_peak, new_info, holds,
black_bars, hitches, flashes, sound_on_picture, captions, margin, peak_silence, digital_zero) are all **not run**.
Nothing is assessed; listening and frame review are **unassessed**.

## Acceptance findings

- **G1 (blocker, command gap): the already-imported, owner-picked pilot media cannot enter a scene's cinematic flow
  without new GPU jobs.**
  - The eav jobs `stills-pilot4..7-f01s014`, `motion-pilot6-f01s014` and `music-pilot3b-f01s014` in the real record
    were built without a spec `"scene"`. Their `job_target` events have no `scene`, and the motion-pilot6 items
    have no `"shot"`.
  - `_scene_picks` takes only picks of jobs with `scene == sid` (`eav/cli.py:917-934`).
  - `film.pick_wan_clips` takes only items with `shot == n` (`eav/film.py:471`).
  - `_depth_maps` reads only a job's `depth_stills` (`eav/cli.py:949-957`); motion-pilot6 has none.
  - So even in the real root, `film --shots` stops with "have no picked still" or "no film_clips item for shot n".
  - In a scratch root the jobs are absent altogether, and importing their outputs needs a manifest with the scratch
    job's `job_id` and `input_zip_sha256` (`eav/importer.py:138-145`). No manifest was forged.
  - The v6 art picks (`pilot/v6/art/f01s014-{7,9,13,14}.png`) are hand-copied files and have no recorded pick.
    `f01s014-13` is also a hand OpenCV touch-up made outside `eav touchup` (`pilot/v5/stills/README.md`).
  - **Needs a decision:** either an adoption path (bind an imported job's items to a scene and shots, and record
    picks of its existing candidates; a code change, not a one-liner), or about 8.6 CU of regeneration (above).
- **G2 (blocker, record gap): no Eleven v4 model id is on record.**
  - `voice.json` is absent in the title root, and no file in the repo names the v4 model.
  - `import-take` needs it (`eav/cli.py:1372-1387`). This run used the placeholder `unrecorded-eleven-v4`, so the
    scratch record's model field is a placeholder, not a fact.
  - The owner must supply the id that generated `v4-retimed.wav`.
- **G3 (defect, narration damaged): `import-take` re-retimes a take, and `retime.plan_pauses` maps every detected
  pause in text order to the punctuation marks, including unpunctuated breaths** (`eav/retime.py:131-144`, called
  at `eav/cli.py:1475-1477`).
  - The owner-endorsed take is already retimed. Re-retiming it moved the dramatic 1.63 s pause after "নাই!" into the
    middle of the sentence after "তাহা" (1.51 s), shrank the "নাই!" pause to 0.46 s, and doubled the comma pause
    after "প্রভাত হইবে," (0.68 → 1.39 s). See the table above.
  - The same in-order mapping will mis-time any real v4 take with an in-clause breath.
  - Two things are needed:
    1. a retime that skips breaths it cannot match to punctuation (a code fix, not a one-liner);
    2. the raw downloaded v4 take, or an import option for a take that is already retimed.
  - The source transcript is unchanged. Only its pauses moved.
- **G4 (route mismatch, warning only):** the v4 take is one 51.9 s scene take, but `split-passages` cuts the scene
  into two passages.
  - Cutting the audio by hand would be a hand-patch, so it was imported as one 46 s-of-speech passage.
  - `import-take` does not hold a passage to 15–30 s.
  - With a run of one passage, `duration` is only a warning, and the voicecheck profile is measured from this one
    take. The profile saved in the scratch root is therefore uncalibrated.
- **G5 (defect): `scene-timing` checks only the pause count, never the positions** (`eav/cli.py:3540-3556`).
  - At `--min-pause 0.45` the count matched (7), but the mapping took the in-clause breath at 44.92 s and missed the
    0.45 s comma pause at 26.83 s.
  - Clauses 6–8 were therefore mislabelled. For example, "এবং সেই … পড়িবে," was timed as 3.4 s, when it runs about
    15 s. The command wrote the file and exited 0 without a warning.
  - Partly caused by G3, which made comma pauses shorter than a breath.
  - The timing was hand-entered through the documented `"timing"` path, and its word placement is estimated.
- **G6 (command gap, F6 still open): there is no per-scene route.**
  - `status` / `Next:` walks the film from f01s001 (`eav/cli.py:665-677`, `680+`). After every scene-14 step it
    points back to scene 1.
  - `film --shots` has no `--scene` and stops on "scene f01s001 has no shot plan" (`eav/cli.py:1998-2017`).
  - A reference-scene build cannot follow `Next:` or assemble without restricting `plan.json`, which v4 did by hand.
- **G7 (process stop): R11 approval needs an independent reviewer, and none was available.** The reference scene
  also needs the owner. The plan stays NOT APPROVED, and no approval string was invented (compare v4's F16).
- **G8 (plan, F1 carries over): 12 shots, not the spec's 11.**
  - With this narration, shots 5+6 (6.9 s) and 8+9 (8.7 s) cannot merge as glides under R1.
  - The door beat replaces the old shot 10 as ruled. The spec's "sunlight onto the empty pillow" shot is still
    absent (the planted payoff is the empty bed, shot 3).
- **G9 (estimate, F15 partly open): the `plan-shots` compute** reports "5 Wan clips, about 3.0 CU". It counts the
  chain now, but it ignores takes that already exist and uses 0.6 CU per clip. The job forecast from `rates.json`
  is 4.13 CU on L4 for the same five clips.
- **G10 (F3 still open, not exercised): standalone `glide`** has no `--zoom0` or `--near-gain` (parser at
  `eav/cli.py:3725-3736`).
- **G11 (minor, scratch only): the scratch root shows a lifetime cap of 60, not 100.** `title-caps.json` sits only
  beside the real ledger (`eav/budget.py:59-71`). Forecasts above are unaffected.
- **G12 (picture risk): the door beat (13q→13r) is nearly static.** In its contact sheets the mother stands with the
  broom and only turns her head.
  - `plan-shots` passes the shot on its two declared actions.
  - `qc new_info` measures frame similarity, and may fail shot 10 (9.5 s) as it failed v4's sweeping shot.
  - Worth checking before spending on regeneration.
- **G13 (review, not failure): the motion gate flags 13r, 9p and 12a as REVIEW**, with spikes classed as motion:
  - 9p at frames 10–17 and 111–113;
  - 12a at frames 21–31 and 63–80, the blink and turn known from pilot calibration;
  - 13r at frame 115.

  13q and 14w pass. The thresholds are uncalibrated.

## Remaining owner-review items

1. **Approve the scene 14 paper edit** (the AV table above, `root/film/film-01/shots/f01s014.av.md`), or rule on
   the 12-shot count (G8). An independent reviewer is also needed (G7).
2. **Choose between regenerating about 8.6 CU** of already-picked media through scene-bound jobs, and asking for an
   eav adoption path for the imported pilot jobs (G1).
3. **Supply the Eleven v4 model id**, and the raw downloaded v4 take if it exists (G2, G3). Until the retime fix
   lands (G3), the imported scene voice misplaces the "নাই!" held breath.
4. **Picture checks:**
   - 13q/13r: the door beat is nearly static (G12).
   - 9p: the pot drop is REVIEW in the motion gate.
   - 12a and the 7-c1 eye still: confirm the eye colour matches.
   - The contact sheets show one consistent veiled mother (white sari, red border, head covered) across 13q, 13r,
     9p and 14w.
5. **New stills for shots 6 and 8** have no existing material.
6. **Listening and frame review stay unassessed.** No film exists.
