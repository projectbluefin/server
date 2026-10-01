#!/usr/bin/env bash
# Key-free BuildStream cache of FSDK's kernel (and Go), stored in ghcr.io.
#
#   kernel-cache.sh key                    print the cache tag for this checkout
#   kernel-cache.sh seed    <repository>   build and push the tag unless it exists
#   kernel-cache.sh restore <repository>   pull the tag into ~/.cache/buildstream;
#                                          a missing tag or failed pull is not an error
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
set -euo pipefail

ELEMENTS=(freedesktop-sdk.bst:components/linux.bst freedesktop-sdk.bst:components/go.bst)
KEYS_ELEMENT=bluefin-server/keys/boot-keys.bst
ARTIFACT_TYPE=application/vnd.projectbluefin.server.bst-cache.v1
PART_SIZE=1900M
cache_dir="${HOME}/.cache/buildstream"

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

seed() {
    local repo="$1" tag work
    tag="$(key)"
    if oras manifest fetch "${repo}:${tag}" > /dev/null 2>&1; then
        echo "kernel-cache: ${repo}:${tag} already exists"
        return 0
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
    (cd "${work}" && oras push --artifact-type "${ARTIFACT_TYPE}" "${repo}:${tag}" cache.tar.zst.*)
    echo "kernel-cache: pushed ${repo}:${tag} ($(du -ch "${work}"/cache.tar.zst.* | tail -n1 | cut -f1))"
    rm -rf "${work}"
}

restore() {
    local repo="$1" tag work
    tag="$(key)"
    mkdir -p "${cache_dir}"
    work="$(mktemp -d "${cache_dir}/kernel-cache.XXXXXX")"
    if ! oras pull -o "${work}" "${repo}:${tag}" > /dev/null; then
        rm -rf "${work}"
        echo "::warning title=No kernel cache::${repo}:${tag} is not available; the kernel builds from source."
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
