#!/usr/bin/env bash
# Propose the working-tree changes to PATHs as one commit on BRANCH and open
# or update its pull request against BASE. Shared by the trackers
# (track-junctions.yml, track-binaries.yml).
#
#   propose-pr.sh --branch B --title T --body-file F [--base main]
#                 [--remote origin] [--skip-closed-title] -- PATH...
#
# Does nothing when:
#  - PATHs do not differ from the checked-out commit (nothing to propose);
#  - an open pull request's branch already holds exactly these PATHs, so a
#    daily run neither force-pushes an identical commit nor restarts its CI;
#  - --skip-closed-title and a closed pull request from BRANCH had this
#    title: it was turned down, and the next upstream version brings a new
#    title.
# Otherwise it commits onto BRANCH (from the checked-out commit), force-pushes
# with a lease on the branch state it saw, and creates or edits the pull
# request. GH_TOKEN authenticates `gh` and the push: checkouts do not persist
# credentials, so the push passes it as a one-off header that never reaches
# .git/config.
#
# No `|| true` on the queries: a failed `gh` or `git ls-remote` must stop the
# run, not pass for "no pull request" or "no branch".
set -euo pipefail

die() { echo "propose-pr: $*" >&2; exit 1; }

branch="" title="" body="" base=main remote=origin skip_closed=0
while [ $# -gt 0 ]; do
    case "$1" in
        --branch) branch="$2"; shift 2 ;;
        --title) title="$2"; shift 2 ;;
        --body-file) body="$2"; shift 2 ;;
        --base) base="$2"; shift 2 ;;
        --remote) remote="$2"; shift 2 ;;
        --skip-closed-title) skip_closed=1; shift ;;
        --) shift; break ;;
        *) die "unknown argument: $1" ;;
    esac
done
[ -n "${branch}" ] && [ -n "${title}" ] || die "--branch and --title are required"
[ -f "${body}" ] || die "--body-file must name a file"
[ $# -gt 0 ] || die "no paths to propose"
paths=("$@")

git add -- "${paths[@]}"
if git diff --cached --quiet -- "${paths[@]}"; then
    echo "Nothing to propose: ${paths[*]} already match $(git rev-parse --short HEAD)."
    exit 0
fi

remote_head=""
if git ls-remote --exit-code --heads "${remote}" "refs/heads/${branch}" >/dev/null; then
    git fetch --quiet "${remote}" "+refs/heads/${branch}:refs/remotes/${remote}/${branch}"
    remote_head="$(git rev-parse "refs/remotes/${remote}/${branch}")"
else
    status=$?
    [ "${status}" -eq 2 ] || die "cannot list ${branch} on ${remote} (git ls-remote exit ${status})"
fi

open="$(gh pr list --head "${branch}" --base "${base}" --state open --json number --jq '.[0].number // empty')"
if [ -n "${open}" ] && [ -n "${remote_head}" ] && git diff --cached --quiet "${remote_head}" -- "${paths[@]}"; then
    echo "#${open} already proposes this content on ${branch}; leaving it and its CI alone."
    exit 0
fi
if [ -z "${open}" ] && [ "${skip_closed}" = 1 ]; then
    closed="$(gh pr list --head "${branch}" --base "${base}" --state closed --json title --jq '.[].title')"
    if grep -Fxq -- "${title}" <<< "${closed}"; then
        echo "A closed pull request already proposed '${title}'; not reopening it."
        exit 0
    fi
fi

# Deliberately no attribution trailers: the trackers' commits are the
# deterministic output of their tools, with no AI authorship to attribute
# (AGENTS.md's trailers are for AI-authored commits). Do not re-add the
# Copilot trailer the old track-refs job carried.
git checkout --quiet -B "${branch}"
git -c user.name="github-actions[bot]" \
    -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
    commit --quiet -m "${title}"
push_auth=()
if [ -n "${GH_TOKEN:-}" ]; then
    push_auth=(-c "http.${GITHUB_SERVER_URL:-https://github.com}/.extraheader=AUTHORIZATION: basic $(printf 'x-access-token:%s' "${GH_TOKEN}" | base64 -w0)")
fi
git "${push_auth[@]}" push --quiet --force-with-lease="refs/heads/${branch}:${remote_head}" \
    "${remote}" "HEAD:refs/heads/${branch}"

if [ -n "${open}" ]; then
    gh pr edit "${open}" --title "${title}" --body-file "${body}"
    echo "Updated PR: $(gh pr view "${open}" --json url --jq '.url')"
else
    echo "Created PR: $(gh pr create --base "${base}" --head "${branch}" --title "${title}" --body-file "${body}")"
fi
