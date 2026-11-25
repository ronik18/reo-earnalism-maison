# ক্ষুধিত পাষাণ — Colab run sheet (first film)

Three prepared GPU jobs make the narration, the illustrated stills and the score for the ক্ষুধিত পাষাণ audiobook film. Only the owner runs them, in the existing Colab Pro account. Nothing else is needed from you; after each run, Claude imports and checks the output with `eav`.

**Source:** the unpublished production draft (edition `54f37caa-050b-47c3-95c2-3cbc214d6485`, revision `3cb6a0b9-f774-4822-92e7-d4fc99de2ef4`, text hash `5fe21785…2949e`), 59 paragraphs, 36 scenes, about 31 min of narration (estimate; real timing is measured from the audio).

**Budget:** the three jobs are forecast at **9.78 CU** together (already reserved: narration 4.24, stills 4.05, music 1.49). This title's lifetime cap is 60 CU and 50.22 CU remains. Each notebook stops itself at its reserved time; nothing runs past it.

**Runtime:** pick **L4 GPU** in Colab (Runtime → Change runtime type) for every job.

**Links work once this folder is on `main`** (after the next merge).

## Order and links

Run them one at a time, in this order. Each can be a separate Colab session.

| # | Job | Open in Colab | Input to put on Drive | Drive folder | Stops after |
|---|---|---|---|---|---|
| 1 | Narration (Earnalism Voice, `bn_arnav`) | [narration.ipynb](https://colab.research.google.com/github/ronik18/reo-earnalism-maison/blob/main/production/audiovisual/kshudhita-pashan/jobs/narration-9187e43e/narration.ipynb) | [inputs.zip](https://github.com/ronik18/reo-earnalism-maison/raw/main/production/audiovisual/kshudhita-pashan/jobs/narration-9187e43e/inputs.zip) | `MyDrive/earnalism-audiovisual/kshudhita-pashan/narration-9187e43e/` | 7,865 s (about 131 min) |
| 2 | Stills (FLUX.1-schnell, 138 keyframes) | [stills.ipynb](https://colab.research.google.com/github/ronik18/reo-earnalism-maison/blob/main/production/audiovisual/kshudhita-pashan/jobs/stills-d095a5f0/stills.ipynb) | [inputs.zip](https://github.com/ronik18/reo-earnalism-maison/raw/main/production/audiovisual/kshudhita-pashan/jobs/stills-d095a5f0/inputs.zip) | `MyDrive/earnalism-audiovisual/kshudhita-pashan/stills-d095a5f0/` | 7,520 s (about 125 min) |
| 3 | Music cues (ACE-Step, 8 instrumental cues) | [music.ipynb](https://colab.research.google.com/github/ronik18/reo-earnalism-maison/blob/main/production/audiovisual/kshudhita-pashan/jobs/music-a45f086f/music.ipynb) | [inputs.zip](https://github.com/ronik18/reo-earnalism-maison/raw/main/production/audiovisual/kshudhita-pashan/jobs/music-a45f086f/inputs.zip) | `MyDrive/earnalism-audiovisual/kshudhita-pashan/music-a45f086f/` | 2,760 s (about 46 min) |

## Steps for each job

1. Download its `inputs.zip` (link above) and upload it, **unchanged and still named `inputs.zip`**, into its Drive folder (create the folders if they do not exist).
2. Open its notebook (link above). Set the runtime to **L4 GPU**.
3. In the **first code cell**, change `RUN = False` to `RUN = True`. Change nothing else.
4. **Runtime → Run all.** Allow Google Drive access when Colab asks.
5. When it finishes, the Drive folder holds the outputs and a `manifest.json`. Note the **compute units** Colab shows for the run (Runtime → View resources, or the usage page).
6. Tell Claude: the job name, the CU used, and either share the Drive folder or zip it to Drive. Claude imports it with `eav import`, which checks every file against the manifest.

## If something goes wrong

- **It stops early or crashes:** do not re-run or edit anything. Tell Claude the job name and the CU Colab shows; it is recorded with `eav close` and replanned within the budget.
- **"RUN is False" error:** step 3 was missed.
- **Input checksum error:** the `inputs.zip` was renamed, re-zipped or changed; download it again from the link.
- **Colab asks for a different GPU or more units:** stop and tell Claude. Never lower a job's quality or split it to fit; that is the production rule.

## What happens next (Claude)

After all three are imported: look at every still (anatomy, identity drift, stray text, respectful depiction) and regenerate only failing ones in a small new stills job, assemble the film with the score, run the quality checks, then the reels and the 2-minute podcast preview clip (separate small jobs, another run sheet). The audio reaches readers only after you approve its per-title audio clearance. Nothing is posted or published without your instruction.
