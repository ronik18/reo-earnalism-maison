#!/usr/bin/env bash
# Commit one Modal request's request file and ledger and push them to the branch, for the
# modal-jobs workflow. A conflicting rebase is aborted; the fresh branch head is then checked out
# and this run's own changes are re-applied from saved copies (`eav modal-replay`: the request file,
# and this job's ledger entry and exactly its saved rows; other jobs' rows are kept; a row billed
# on the branch meanwhile stays billed), then retried. The replay is stdlib only (`python3 -S -m
# eav.modal_requests replay`), so it works even when installing the dependencies failed.
# A failed fetch, rebase or replay never ends the script early: the attempt is retried, and if
# every attempt fails this run's own commit goes to the fallback branch modal-results/<job_id>
# (modal-results/<job_id>-run-<GitHub run id> if that branch already exists); `eav modal-fetch`
# still works from the R2 copy of the request (_request-result.json) when r2-upload ran.
# The checkout keeps no credentials: git authenticates with $GH_TOKEN, passed to git through the
# environment of each git call only (never on a command line, never to eav).
# Usage: modal-publish.sh <message> <job_id> <title root (absolute, or "")> <ledger (absolute, or "")> <request>
# An empty ledger (a request refused as invalid, whose ledger could not be located) publishes the
# request file alone.
set -euo pipefail
msg="$1"; job_id="$2"; root="$3"; ledger="$4"; req="$5"
: "${BRANCH:?}" "${RUNNER_TEMP:?}" "${GITHUB_WORKSPACE:?}"
SW="$GITHUB_WORKSPACE/skills/earnalism-audiovisual/software"
saved="$RUNNER_TEMP/modal-saved-$job_id"
rm -rf "$saved"
mkdir -p "$saved"
cp "$req" "$saved/request.json"
files=("$req")
if [ -n "$ledger" ]; then
  cp "$ledger" "$saved/ledger.json"
  files+=("$ledger")
fi

gitauth() {  # git with the push token for this call only
  if [ -n "${GH_TOKEN:-}" ]; then
    local auth
    auth="$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)"
    echo "::add-mask::$auth"
    GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0="http.https://github.com/.extraheader" \
      GIT_CONFIG_VALUE_0="AUTHORIZATION: basic $auth" git "$@"
  else
    git "$@"
  fi
}

commit() {
  git add -- "${files[@]}" || return 1
  if ! git diff --cached --quiet; then git commit -q -m "$msg" || return 1; fi
}

replay() {  # this run's changes on top of the fresh branch head, from the saved copies
  git checkout -q --detach "origin/$BRANCH" || return 1
  if [ -n "$ledger" ]; then
    (cd "$SW" && GH_TOKEN= python3 -S -m eav.modal_requests replay "$job_id" --root "$root" --saved "$saved") || return 1
  else
    cp "$saved/request.json" "$req" || return 1
  fi
  commit
}

resync() {  # returns non-zero when HEAD is not a pushable re-application of this run
  gitauth fetch -q origin "$BRANCH" || return 1
  # every attempt starts again from this run's own commit (never from a half-done earlier attempt)
  git checkout -q -f --detach "$own" || return 1
  if ! git rebase -q "origin/$BRANCH"; then
    git rebase --abort || true
    replay || return 1
  elif ! python3 -S -c 'import json, sys; [json.load(open(p)) for p in sys.argv[1:]]' "${files[@]}"; then
    replay || return 1  # a clean textual rebase that left invalid JSON: re-apply from the saved copies
  fi
}

commit
own="$(git rev-parse HEAD)"  # this run's own commit, pushed to the fallback branch if all else fails
synced=1
for attempt in 1 2 3 4 5; do
  if [ "$synced" = 1 ] && gitauth push -q origin "HEAD:$BRANCH"; then exit 0; fi
  sleep $((attempt * ${MODAL_PUBLISH_BACKOFF_S:-10}))
  if resync; then synced=1; else synced=0; echo "attempt $attempt: could not re-apply onto $BRANCH"; fi
done
fallback="modal-results/$job_id"
if gitauth ls-remote --exit-code --heads origin "$fallback" >/dev/null 2>&1; then
  fallback="$fallback-run-${GITHUB_RUN_ID:-$(date +%s)}"
fi
if gitauth push -q origin "$own:refs/heads/$fallback"; then
  echo "Could not push to $BRANCH; the result is on $fallback (merge it; modal-fetch reads the R2 copy)"
else
  echo "Could not push to $BRANCH or $fallback; modal-fetch reads the R2 copy of the request"
fi
exit 1
