#!/usr/bin/env bash
# Key-free BuildStream cache of FSDK's kernel (and Go), stored in ghcr.io.
#
#   kernel-cache.sh key                    print the cache tag for this checkout
#   kernel-cache.sh seed    <repository>   build and push the tag unless it exists
#                                          and is attested; print its digest
#   kernel-cache.sh restore <repository>   pull the attested tag into
#                                          ~/.cache/buildstream; a missing,
#                                          unattested or failed pull is not an error
#
# The kernel is about 70 of the ~85 build minutes and no upstream cache holds
# it: its cache key depends on the module certificate it trusts (the
# linux-module-cert junction override) and on patches/freedesktop-sdk/0006.
# Both the seed job and release builds stage the committed release
# certificate files/release-keys/linux-module-cert.crt as
# files/boot-keys/modules/linux-module-cert.crt, so the keys match.
#
# The pushed tarball is public. It is key-free by construction: the seed job
# holds no signing secrets, and `seed` refuses to build if
# bluefin-server/keys/boot-keys.bst (the only element that stages private
# keys) is anywhere in the graph of ELEMENTS.
#
# The tarball feeds the release build: what `restore` extracts becomes the
# kernel inside the Secure Boot-signed UKI. The tag is mutable and anyone with
# write access to the package can replace it, so `restore` trusts a tag only
# after `gh attestation verify` finds a build-provenance attestation for its
# manifest digest from this repository's build workflow on main
# (actions/attest, kernel-cache job), and pulls that digest, not the tag.
# `seed` prints the pushed digest for the workflow to attest, and rebuilds
# and replaces a tag that exists without such an attestation.
set -euo pipefail

ELEMENTS=(freedesktop-sdk.bst:components/linux.bst freedesktop-sdk.bst:components/go.bst)
KEYS_ELEMENT=bluefin-server/keys/boot-keys.bst
ARTIFACT_TYPE=application/vnd.projectbluefin.server.bst-cache.v1
PART_SIZE=1900M
cache_dir="${HOME}/.cache/buildstream"
# The repository whose build workflow must have attested the cache. In CI
# GITHUB_REPOSITORY names the repository (so a fork trusts its own seeds).
ATTESTATION_REPO="${KERNEL_CACHE_ATTESTATION_REPO:-${GITHUB_REPOSITORY:-projectbluefin/server}}"
ATTESTATION_WORKFLOW="${ATTESTATION_REPO}/.github/workflows/build.yml"
ATTESTATION_REF=refs/heads/main

cd "$(dirname "$0")/.."

bst_show() {
    just bst show "$@" | sed 's/\x1b\[[0-9;]*m//g'
}

key() {
    local keys
    keys="$(bst_show --deps none --format "'%{full-key}'" "${ELEMENTS[@]}" | grep -xE '[0-9a-f]{64}' || true)"
    if [ "$(grep -c . <<< "${keys}")" -ne "${#ELEMENTS[@]}" ]; then
        echo "kernel-cache: could not read the cache keys of ${ELEMENTS[*]}" >&2
        exit 1
    fi
    printf 'kernel-%s\n' "$(sha256sum <<< "${keys}" | cut -c1-32)"
}

# Print the manifest digest of <repository>:<tag>, or fail if the tag does
# not resolve.
tag_digest() {
    local digest
    digest="$(oras manifest fetch --descriptor "$1:$2" 2>/dev/null | jq -r '.digest // empty')" || return 1
    [[ "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
    printf '%s\n' "${digest}"
}

# Print the manifest digest of <repository>:<tag> if this repository's build
# workflow on main attested it, or fail. gh needs GH_TOKEN or GITHUB_TOKEN.
attested_digest() {
    local repo="$1" tag="$2" digest
    digest="$(tag_digest "${repo}" "${tag}")" || return 1
    gh attestation verify "oci://${repo}@${digest}" \
        --repo "${ATTESTATION_REPO}" \
        --signer-workflow "${ATTESTATION_WORKFLOW}" \
        --source-ref "${ATTESTATION_REF}" \
        --predicate-type https://slsa.dev/provenance/v1 > /dev/null 2>&1 || return 1
    printf '%s\n' "${digest}"
}

# Hand <repository> and <digest> to the workflow's actions/attest step.
emit_digest() {
    if [ -n "${GITHUB_OUTPUT:-}" ]; then
        printf 'name=%s\ndigest=%s\n' "$1" "$2" >> "${GITHUB_OUTPUT}"
    fi
    echo "kernel-cache: digest ${2}"
}

seed() {
    local repo="$1" tag work digest
    tag="$(key)"
    if digest="$(attested_digest "${repo}" "${tag}")"; then
        echo "kernel-cache: ${repo}:${tag} already exists and is attested"
        emit_digest "${repo}" "${digest}"
        return 0
    fi
    if tag_digest "${repo}" "${tag}" > /dev/null; then
        echo "kernel-cache: ${repo}:${tag} exists without an attestation from ${ATTESTATION_WORKFLOW}@${ATTESTATION_REF}; rebuilding and replacing it"
    fi
    if bst_show --deps all --format "'%{name}'" "${ELEMENTS[@]}" | grep -qxF "${KEYS_ELEMENT}"; then
        echo "kernel-cache: ${KEYS_ELEMENT} is in the graph of ${ELEMENTS[*]}; refusing to publish" >&2
        exit 1
    fi
    just bst build "${ELEMENTS[@]}"
    # Inside the cache directory, on the same (large) disk, and left out of
    # the tarball with logs, build trees and temporary files.
    work="$(mktemp -d "${cache_dir}/kernel-cache.XXXXXX")"
    # The trailing slash descends into a symlinked cache (CI links it to /mnt).
    mapfile -t dirs < <(find "${cache_dir}/" -mindepth 1 -maxdepth 1 ! -name logs ! -name tmp ! -name build ! -name 'kernel-cache.*' -printf '%f\n')
    if [ "${#dirs[@]}" -eq 0 ] || [ ! -d "${cache_dir}/cas" ]; then
        echo "kernel-cache: nothing to pack in ${cache_dir}" >&2
        exit 1
    fi
    tar -C "${cache_dir}" -cf - "${dirs[@]}" | zstd -T0 -3 -q | split -b "${PART_SIZE}" - "${work}/cache.tar.zst."
    digest="$(cd "${work}" && oras push --format json --artifact-type "${ARTIFACT_TYPE}" "${repo}:${tag}" cache.tar.zst.* | jq -r '.digest // empty')"
    if ! [[ "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
        echo "kernel-cache: oras push did not report the digest of ${repo}:${tag}" >&2
        exit 1
    fi
    echo "kernel-cache: pushed ${repo}:${tag} ($(du -ch "${work}"/cache.tar.zst.* | tail -n1 | cut -f1))"
    rm -rf "${work}"
    emit_digest "${repo}" "${digest}"
}

restore() {
    local repo="$1" tag work digest
    tag="$(key)"
    mkdir -p "${cache_dir}"
    if ! digest="$(attested_digest "${repo}" "${tag}")"; then
        echo "::warning title=No kernel cache::${repo}:${tag} is not available or not attested by ${ATTESTATION_WORKFLOW}@${ATTESTATION_REF}; the kernel builds from source."
        return 0
    fi
    work="$(mktemp -d "${cache_dir}/kernel-cache.XXXXXX")"
    # Pull the attested digest, not the tag: the tag could move between
    # verification and pull.
    if ! oras pull -o "${work}" "${repo}@${digest}" > /dev/null; then
        rm -rf "${work}"
        echo "::warning title=No kernel cache::${repo}@${digest} could not be pulled; the kernel builds from source."
        return 0
    fi
    # Read the whole stream (zstd checksums, every tar header) before writing
    # anything: a half-extracted cache has artifact refs without their CAS
    # objects, which BuildStream takes as cached and fails on much later.
    if ! cat "${work}"/cache.tar.zst.* | zstd -dcq | tar -t > /dev/null; then
        rm -rf "${work}"
        echo "::warning title=Corrupt kernel cache::${repo}:${tag} did not verify; the kernel builds from source."
        return 0
    fi
    cat "${work}"/cache.tar.zst.* | zstd -dcq | tar -x -C "${cache_dir}/"
    rm -rf "${work}"
    echo "kernel-cache: restored ${repo}:${tag}"
}

case "${1:-}" in
    key) key ;;
    seed) seed "${2:?repository}" ;;
    restore) restore "${2:?repository}" ;;
    *) echo "usage: $0 key | seed <repository> | restore <repository>" >&2; exit 2 ;;
esac
