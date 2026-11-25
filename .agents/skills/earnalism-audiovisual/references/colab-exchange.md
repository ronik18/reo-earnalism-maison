# Colab R2 exchange (default route for narration, stills, retouch, edit and music)

Owner-approved 2026-11-23 (option B). The owner's only action per Colab job is:
**open the notebook in Colab, set `RUN = True` in the first cell, Run all.** Inputs arrive
and outputs leave through two short-lived, single-object signed URLs on the PRIVATE R2
bucket; Claude stages and collects everything else.

```
exports/colab-exchange/<title>/<job_id>/inputs.zip    GET  (Claude uploads it; the notebook downloads it)
exports/colab-exchange/<title>/<job_id>/outputs.tar   PUT  (the notebook uploads it; Claude collects it)
```

Wan `reel_clips` jobs are **out of scope**: they keep the Wan batch builder's own route
(its notebook, authority file and export archive, `references/reel-recipe.md`).

## Owner (one step)

1. Open `jobs/<job_id>/<kind>.ipynb` from the job's Drive folder
   (`MyDrive/earnalism-audiovisual/<title>/<job_id>/`) in Colab (L4).
2. Set `RUN = True` in the first cell, then Runtime → Run all.
3. When it finishes, tell Claude the CU Colab shows. The last cell prints
   `outputs.tar upload: HTTP 200`; any other status raises an error (the outputs stay in
   Drive and nothing is claimed).

## Operator (Claude) steps

```sh
cd skills/earnalism-audiovisual/software
export EAV_R2_ACCOUNT=<cloudflare account id> EAV_R2_BUCKET=<private bucket>
export CLOUDFLARE_API_TOKEN=placeholder      # the egress proxy injects the real token here
python3 -m eav.cli exchange-stage <job_id> --root <title root>
```

1. `exchange-stage` uploads the job's `inputs.zip` (Cloudflare REST
   `PUT /client/v4/accounts/{acc}/r2/buckets/{bucket}/objects/{key}`, `application/zip`),
   records `job/exchange_uploaded` (key, sha256, bytes) and prints two Maison commands.
2. Sign them where the R2 credentials live, as a **Render one-off job** on the Maison web
   service (no new service, no paid resource):
   ```sh
   python manage.py presign_colab_exchange --key exports/colab-exchange/<title>/<job_id>/inputs.zip --method GET
   python manage.py presign_colab_exchange --key exports/colab-exchange/<title>/<job_id>/outputs.tar --method PUT --content-type application/x-tar
   ```
   Each prints one JSON line `{key, method, url, headers, expires_at}` (default TTL 6 h,
   max 24 h; the key must match the exchange pattern, GET only for `inputs.zip`, PUT only
   for `outputs.tar`). Save both lines to one file **outside the repository**.
3. `python3 -m eav.cli exchange-stage <job_id> --root <title root> --signed <that file>`
   checks both requests (exact keys, methods, PUT `Content-Type: application/x-tar`,
   HTTPS R2 URL of that exact object, expiry at least 2 h away, including the SigV4
   `X-Amz-Expires` in the URL), refuses an ended or imported job, writes
   `jobs/<job_id>/exchange.json` and records `job/exchange_staged` (keys and expiry only).
4. Put `exchange.json` and the notebook in the job's Drive folder. The owner runs it.
   The notebook refuses to start when the URLs would expire before its hard stop.
5. `python3 -m eav.cli exchange-collect <job_id> --root <title root> --units <CU Colab shows>`
   downloads `outputs.tar`, extracts it inside the title root (flat regular files only:
   absolute paths, `..`, sub-directories, links, devices and duplicate names are refused)
   and hands the folder to the normal import: every manifest, sha256, `COMPLETE` status
   and job-item check still applies. The temporary folder is removed on success and on
   failure. Success records `import/accepted` and `job/exchange_collected`.
6. Held (exit 4)? A failed or `INCOMPLETE` run is `close`d with the CU Colab shows; never
   rebuild or rerun a job to get past a hold. Expired URLs before the run: re-sign (step 2–3).

Manual fallback (no R2): copy `inputs.zip` into the Drive folder, run, download the folder,
`import <job_id> --from <folder>`. A Drive download that contains `exchange.json` is fine:
the importer skips it and never imports it.

## Security

- The signed URLs are **short-lived capabilities**. They live only in `exchange.json` in
  the job dir (gitignored: `production/**/exchange.json`) and in the job's Drive folder;
  **never in record.json**, never in a commit, ticket, chat message or log. The record keeps
  keys, hashes and expiry only; Maison's audit line omits the URL.
- One object per URL, one method per object; the PUT signs its content type. A leaked URL
  reaches one object until it expires; delete the Drive copy of `exchange.json` after collect.
- The notebook never prints the URLs; the inputs download is sha256-checked against both
  the job and `exchange.json` before it is kept, then the unchanged notebook check runs.
- Nothing here creates buckets, tokens, lifecycle rules or any paid resource.
