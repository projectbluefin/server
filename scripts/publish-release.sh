#!/usr/bin/env bash
# Publish one Bluefin Server release set (dist/diskless/), or rehearse it.
#
#   publish-release.sh verify  DIR VERSION KEYRING
#   publish-release.sh release DIR VERSION [--dry-run]
#   publish-release.sh oci     DIR VERSION REF [--plain-http] [--pull-back]
#
# .github/workflows/build.yml runs these same commands in the `release` job
# on main and in the `release-dry-run` job on every pull request. The dry
# run only prints the `gh release create` command, and pushes the OCI
# artifact to a throwaway local registry and pulls it back.
#
# A release publishes the top-level files of DIR: the ones SHA256SUMS lists,
# plus SHA256SUMS and SHA256SUMS.gpg. Subdirectories (efi-keys/,
# sysupdate-keys/) stay local.
set -euo pipefail

ARTIFACT_TYPE=application/vnd.projectbluefin.server.release.v1
TITLE_KEY=org.opencontainers.image.title

die() { echo "publish-release: $*" >&2; exit 1; }

# Top-level regular files of DIR, sorted: exactly what a release publishes.
published_files() {
    find "$1" -mindepth 1 -maxdepth 1 -type f -printf '%f\n' | LC_ALL=C sort
}

# "<sha256> <name>" for every published file, from the verified SHA256SUMS
# plus the two files it cannot list itself.
published_digests() {
    {
        sed -E 's/^([0-9a-f]{64}) [ *]/\1 /' "$1/SHA256SUMS"
        (cd "$1" && sha256sum SHA256SUMS SHA256SUMS.gpg) | sed -E 's/  / /'
    } | LC_ALL=C sort -k2
}

output() {
    echo "$1=$2"
    if [ -n "${GITHUB_OUTPUT:-}" ]; then
        echo "$1=$2" >> "${GITHUB_OUTPUT}"
    fi
}

check_version() {
    [[ "$1" =~ ^[0-9][0-9A-Za-z.]{0,16}$ ]] || die "invalid version: $1"
}

# The file names one image version ships (see the description of
# elements/oci/bluefin-server-image.bst). Each must appear exactly once;
# k0s and the NVIDIA Container Toolkit carry their own version axis.
expected_patterns() {
    local v="${1//./\\.}"
    local uuid='[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    printf '%s\n' \
        "bluefin-server_${v}\\.raw" \
        "bluefin-server_${v}_${uuid}\\.usr\\.raw" \
        "bluefin-server_${v}_${uuid}\\.usr-verity\\.raw" \
        "bluefin-server-${v}\\.efi" \
        "bluefin-server-netboot_${v}\\.efi" \
        "bluefin-server-netboot_${v}\\.esp\\.raw" \
        "bluefin-server-installer_${v}\\.raw" \
        "bluefin-server_${v}\\.spdx\\.json" \
        "zfs_${v}\\.raw\\.zst" \
        "kubestellar_${v}\\.raw\\.zst" \
        "kubeadm_${v}\\.raw\\.zst" \
        "nvidia-open-595_${v}\\.raw\\.zst" \
        "k0s-[0-9][0-9A-Za-z.+-]*\\.raw\\.zst" \
        "nvidia-container-toolkit-[0-9][0-9A-Za-z.+-]*\\.raw\\.zst"
}

cmd_verify() {
    [ $# -eq 3 ] || die "usage: verify DIR VERSION KEYRING"
    local dir="$1" ver="$2" keyring
    check_version "${ver}"
    [ -d "${dir}" ] || die "no such directory: ${dir}"
    keyring="$(realpath -e "$3")" || die "no such keyring: $3"
    [ -f "${dir}/SHA256SUMS" ] || die "missing SHA256SUMS"
    [ -f "${dir}/SHA256SUMS.gpg" ] || die "missing SHA256SUMS.gpg"

    # The same check systemd-sysupdate and systemd-importd make on nodes.
    gpgv --keyring "${keyring}" "${dir}/SHA256SUMS.gpg" "${dir}/SHA256SUMS" \
        || die "SHA256SUMS.gpg does not verify against ${keyring}"

    local line name listed=()
    while IFS= read -r line; do
        [[ "${line}" =~ ^[0-9a-f]{64}\ [\ *]([^/]+)$ ]] \
            || die "malformed SHA256SUMS line: ${line}"
        name="${BASH_REMATCH[1]}"
        [ -f "${dir}/${name}" ] || die "listed in SHA256SUMS but missing: ${name}"
        listed+=("${name}")
    done < "${dir}/SHA256SUMS"
    [ "${#listed[@]}" -gt 0 ] || die "SHA256SUMS is empty"

    local dup
    dup="$(printf '%s\n' "${listed[@]}" | LC_ALL=C sort | uniq -d)"
    [ -z "${dup}" ] || die "listed more than once in SHA256SUMS: ${dup}"

    (cd "${dir}" && sha256sum --check --strict --quiet SHA256SUMS) \
        || die "checksum mismatch"

    # Everything a release would publish is covered by the signature.
    local unsigned
    unsigned="$(LC_ALL=C comm -23 \
        <(published_files "${dir}" | grep -vxE 'SHA256SUMS(\.gpg)?') \
        <(printf '%s\n' "${listed[@]}" | LC_ALL=C sort))"
    [ -z "${unsigned}" ] || die "not covered by SHA256SUMS: ${unsigned//$'\n'/ }"

    local pattern count
    for name in "${listed[@]}"; do
        grep -qxEf <(expected_patterns "${ver}") <<<"${name}" \
            || die "${name} is not a file of release ${ver}"
    done
    while IFS= read -r pattern; do
        count="$(printf '%s\n' "${listed[@]}" | grep -cxE "${pattern}" || true)"
        [ "${count}" -eq 1 ] \
            || die "release ${ver} needs exactly one file matching ${pattern}, found ${count}"
    done < <(expected_patterns "${ver}")

    # What actions/attest needs to accept it as an SPDX SBOM.
    local sbom="${dir}/bluefin-server_${ver}.spdx.json"
    jq -e '.spdxVersion == "SPDX-2.3" and (.packages | length > 0)
        and ([.packages[].SPDXID] | length == (unique | length))
        and (.creationInfo.created | type == "string")' "${sbom}" >/dev/null \
        || die "$(basename "${sbom}") is not an SPDX 2.3 document with unique packages and a creation time"

    # Attestation subjects: every published file (sha256sum format).
    local subjects="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/release-subjects-${ver}.sha256"
    published_digests "${dir}" | sed 's/ /  /' > "${subjects}"
    echo "release set ${ver}: ${#listed[@]} files match SHA256SUMS, signature verified"
    output subjects "${subjects}"
}

cmd_release() {
    [ $# -ge 2 ] || die "usage: release DIR VERSION [--dry-run]"
    local dir="$1" ver="$2" dry=0
    shift 2
    case "${1:-}" in
        --dry-run) dry=1 ;;
        "") ;;
        *) die "unknown option: $1" ;;
    esac
    check_version "${ver}"
    local sha="${GITHUB_SHA:-$(git rev-parse HEAD)}"
    local files=()
    mapfile -t files < <(published_files "${dir}" | sed "s|^|${dir%/}/|")
    [ "${#files[@]}" -gt 0 ] || die "nothing to publish in ${dir}"

    # A version is published exactly once: gh refuses an existing tag, so
    # assets nodes may already trust are never overwritten.
    local cmd=(gh release create "v${ver}" --target "${sha}"
        --title "Bluefin Server ${ver}"
        --notes "Image ${ver} built from ${sha}."
        "${files[@]}")
    if [ "${dry}" = 1 ]; then
        echo "dry run, would run:"
        printf '%q ' "${cmd[@]}"
        echo
    else
        "${cmd[@]}"
    fi
}

cmd_oci() {
    [ $# -ge 3 ] || die "usage: oci DIR VERSION REF [--plain-http] [--pull-back]"
    local dir="$1" ver="$2" ref="$3" pull_back=0 flags=()
    shift 3
    while [ $# -gt 0 ]; do
        case "$1" in
            --plain-http) flags+=(--plain-http) ;;
            --pull-back) pull_back=1 ;;
            *) die "unknown option: $1" ;;
        esac
        shift
    done
    check_version "${ver}"
    local source="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-projectbluefin/server}"
    local files=()
    mapfile -t files < <(published_files "${dir}")

    (cd "${dir}" && oras push "${flags[@]}" \
        --artifact-type "${ARTIFACT_TYPE}" \
        --annotation "org.opencontainers.image.version=${ver}" \
        --annotation "org.opencontainers.image.source=${source}" \
        --annotation "org.opencontainers.image.revision=${GITHUB_SHA:-$(git rev-parse HEAD)}" \
        "${ref}:${ver},latest" "${files[@]}")

    local digest latest
    digest="$(oras resolve "${flags[@]}" "${ref}:${ver}")"
    latest="$(oras resolve "${flags[@]}" "${ref}:latest")"
    [ "${digest}" = "${latest}" ] || die "${ref}:latest is ${latest}, not ${digest}"

    # The registry holds exactly the published files, byte for byte.
    diff -u <(published_digests "${dir}") \
        <(oras manifest fetch "${flags[@]}" "${ref}@${digest}" \
            | jq -r --arg k "${TITLE_KEY}" '.layers[] | "\(.digest | ltrimstr("sha256:")) \(.annotations[$k])"' \
            | LC_ALL=C sort -k2) \
        || die "${ref}@${digest} does not match ${dir}"

    if [ "${pull_back}" = 1 ]; then
        local tmp
        tmp="$(mktemp -d)"
        # shellcheck disable=SC2064
        trap "rm -rf '${tmp}'" EXIT
        oras pull "${flags[@]}" -o "${tmp}" "${ref}@${digest}"
        diff -u <(published_files "${dir}") <(published_files "${tmp}") \
            || die "pulled file list differs"
        (cd "${tmp}" && sha256sum --check --strict --quiet SHA256SUMS) \
            || die "pulled files do not match SHA256SUMS"
        cmp "${dir}/SHA256SUMS.gpg" "${tmp}/SHA256SUMS.gpg" \
            || die "pulled SHA256SUMS.gpg differs"
        echo "pulled ${ref}@${digest} back: ${#files[@]} files match"
    fi

    output name "${ref}"
    output digest "${digest}"
}

sub="${1:-}"
[ $# -gt 0 ] && shift
case "${sub}" in
    verify) cmd_verify "$@" ;;
    release) cmd_release "$@" ;;
    oci) cmd_oci "$@" ;;
    *) die "usage: $0 verify|release|oci ..." ;;
esac
