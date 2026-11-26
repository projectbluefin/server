#!/usr/bin/env bash
# Run a command, trying again when it fails: for CI steps that fetch from the
# network (apt mirrors, GitHub release downloads), where one dropped
# connection or 5xx is not a failed build.
#
#   bash scripts/ci/retry.sh [-n ATTEMPTS] COMMAND [ARGS...]
#
# ATTEMPTS defaults to 3. Between attempts it waits RETRY_DELAY seconds
# (default 15) times the attempt number. It exits with the command's own
# status after the last attempt. Do not wrap a command that is not safe to
# run twice (one that publishes, or that a partial run leaves half done).
#
# apt-get is wrapped here because Acquire::Retries does not retry an HTTP
# 503 on an index (measured on Ubuntu 26.04 against a server that always
# answered 503: the same 9 requests with Acquire::Retries=0 and =3).
set -euo pipefail

attempts=3
if [ "${1:-}" = -n ]; then
    attempts="${2:?usage: retry.sh [-n ATTEMPTS] COMMAND [ARGS...]}"
    shift 2
fi
[[ "${attempts}" =~ ^[1-9][0-9]*$ ]] || { echo "retry.sh: ATTEMPTS must be a positive number" >&2; exit 2; }
[ $# -gt 0 ] || { echo "usage: retry.sh [-n ATTEMPTS] COMMAND [ARGS...]" >&2; exit 2; }

n=1
while true; do
    rc=0
    "$@" || rc=$?
    [ "${rc}" -ne 0 ] || exit 0
    if [ "${n}" -ge "${attempts}" ]; then
        echo "::error::$1 failed after ${attempts} attempts (exit ${rc})" >&2
        exit "${rc}"
    fi
    echo "::warning title=Retrying::$* failed (exit ${rc}), attempt ${n} of ${attempts}" >&2
    sleep $(( ${RETRY_DELAY:-15} * n ))
    n=$(( n + 1 ))
done
