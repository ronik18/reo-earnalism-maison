# Scene 14 v6 (বিচারক f01s014): owner fixes for shot 1 and shot 7, stills job built

28 Nov 2026. Operator run, `eav` commands only. The code ran from a clean worktree of HEAD `4764585`
(`claude/great-gates-tpoz8n`), at `<scratchpad>/wt-fix2`. The root is
`R = production/audiovisual/bicharak/pilot/v5/root`, the same working root as before.

**Status: READY FOR THE CONTROLLER TO STAGE `stills-f01s014-fix-r1`.** The follow-up film_clips job is forecast
only, not built.
- Nothing was staged, presigned, uploaded or run. No Colab, GPU or ElevenLabs call was made, and nothing was spent.
- `source.json` (the book's transcript) is unchanged. No source media was modified: the stills, takes and art I
  read were only decoded to scratch frames.
- No signed URL and no `exchange.json` is in any tracked file. The notebook only carries the template's code
  references to `exchange.json`, as earlier jobs do.

## 1. Shot 7: how the mother's face in 14w differs

Frames were extracted to the scratchpad from these takes:
- `14w` (adopted, frames 0, 60 and 120);
- `13s` (frames 0 and 100) and `13t` (frames 60 and 120), from `clips-f01s014-door-r3`;
- `9p` (frames 0, 30 and 100).

Her face was cropped from each and compared side by side (`<scratchpad>/fix2/faces-row.png`, plus gridded crops
`grid-*.png`).

In 14w she is not the same face as in shots 10 and 11. It is a narrower, longer, more angular face drawn in a
finer "glamour illustration" manner:

| | 14w (shot 7) | 13s/13t (shot 10) and 9p (shot 11), and the anchor |
|---|---|---|
| Face outline | Long tapering oval. Straight cheek planes run down to a **pointed chin**, and the cheek is cut in under the cheekbone. Jaw width at mouth level is about **0.66** of the face width at eye level. | **Round, broad face** with full, soft, blushed cheeks and a wide, soft jaw ending in a rounded chin. Jaw width over eye-level width is about **0.75** (9p, frontal) and about **0.9** (13s, three-quarter view). |
| Cheeks | A shadow plane runs from the ear down to the jaw, under the cheekbone. This reads as **hollow cheeks**, which is the "gaunt" look. | Full cheeks with a rose blush. The "careworn" look comes from lines instead: forehead creases, eye bags, smile lines. |
| Eyes | **Closed for the whole take** (frames 0–120). Heavy lowered lids, long fashion-style lashes, thin brows angled down. | **Large, round, open eyes** with white sclera and thick, expressive brows. |
| Neck | Long, slender neck with visible collarbone lines. | Short, full neck. |
| Details | **Large round gold disc earrings with a red centre.** Red teardrop bindi. Orange-red sari border. | Small gold drop earrings. Round or diamond bindi with sindoor. Crimson sari border. |

The ratios are approximate. I read them by hand from the gridded crops, and pose differs between the takes
(14w has her head bowed in three-quarter view).

In short: 14w gives her a slimmer, younger, hollow-cheeked face with a pointed chin and closed eyes. The other
shots give her a round, full-cheeked, wide-jawed face with big open eyes.

## 2. Cheaper alternatives checked (none buildable without a deviation)

- **A frame of her from another take as the 14w start image.**
  - 13s/13t show the sunlit courtyard holding the broom, and 9p shows Hem's bedroom holding the pot.
  - None shows the paan mat, so using one would change shot 7's approved subject ("the paan-making place … Hem's
    place on the mat is only empty space").
  - 13t is also a profile view. Rejected.
- **Another existing paan still.** I looked at stills-pilot7 `f01s014-14` c1, c3 and c4 and stills-pilot4 c1–c3
  (c2 of pilot7 is the current start, `301980b6…` = `pilot/v6/art/f01s014-14.png`):
  - pilot7 c1 and c4 have the same narrow, pointed-chin face. c4 is also a gate certain fail (detached hand).
  - pilot7 c3 has a girlish face, a wall cable (an anachronism) and a gate certain fail (detached hand).
  - pilot4 c1–c3 show young girls; c2 has no veil.
  - None matches the round face.
- **Qwen edit (`job edit`) of the current paan still with a 9p face reference.** A separate job of about 1.75 CU on
  L4 (3243 s; 3 candidates). The shot 7 item inside this stills job costs about **0.08 CU** at the margin (0.96 vs
  0.88 CU without it). Retouch would also be a separate job, and OpenCV touch-up cannot reshape a face. All of these
  still need a new Wan clip.
- **Shot 7 as a glide instead of Wan.** The depth-only follow-up would be 0.75 CU instead of 1.44, saving about
  0.69 CU. But this changes the approved plan's motion type for shot 7 (Wan → glide) and drops the shown daily
  task, so it is a design deviation needing the owner's approval. **Not built.** Offered as an option only.

## 3. Stills job built: `stills-f01s014-fix-r1`

Command:

```
job stills --root R --film 1 --spec R/specs/stills-f01s014-fix-r1.json --job-id stills-f01s014-fix-r1 --rates production/audiovisual/rates.json
```

It exited 0.

| | |
|---|---|
| **Forecast** | **0.96 CU** (0.9619), reserved on the root's pinned scratch ledger `V/allowance-ledger.json` |
| **GPU** | **L4** (FLUX.1-schnell, `min_vram_gib` 0, notebook `gpuType` L4) |
| Hard stop | 1785 s |
| Work | 2 items × 3 candidates = 6 stills, gated |
| Inputs | `inputs.zip` `8d6b978b…` (job.json plus `anchors/anchor-mother.png`) |
| Notebook | `b68a038a…` |

The real ledger was not touched; the controller reserves there at staging.

The two items, both at 1344×768 with T5 estimates within the 180 limit:

**`f01s014-1`** (seed 18101; T5 estimate with the house style **174**). The carriage line comes first, then the
setting:

> A closed black horse carriage with shuttered windows, seen from behind, rolls away down a narrow North Calcutta
> lane at deep night, one horse mid-stride. Bengal, 1880s: two- and three-storey lime-plastered houses with flat
> roofs and parapets, arched ground-floor doorways, wooden balconies with cast-iron railings, closed louvred wooden
> shutters in muted ochre and brown, a kerosene lamp on a wall bracket, an earthen drain channel. A flat low
> horizon, one full moon, wide indigo sky. Indigo night, silver moonlight, lamp amber.

**`f01s014-7`** (seed 18107; anchor `anchor-mother.png`; T5 estimate **170**). The mother's line is the world
bible's appearance line verbatim, then the face match, then the setting:

> Hemshashi's mother, a 40-year-old Bengali woman, kind careworn round face, red bindi, small gold earrings, an
> ivory-white cotton sari with a thin red border draped over her head, red blouse. Full soft cheeks, large round
> dark eyes open, looking down at her hands. Medium wide, morning: she sits cross-legged on a straw mat at the right
> of a plain cream-walled room, folding green betel leaves on a brass tray; the mat beside her lies empty. Bengal,
> 1880s. Ivory, faded vermilion, pale gold.

How the owner's rulings and the skill's rules are kept:
- **Owner rulings.** One horse, moving away. No standing cart, no hills and no towers are named. One moon.
- **Spire.** The optional temple spire was left out so that nothing reads as a tower.
- **Wording.** Both prompts are positive-only; the builder's check passed.
- **Eyes.** They are open on purpose, because the Wan negative prompt lists closed eyes.
- **Layout.** Her place on the right with the mat empty beside her keeps the shot 7 composition.

## 4. Follow-up film_clips job: forecast only, not built

The job depends on the picks. It would hold:
- one Wan clip for shot 7 at 1280×704, from the picked new start still. Shot 7 renders about 3.8 s, so one
  121-frame clip covers it;
- `min_vram_gib` 22 (L4), as in `clips-f01s014-door-r3`;
- the depth map of the new shot 1 pick, which `job film_clips` fills in from the picks. The maps of shots 2, 3, 6
  and 12 are already held by door-r3.

Forecast with `eav.colab_jobs.derive_compute` and `eav.budget.forecast` and the same rates: hd 1, gpu l4,
depth_s 102. Seconds = 900 × 1.15 + 900 decode + 120 export + 102 = **2157 s, i.e. 1.44 CU (1.438) on L4**.

Steps after the owner picks:
1. `pick --job stills-f01s014-fix-r1`.
2. Hand-copy the shot 7 pick into `pilot/v6/art` as the clip's image (as was done for f01s014-14.png).
3. Build a spec with one item (`shot` 7, 1280×704, a new take key, a prompt with one concrete action of the paan
   work).
4. `job film_clips ... --rates production/audiovisual/rates.json`.
5. After import, `film/film-01/clip-picks.json` `{"f01s014/7": "<new take>"}`. Optionally update the "(take
   f01s014-14w)" wording in shot 7's subject and re-approve.

## 5. Total

0.96 (stills, L4) + 1.44 (film_clips, L4) = **2.40 CU** (2.400).

## Notes

- **The world bible is part of the cause.** Its `period_and_place` says "green wooden shutters", and its
  `clean_frame` lists "gas lamps on wooden posts". Both point toward the European-looking lane. The new prompt
  states ochre and brown shutters and a kerosene lamp on a bracket instead. I did not edit the bible (it is canon);
  bringing it in line needs the owner's approval.
- **Scratch ledger.** `status` now shows 2.96 CU spent or reserved for the title in this root. The controller
  reconciles with the real ledger at staging, as before.

## Commit

`7a92b18` on `claude/great-gates-tpoz8n`, not pushed. Staged by explicit path, with the pilot paths force-added:
- `R/specs/stills-f01s014-fix-r1.json`;
- `R/jobs/stills-f01s014-fix-r1/{build-manifest.json,stills.ipynb,inputs.zip}`;
- `R/record.json` (only the job's additions).

The commit carries exactly the two required trailers.

## Fix r1 picks and clip job

28 Nov 2026. Operator run, `eav` commands only, from a clean worktree of HEAD `86b0169` (scratchpad `wt-fix3`). The
untracked media (stills, film_clips, source.json) was symlinked in. Nothing was staged, presigned, uploaded or run;
nothing was spent. The job is reserved only on the root's pinned scratch ledger; the controller reserves on the real
ledger at staging.

**Status: READY FOR THE CONTROLLER TO STAGE `clips-f01s014-fix-r1`.**

Picks (`eav pick --job stills-f01s014-fix-r1`):
- `f01s014-1` to c3. The gate needs review ("possible anachronism: modern high-rise building, spotlight"). The
  owner's reason: none is visible, it is a period lane. Advisory, so no override flag was needed; the reason is in
  `picks/gate-overrides.json`, replacing the old scene-r1 c1 text.
- `f01s014-7` to c2. The gate is a certain fail ("a hand with no body or arm near its wrist"), recorded with
  `--override-fail`. The owner's reason: a false positive, her hands fold the betel leaves in her lap.
  Also in `picks/gate-overrides.json`.

Job `clips-f01s014-fix-r1` (`job film_clips`, spec `specs/clips-f01s014-fix-r1.json`, exit 0):
- **Forecast 1.44 CU (1.438), L4, `min_vram_gib` 22.** Below the 1.8 CU limit. Deadline 2157 s.
- Model Wan-AI/Wan2.2-TI2V-5B-Diffusers with the depth model Depth-Anything-V2-Small; same settings as door-r3.
- Item 1: clip `f01s014-14x`, shot 7, 1280x704, seed 62714, one 121-frame clip (covers 3.39 s plus the 1-frame
  margin; the builder checked it). Its start image is the c2 still (sha256 `daf44486...`), hand-copied to
  `pilot/v6/art/f01s014-14x.png`. Prompt: the veiled mother folds betel leaves on the mat, slow natural hand motion,
  eyes open, looking down at her hands.
- Item 2: depth map only for `f01s014-1.png` (c3, sha256 `7ad9cfe0...`). The other maps are already held.

Shot plan: the route does not bind clips at build time. `f01s014.json` shot 7 keeps its text (it only names take
14w in the subject). After import, bind it with `film/film-01/clip-picks.json` `{"f01s014/7": "f01s014-14x"}`.
The plan file was not changed.

Commit `55fe84d` on `claude/great-gates-tpoz8n` (fast-forwarded, not pushed): picks, overrides, spec, job files and
record.json, force-added by explicit path, with the two required trailers.

## Fix r2 (owner review of v7, 28 Nov): stills job built, clip job forecast

Operator run, `eav` commands only. The code ran from a clean worktree of HEAD `0861596` (`claude/great-gates-tpoz8n`,
scratchpad `wt-fix4`) against the working root `R` in the main checkout
(`production/audiovisual/bicharak/pilot/v5/root`), so the job, `record.json` and the scratch-ledger reservation were
written straight into the main checkout. Nothing was staged, presigned, uploaded or run. No Colab or GPU call was
made, and nothing was spent. `source.json` is unchanged (`12fc3cb0…`, checked before and after), no source media was
modified (frames were only decoded to the scratchpad), and no signed URL or `exchange.json` is in any tracked file.

**Status: READY FOR THE CONTROLLER TO STAGE `stills-f01s014-fix-r2`.** The follow-up film_clips job is forecast only.

### Shot 7: her look in shots 10 and 11

Frames 40 and 100 of `13s` (door-r3) and `9p`, and of the v7 take `14x`, were extracted to `<scratchpad>/fix4/`.
In 13s/9p and the anchor (`anchor-mother.png`) she is a careworn woman of about 45: a round, full, mature face with
a soft broad jaw; faint forehead lines; slight bags and shadows under the eyes; smile lines; eyes of ordinary size
under thick brows; a sturdy, heavier build with full arms; a white sari with a crimson border over her head, a red
blouse, a red bindi and small gold drop earrings. In 14x (fix-r1 c2) she has the same costume but a child's
proportions: huge round eyes, a small smooth face, a slight body.

The prompt states that look in positive words. The house style that the builder appends asks for "large luminous
eyes", which is likely what pushed the eyes large; the prompt counters it with "normal-sized dark eyes" and an
explicit age and build. The world bible's age (40) was not edited; the prompt uses the owner's "about 45" reading
of shots 10 and 11.

**Reference strength.** The stills route (FLUX.1-schnell, text-to-image) has no reference weight or face-reference
input. The item's `anchor` (`anchor-mother.png`, the door still the bible names) only feeds the gate's similarity
check against her anchor, and it is kept. The skill's only face-reference route is a separate Qwen `job edit`
(about 1.75 CU), which is over the accepted spend and outside the one-stills-job brief, so it was not used.

### Job `stills-f01s014-fix-r2`

`job stills --root R --film 1 --spec R/specs/stills-f01s014-fix-r2.json --job-id stills-f01s014-fix-r2 --rates production/audiovisual/rates.json`: exit 0.

| | |
|---|---|
| **Forecast** | **0.96 CU** (0.9619), reserved on the root's pinned scratch ledger `V/allowance-ledger.json` (main checkout) |
| **GPU** | **L4** (FLUX.1-schnell, `min_vram_gib` 0) |
| Hard stop | 1785 s |
| Work | 2 items × 3 candidates = 6 stills, gated |
| Inputs | `inputs.zip` `cca844e3…` (job.json plus `anchors/anchor-mother.png`) |
| Notebook | `6d34a643…` |

The forecast is the builder's conservative figure: it matches fix-r1, whose run settled at 0.40 CU. That is the
spend the owner accepted for the run, but the reservation is 0.96 CU until settlement.

**`f01s014-1`** (seed 18201, fix-r1 used 18101; T5 estimate with the house style 175):

> One horse pulls a closed black carriage away down a narrow North Calcutta lane at night, seen from behind: the
> carriage's back nearest us, the horse ahead of it, half hidden by the carriage. Bengal, 1880s: lime-plastered two-
> and three-storey houses, every roof flat with a parapet, plain blank walls and pillars, arched doorways, wooden
> balconies, closed louvred shutters in muted ochre and brown, kerosene lanterns on wall brackets. Flat low horizon,
> one full moon, clear indigo sky. Indigo night, silver moonlight, lamp amber.

**`f01s014-7`** (seed 18207, fix-r1 used 18107; anchor `anchor-mother.png`; T5 estimate 177):

> Hemshashi's mother, a careworn 45-year-old Bengali woman, round full face, faint forehead lines, slight bags under
> her eyes, normal-sized dark eyes open, looking down at her hands, heavy-set build, red bindi, small gold earrings,
> an ivory-white cotton sari with a thin red border draped over her head, red blouse. Morning: she sits cross-legged
> on a straw mat at the right of a plain cream-walled room, folding green betel leaves; an empty brass tray on the
> mat beside her. Bengal, 1880s. Ivory, faded vermilion, pale gold.

Both prompts are positive-only (the builder's check passed). The owner's "no pitched roofs, tiles or chimneys",
"no numbers, signs or writing" and "no wires" are written as "every roof flat with a parapet", "plain blank walls
and pillars" and "clear indigo sky", because FLUX.1-schnell draws whatever is named. The shot 1 order puts the horse
"ahead of" the carriage and "half hidden by" it, with the carriage's back nearest the camera.

### Shot 11 eye anomaly (coordinator, 28 Nov)

The owner's screenshot (0:51 of v7, take `f01s014-9p`) shows a doubled eyeball in her eye. The start still
`pilot/v6/art/f01s014-9.png` (sha256 `89d3ee4f…`) has normal eyes, so Wan introduced the doubling. The fix is a re-take
from the same still with a new seed, carried in the same follow-up film_clips job:
- key `f01s014-9r` (9p and 9q are taken), shot 11, image `f01s014-9.png`, 1280×704, seed **62911** (9p used 61009);
  shot 11 is 4.14 s, so one 121-frame clip (5.04 s) covers it;
- prompt (positive-only, checked): "A careworn veiled Bengali mother with her white red-bordered sari drawn over her
  head stands at the empty cot holding a brass water pot; the pot slips from her hands and falls to the floor, she
  freezes in shock and slowly raises one hand to her lips, two normal eyes with natural eyelids, one consistent face
  throughout, her hands and arms stay whole and attached, static locked-off camera."
- The job's Wan negative prompt already lists "face morphing", "morphing eyelids", "blink" and "closed eyes".

### Follow-up film_clips job: forecast only, not built

After the owner picks, the job would hold:
- the new shot 7 clip (e.g. `f01s014-14y`, seed 62717) from the picked start still, hand-copied to `pilot/v6/art`;
- the shot 11 re-take `f01s014-9r` above;
- the depth map of the new shot 1 pick.

It would run on L4 (`min_vram_gib` 22), with the same model and settings as fix-r1. The forecast comes from
`derive_compute` and `budget.forecast` with the same rates: hd 2, depth_s 110. That is (2 × 900) × 1.15 + 900 decode
+ 120 export + 110 = **3200 s, i.e. 2.13 CU (2.133) on L4**, inside one session (4200 s). Without the shot 11 re-take
it would be 1.44 CU (2157 s).

### Total forecast

0.96 (stills) + 2.13 (clips) = **3.09 CU**. The settled spend is expected to be well below that: fix-r1's two jobs
settled at 0.40 CU each.

### Commit

The job files, the spec and `record.json` were committed on `claude/great-gates-tpoz8n` (not pushed): force-added by
explicit path, with the two required trailers. The scratch ledger is gitignored. Its new entry (`stills-f01s014-fix-r2`,
0.9619 CU, `reserved`) is in the main checkout's `V/allowance-ledger.json`.

## Fix r3 (owner decisions of 28 Nov on fix-r2): shot 7 picked, shot 1 an empty lane, stills job built

Operator run, `eav` commands only (`python3 -m eav.cli`), code from a clean worktree of HEAD `1ee2dc3`
(`claude/great-gates-tpoz8n`, scratchpad `wt-fix5`) against the working root `R` in the main checkout. Nothing was
staged, presigned, uploaded or run; no Colab or GPU call; nothing spent. `source.json` and all source media are
untouched; no signed URL or `exchange.json` is in any tracked file.

**Status: READY FOR THE CONTROLLER TO STAGE `stills-f01s014-fix-r3`.** The follow-up film_clips job is forecast only.

### Shot 7 pick and override
- `pick --job stills-f01s014-fix-r2 --choices {"f01s014-7": 3}`: exit 0, recorded `picks/stills-f01s014-fix-r2.pick-1.json`.
  The careworn mother, eyes down, folding leaves.
- Gate result for c3 (advisory until `gate-calibration.json` exists): pass false, needs_review true, eyes 0,
  hands_detached false, anchor_similarity 0.5905; notes "a character is expected but no face was detected", "a hand
  could not be judged attached or detached", "no person box: similarity used the whole frame". The owner reason, quoting
  that result (the model missed her face), is in `picks/gate-overrides.json` under `f01s014-7`.

### Plan (shot 1)
- Input `film/film-01/shots/f01s014.input.json`: shot 1's subject is now an empty narrow North Calcutta lane at deep
  night, moonlit, no vehicle, people or animals, wheel ruts leading away; the hooves and wheels fade away on the
  soundtrack as if the carriage has just turned out of sight. The SFX entries `night`, `wheels`, `hooves` stay on shot 1
  (the sound-on-picture gate matches them by name); the fade is noted in the subject and in the shot's music text.
  `approval_record.owner_decisions_28_nov_2026_fix` gained the shot 7 and shot 1 decisions.
- `plan-shots --film 1 --scene f01s014 --bible B/specs/world-bible.json`: 12 shots, 54.6 s, 5 Wan clips, R1-R3 pass.
  Re-approved with `--approve --by Claude`, the existing approval text unchanged plus "the owner changes of 28 Nov 2026
  after the fix-r2 review: shot 7's start still fix-r2 c3; shot 1 an empty lane, SFX fading away, new still fix-r3".
  Shot 7's subject still ends "(take f01s014-14x)"; it is updated when the new take is made.

### Job `stills-f01s014-fix-r3`
`job stills --root R --film 1 --spec R/specs/stills-f01s014-fix-r3.json --job-id stills-f01s014-fix-r3 --rates production/audiovisual/rates.json`: exit 0.
- **Forecast 0.88 CU** (0.87785), reserved on the root's pinned scratch ledger (96.09 CU left under the caps).
- **GPU L4** (FLUX.1-schnell, `min_vram_gib` 0); hard stop 1629 s; 1 item x 3 candidates, seeds 18301-18303 (fix-r1
  18101, fix-r2 18201); 1344x768; inputs.zip `7ec8d6b9...`, notebook `9f806175...`. The builder's T5 token check passed.
- First attempt was refused: the builder rejects the word "no" in a FLUX prompt. The owner's exclusions are written as
  "empty, deserted ... only still houses and moonlit dust", "plain blank walls and pillars" and "clear indigo sky".
- Prompt (`f01s014-1`): "An empty, deserted narrow North Calcutta lane at deep night, Bengal, 1880s, only still
  houses and moonlit dust: lime-plastered two- and three-storey houses, every roof flat with a parapet, plain blank
  walls and pillars, arched doorways, wooden balconies, closed louvred shutters in muted ochre and brown, kerosene
  lanterns on wall brackets, an earthen drain channel, wheel ruts in the dust leading away. Flat low horizon, one full
  moon, clear indigo sky. Indigo night, silver moonlight, lamp amber."

### Follow-up film_clips job: forecast only, not built
Holds the new shot 7 Wan clip from the fix-r2 c3 still, the shot 11 re-take `f01s014-9r` (from
`pilot/v6/art/f01s014-9.png`, seed 62911, the Fix r2 prompt, to fix the mother's double eye) and the depth map of the
shot 1 fix-r3 pick. L4 (`min_vram_gib` 22), the same settings as fix-r1 (hd 2, depth_s 110): (2 x 900) x 1.15 + 900 +
120 + 110 = 3200 s, **2.13 CU** (inside one 4200 s session). Total with the stills job: about 3.01 CU, expected to
settle far lower (fix-r1 0.40 CU each, fix-r2 0.23 CU).
