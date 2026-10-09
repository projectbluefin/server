#!/usr/bin/env bash
# Keep one open tracking issue per unattended workflow that nobody watches
# (the nightly build, the trackers): open it, or comment on the open one,
# when a run failed; close it when a later run passes.
#
#   tracking-issue.sh TITLE SUBJECT LATER
#
# FAILED=true|false and RUN_URL come from the environment; GH_TOKEN and
# GH_REPO authenticate `gh` and need issues: write only. SUBJECT names what
# failed ("The nightly build of main"), LATER what closes the issue ("a later
# nightly build"). The issue is found by its exact title.
set -euo pipefail

[ $# -eq 3 ] || { echo "usage: tracking-issue.sh TITLE SUBJECT LATER" >&2; exit 2; }
title="$1" subject="$2" later="$3"
: "${FAILED:?}" "${RUN_URL:?}"

issue="$(gh issue list --state open --limit 500 --json number,title \
    --jq "[.[] | select(.title == \"${title}\")][0].number // empty")"
if [ "${FAILED}" = true ]; then
    if [ -n "${issue}" ]; then
        gh issue comment "${issue}" --body "Failed again: ${RUN_URL}"
    else
        gh issue create --title "${title}" \
            --body "${subject} failed: ${RUN_URL}"$'\n\n'"This issue closes when ${later} passes."
    fi
elif [ -n "${issue}" ]; then
    gh issue close "${issue}" --comment "${subject} passes again: ${RUN_URL}"
fi
