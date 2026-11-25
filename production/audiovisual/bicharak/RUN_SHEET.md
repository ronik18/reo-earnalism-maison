# বিচারক — Colab run sheet (first film)

Three prepared GPU jobs make the narration, the illustrated stills and the score for the বিচারক audiobook film. Only the owner runs them, in the existing Colab Pro account. Nothing else is needed from you; after each run, Claude imports and checks the output with `eav`.

**Budget:** the three jobs are forecast at **6.22 CU** together (already reserved). This title's lifetime cap is 60 CU and 53.78 CU remains. Each notebook stops itself at its reserved time; nothing runs past it.

**Runtime:** pick **L4 GPU** in Colab (Runtime → Change runtime type) for every job.

## Order and links

Run them one at a time, in this order. Each can be a separate Colab session.

| # | Job | Open in Colab | Input to put on Drive | Drive folder | Stops after |
|---|---|---|---|---|---|
| 1 | Narration (Earnalism Voice, `bn_arnav`) | [narration.ipynb](https://colab.research.google.com/github/ronik18/reo-earnalism-maison/blob/main/production/audiovisual/bicharak/jobs/narration-film-01-r2/narration.ipynb) | [inputs.zip](https://github.com/ronik18/reo-earnalism-maison/raw/main/production/audiovisual/bicharak/jobs/narration-film-01-r2/inputs.zip) | `MyDrive/earnalism-audiovisual/bicharak/narration-film-01-r2/` | 4,899 s (about 82 min) |
| 2 | Stills (FLUX.1-schnell) | [stills.ipynb](https://colab.research.google.com/github/ronik18/reo-earnalism-maison/blob/main/production/audiovisual/bicharak/jobs/stills-film-01-r3/stills.ipynb) | [inputs.zip](https://github.com/ronik18/reo-earnalism-maison/raw/main/production/audiovisual/bicharak/jobs/stills-film-01-r3/inputs.zip) | `MyDrive/earnalism-audiovisual/bicharak/stills-film-01-r3/` | 4,715 s (about 79 min) |
| 3 | Music cues (ACE-Step) | [music.ipynb](https://colab.research.google.com/github/ronik18/reo-earnalism-maison/blob/main/production/audiovisual/bicharak/jobs/music-film-01-r2/music.ipynb) | [inputs.zip](https://github.com/ronik18/reo-earnalism-maison/raw/main/production/audiovisual/bicharak/jobs/music-film-01-r2/inputs.zip) | `MyDrive/earnalism-audiovisual/bicharak/music-film-01-r2/` | 1,931 s (about 32 min) |

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

After all three are imported: assemble the film with the score, run the quality checks, build the reels' narration and shots (separate small jobs, another run sheet), then write the posting kit with tagged YouTube links. Nothing is posted or published without your instruction.
