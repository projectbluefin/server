#!/usr/bin/env bash
# Check the Ignition config keyring staged for a build: the initrd verifies a
# network-booted node's bluefin-node.ign.gpg against it alone, so it must be
# there and must share no key with the release keyring (import-pubring.pgp,
# which authenticates SHA256SUMS). Otherwise a release signature
# (SHA256SUMS.gpg over SHA256SUMS) would verify as a node config, and whoever
# signs node configs could sign release manifests.
#
#   check-ignition-keys.sh [--release] [KEY_DIR]    (default: files/boot-keys)
#
# --release also requires the keyring to be exactly the committed
# files/release-keys/ignition-pubring.pgp, and no Ignition secret key in
# KEY_DIR: the config signing key never enters a build.
#
# A relative KEY_DIR is resolved against the repository root.
set -euo pipefail

cd "$(dirname "$0")/.."
release=0
if [ "${1:-}" = --release ]; then
    release=1
    shift
fi
dir="${1:-files/boot-keys}"
committed=files/release-keys/ignition-pubring.pgp

die() { echo "check-ignition-keys: $*" >&2; exit 1; }

gnupghome="$(mktemp -d)"
trap 'rm -rf "${gnupghome}"' EXIT
fingerprints() {
    GNUPGHOME="${gnupghome}" gpg --batch --with-colons --show-keys "$1" 2>/dev/null \
        | awk -F: '$1 == "fpr" { print $10 }' | sort -u
}

ring="${dir}/ignition-pubring.pgp"
[ -s "${ring}" ] || die "missing ${ring} (just gen-dev-keys; release builds copy ${committed})"
ignition_fprs="$(fingerprints "${ring}")"
[ -n "${ignition_fprs}" ] || die "${ring} holds no OpenPGP key"

import_ring="${dir}/import-pubring.pgp"
[ -s "${import_ring}" ] || die "missing ${import_ring}"
shared="$(comm -12 <(printf '%s\n' "${ignition_fprs}") <(fingerprints "${import_ring}"))"
[ -z "${shared}" ] \
    || die "${ring} and ${import_ring} share keys (${shared//$'\n'/ }); the Ignition config key must not be a release key"

if [ "${release}" = 1 ]; then
    [ -s "${committed}" ] || die "missing ${committed}; release builds trust only the committed Ignition config keyring"
    cmp -s "${ring}" "${committed}" || die "${ring} is not ${committed}"
    [ ! -e "${dir}/ignition-signing.asc" ] \
        || die "${dir}/ignition-signing.asc: the Ignition config signing key must never be part of a release build"
fi
echo "check-ignition-keys: ${ring} holds $(printf '%s\n' "${ignition_fprs}" | wc -l) key(s), none in ${import_ring}"
