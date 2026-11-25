# ক্ষুধিত পাষাণ — Colab run sheet (narration)

One prepared GPU job makes the narration for the ক্ষুধিত পাষাণ audiobook film. Only the owner runs it, in the existing Colab Pro account. After the run, Claude imports and checks the output with `eav`.

**Source:** the unpublished production draft (edition `54f37caa-050b-47c3-95c2-3cbc214d6485`, revision `3cb6a0b9-f774-4822-92e7-d4fc99de2ef4`, text hash `5fe21785…2949e`), 59 paragraphs, about 31 min of narration (estimate; real timing is measured from the audio).

**Budget:** forecast **4.24 CU** (already reserved). This title's lifetime cap is 60 CU and 55.76 CU remains. The notebook stops itself at its reserved time; nothing runs past it.

**Runtime:** pick **L4 GPU** in Colab (Runtime → Change runtime type).

**Links work once this folder is on `main`** (after the next merge). Until then, use the same files from branch `claude/wonderful-bardeen-s9k90x`.

| Job | Open in Colab | Input to put on Drive | Drive folder | Stops after |
|---|---|---|---|---|
| Narration (Earnalism Voice, `bn_arnav`) | [narration.ipynb](https://colab.research.google.com/github/ronik18/reo-earnalism-maison/blob/main/production/audiovisual/kshudhita-pashan/jobs/narration-9187e43e/narration.ipynb) | [inputs.zip](https://github.com/ronik18/reo-earnalism-maison/raw/main/production/audiovisual/kshudhita-pashan/jobs/narration-9187e43e/inputs.zip) | `MyDrive/earnalism-audiovisual/kshudhita-pashan/narration-9187e43e/` | 7,865 s (about 131 min) |

## Steps

1. Download `inputs.zip` (link above) and upload it, **unchanged and still named `inputs.zip`**, into the Drive folder (create the folders if they do not exist).
2. Open the notebook (link above). Set the runtime to **L4 GPU**.
3. In the **first code cell**, change `RUN = False` to `RUN = True`. Change nothing else.
4. **Runtime → Run all.** Allow Google Drive access when Colab asks.
5. When it finishes, the Drive folder holds the outputs and a `manifest.json`. Note the **compute units** Colab shows for the run.
6. Tell Claude: the job name (`narration-9187e43e`), the CU used, and share or zip the Drive folder. Claude imports it with `eav import`, which checks every file against the manifest.

## If something goes wrong

- **It stops early or crashes:** do not re-run or edit anything. Tell Claude the job name and the CU Colab shows; it is recorded with `eav close` and replanned within the budget.
- **"RUN is False" error:** step 3 was missed.
- **Input checksum error:** the `inputs.zip` was renamed, re-zipped or changed; download it again.
- **Colab asks for a different GPU or more units:** stop and tell Claude. Never lower the job's quality or split it to fit.

## What happens next (Claude)

After the narration is imported and checked: stills and music jobs for the film (another run sheet, within the remaining budget), then the film, reels and the 2-minute podcast preview clip. The audio reaches readers only after you approve its per-title audio clearance. Nothing is posted or published without your instruction.
