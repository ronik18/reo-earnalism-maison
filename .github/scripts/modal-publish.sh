#!/usr/bin/env bash
# Commit one Modal request's request file and ledger and push them to the branch, for the
# modal-jobs workflow. A conflicting rebase is aborted; the fresh branch head is then checked out
# and this run's own changes are re-applied from saved copies (`eav modal-replay`: the request file,
# and this job's ledger entry and exactly its saved rows; other jobs' rows are kept), then retried.
# If every attempt fails,
# the result goes to the fallback branch modal-results/<job_id>; `eav modal-fetch` still works from
# the R2 copy of the request (_request-result.json).
# Usage: modal-publish.sh <message> <job_id> <title root (absolute)> <ledger (absolute)> <request>
set -euo pipefail
msg="$1"; job_id="$2"; root="$3"; ledger="$4"; req="$5"
: "${BRANCH:?}" "${RUNNER_TEMP:?}" "${GITHUB_WORKSPACE:?}"
SW="$GITHUB_WORKSPACE/skills/earnalism-audiovisual/software"
saved="$RUNNER_TEMP/modal-saved-$job_id"
rm -rf "$saved"
mkdir -p "$saved"
cp "$req" "$saved/request.json"
cp "$ledger" "$saved/ledger.json"

commit() {
  git add -- "$req" "$ledger"
  if ! git diff --cached --quiet; then git commit -q -m "$msg"; fi
}

replay() {  # this run's changes on top of the fresh branch head, from the saved copies
  git checkout -q --detach "origin/$BRANCH"
  (cd "$SW" && python3 -m eav.cli modal-replay "$job_id" --root "$root" --saved "$saved")
  commit
}

commit
for attempt in 1 2 3 4 5; do
  if git push -q origin "HEAD:$BRANCH"; then exit 0; fi
  sleep $((attempt * 10))
  git fetch -q origin "$BRANCH"
  if ! git rebase -q "origin/$BRANCH"; then
    git rebase --abort
    replay
  elif ! python3 -c 'import json, sys; [json.load(open(p)) for p in sys.argv[1:]]' "$ledger" "$req"; then
    replay  # a clean textual rebase that left invalid JSON: re-apply from the saved copies
  fi
done
fallback="modal-results/$job_id"
if git push -q origin "HEAD:refs/heads/$fallback"; then
  echo "Could not push to $BRANCH; the result is on $fallback (merge it; modal-fetch reads the R2 copy)"
else
  echo "Could not push to $BRANCH or $fallback; modal-fetch reads the R2 copy of the request"
fi
exit 1
