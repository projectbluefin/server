#!/usr/bin/env bash
# Publish one Bluefin Server release set (dist/diskless/), or rehearse it.
#
#   publish-release.sh verify   DIR VERSION KEYRING
#   publish-release.sh taggable VERSION
#   publish-release.sh release  DIR VERSION [--dry-run]
#   publish-release.sh oci      DIR VERSION REF [--plain-http] [--pull-back]
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

# `latest` never moves backwards: a re-run of an older release must not
# repoint it. True when VERSION sorts at or above CURRENT (or there is no
# CURRENT yet). sort -V orders YY.MM.<run> versions as strverscmp() does.
is_newest() {
    local ver="$1" current="$2"
    [ -z "${current}" ] || [ "$(printf '%s\n' "${current}" "${ver}" | sort -V | tail -n1)" = "${ver}" ]
}

# The highest version published as a GitHub Release of REPO, or nothing.
newest_github_release() {
    local tags
    tags="$(gh release list --repo "$1" --exclude-drafts --exclude-pre-releases \
        --limit 1000 --json tagName --jq '.[].tagName')" \
        || die "cannot list the releases of $1"
    sed -n 's/^v\([0-9]\)/\1/p' <<<"${tags}" | sort -V | tail -n1
}

# The version REF:latest carries (its org.opencontainers.image.version
# annotation), or nothing when there is no latest yet. Other errors abort.
oci_latest_version() {
    local ref="$1" manifest err version
    shift
    err="$(mktemp)"
    if ! manifest="$(oras manifest fetch "$@" "${ref}:latest" 2>"${err}")"; then
        if grep -q ': not found' "${err}"; then
            rm -f "${err}"
            return 0
        fi
        cat "${err}" >&2
        rm -f "${err}"
        die "cannot read ${ref}:latest"
    fi
    rm -f "${err}"
    version="$(jq -r '.annotations["org.opencontainers.image.version"] // empty' <<<"${manifest}")"
    [ -n "${version}" ] || die "${ref}:latest has no org.opencontainers.image.version annotation"
    echo "${version}"
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
        "homelab_${v}\\.raw\\.zst" \
        "argo-workflows_${v}\\.raw\\.zst" \
        "mcp_${v}\\.raw\\.zst" \
        "nvidia-open-595_${v}\\.raw\\.zst" \
        "k0s-[0-9][0-9A-Za-z.+-]*\\.raw\\.zst" \
        "nvidia-container-toolkit-[0-9][0-9A-Za-z.+-]*\\.raw\\.zst"
    # The homelab Ignition templates: unversioned, so that
    # releases/latest/download/<name> always names the newest.
    local t
    for t in homelab-control-plane homelab-node homelab-k0s-control-plane homelab-k0s-node; do
        printf '%s\\.bu\n%s\\.ign\n' "${t}" "${t}"
    done
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

# GITHUB_TOKEN cannot create a tag (gh release create, the refs API or a git
# push) at a commit whose copy of the running workflow file differs from the
# default branch's: that needs the workflows permission, which GITHUB_TOKEN
# never has. Runs on main queue, so a merge that edits the workflow can land
# before an earlier run publishes. Its content ships with the newer run under
# that run's version; this version is skipped with a warning (publish=false)
# instead of failing with HTTP 403.
cmd_taggable() {
    [ $# -eq 1 ] || die "usage: taggable VERSION"
    local ver="$1"
    check_version "${ver}"
    [ -n "${GITHUB_WORKFLOW_REF:-}" ] || die "GITHUB_WORKFLOW_REF is not set"
    local sha="${GITHUB_SHA:-$(git rev-parse HEAD)}"
    local repo="${GITHUB_REPOSITORY:-projectbluefin/server}"
    # <owner>/<repo>/.github/workflows/<file>@<ref>
    local workflow="${GITHUB_WORKFLOW_REF%@*}"
    workflow=".github/${workflow#*/.github/}"

    local ours theirs
    ours="$(git rev-parse --verify --quiet "${sha}:${workflow}")" \
        || die "${workflow} not found at ${sha}"
    theirs="$(gh api "repos/${repo}/contents/${workflow}" --jq .sha)" \
        || die "cannot read ${workflow} on the default branch of ${repo}"
    [[ "${theirs}" =~ ^[0-9a-f]{40}$ ]] || die "unexpected blob id for ${workflow}: ${theirs}"

    if [ "${ours}" = "${theirs}" ]; then
        echo "${workflow} at ${sha} matches the default branch: v${ver} can be tagged"
        output publish true
        return
    fi
    local msg="v${ver} is not published: ${workflow} changed on the default branch after ${sha}, and GITHUB_TOKEN may not tag a commit whose running workflow differs from the default branch. The run for the newer commit publishes this content."
    echo "::warning title=Release skipped::${msg}"
    if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
        echo "${msg}" >> "${GITHUB_STEP_SUMMARY}"
    fi
    output publish false
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

    local repo="${GITHUB_REPOSITORY:-projectbluefin/server}"
    local source="${GITHUB_SERVER_URL:-https://github.com}/${repo}"
    local docs="${source}/blob/${sha}/docs/skills"
    local notes
    notes="$(cat <<EOF
Image ${ver} built from [${sha}](${source}/commit/${sha}).

## Install from a USB stick

Download **bluefin-server-installer_${ver}.raw** from the assets below for an
offline installation. On Linux, with curl and GNU coreutils installed:

\`\`\`bash
mkdir -p bluefin-server-${ver}
cd bluefin-server-${ver}
curl -fLO '${source}/releases/download/v${ver}/bluefin-server-installer_${ver}.raw'
curl -fLO '${source}/releases/download/v${ver}/SHA256SUMS'
sha256sum --check --ignore-missing SHA256SUMS
lsblk -o NAME,SIZE,MODEL,TRAN,MOUNTPOINTS
\`\`\`

Continue only if the installer checksum says **OK**. Checksums detect download
corruption; see [signature verification](${docs}/systemd-sysupdate-verification.md)
for the signed manifest and trusted keyring.

**Writing the image erases the entire USB stick.** Identify it by size and model
in \`lsblk\`, unmount its mounted partitions, and replace \`/dev/<usb>\` below with
its whole-disk device (not a partition):

\`\`\`bash
sudo dd if=bluefin-server-installer_${ver}.raw of=/dev/<usb> bs=4M conv=fsync status=progress
\`\`\`

Boot the stick in UEFI mode and follow the on-screen installer. **The selected
target disk is erased too.** Remove the stick when the machine reboots, then set
a non-empty root password at first boot. For Secure Boot setup, disk selection,
Homelab boot entries and provisioning, read the [USB installer guide](${docs}/usb-installer.md).

## Which asset do I need?

In the names below, \`<ver>\` is \`${ver}\` and \`<uuid>\` identifies a partition.

| Asset | Purpose |
| --- | --- |
| \`bluefin-server-installer_<ver>.raw\` | Offline USB installer; write this to your stick. |
| \`bluefin-server_<ver>.raw\` | OS discoverable disk image (DDI); pulled into RAM for diskless boot and used as its installation payload. |
| \`bluefin-server-netboot_<ver>.efi\` | Signed netboot unified kernel image (UKI) for UEFI HTTP/PXE boot; downloads the OS DDI. |
| \`bluefin-server-netboot_<ver>.esp.raw\` | Netboot EFI System Partition image with systemd-boot and Secure Boot enrollment payloads; requires network access to the OS DDI. |
| \`bluefin-server-<ver>.efi\` | Signed disk UKI for installed nodes and OS updates. |
| \`bluefin-server_<ver>_<uuid>.usr.raw\`, \`*.usr-verity.raw\` | The /usr partition and its verification data, consumed by systemd-sysupdate for A/B updates. |
| \`kubeadm_<ver>.raw.zst\`, \`k0s-<k0s-version>.raw.zst\` | Optional Kubernetes systemd-sysext images (kubeadm or k0s). |
| \`homelab_<ver>.raw.zst\` | Optional homelab cluster tooling extension. |
| \`argo-workflows_<ver>.raw.zst\`, \`mcp_<ver>.raw.zst\`, \`kubestellar_<ver>.raw.zst\` | Optional homelab extensions: Argo Workflows, MCP server and KubeStellar Console. |
| \`zfs_<ver>.raw.zst\` | Optional OpenZFS extension. |
| \`nvidia-open-595_<ver>.raw.zst\`, \`nvidia-container-toolkit-<toolkit-version>.raw.zst\` | Optional NVIDIA open kernel modules and Container Toolkit extensions. |
| \`homelab-*.bu\`, \`homelab-*.ign\` | Editable Butane YAML and rendered Ignition JSON provisioning templates for control-plane/node roles, with kubeadm or k0s. Customise before use. |
| \`bluefin-server_<ver>.spdx.json\` | SPDX software bill of materials (SBOM), listing the image's components. |
| \`SHA256SUMS\`, \`SHA256SUMS.gpg\` | Release asset checksums and their detached signature. |
| GitHub's \`Source code\` archives | Repository source for developers; not bootable images. |

See the [boot and install guide](${docs}/ddi-installer.md),
[extension guide](${docs}/systemd-sysext-extensions.md) and
[homelab guide](${docs}/homelab-profile.md) for other deployment options.
EOF
)"

    # GitHub's own choice of "Latest" goes by creation date, and
    # releases/latest/download/ must never step back to an older version.
    local newest latest=--latest=false
    newest="$(newest_github_release "${repo}")"
    if is_newest "${ver}" "${newest}"; then
        latest=--latest
    else
        echo "::notice title=Not the latest release::v${ver} is older than v${newest}, which stays Latest"
    fi

    # A version is published exactly once: gh refuses an existing tag, so
    # assets nodes may already trust are never overwritten.
    local cmd=(gh release create "v${ver}" --target "${sha}"
        --title "Bluefin Server ${ver}"
        "${latest}"
        --notes "${notes}"
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

    local current tags="${ver}" newest=false
    current="$(oci_latest_version "${ref}" "${flags[@]}")"
    if is_newest "${ver}" "${current}"; then
        tags="${ver},latest"
        newest=true
    else
        echo "::notice title=latest not moved::${ref}:latest stays at ${current}, newer than ${ver}"
    fi

    (cd "${dir}" && oras push "${flags[@]}" \
        --artifact-type "${ARTIFACT_TYPE}" \
        --annotation "org.opencontainers.image.version=${ver}" \
        --annotation "org.opencontainers.image.source=${source}" \
        --annotation "org.opencontainers.image.revision=${GITHUB_SHA:-$(git rev-parse HEAD)}" \
        "${ref}:${tags}" "${files[@]}")

    local digest latest
    digest="$(oras resolve "${flags[@]}" "${ref}:${ver}")"
    if [ "${newest}" = true ]; then
        latest="$(oras resolve "${flags[@]}" "${ref}:latest")"
        [ "${digest}" = "${latest}" ] || die "${ref}:latest is ${latest}, not ${digest}"
    fi

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
    output latest "${newest}"
}

sub="${1:-}"
[ $# -gt 0 ] && shift
case "${sub}" in
    verify) cmd_verify "$@" ;;
    taggable) cmd_taggable "$@" ;;
    release) cmd_release "$@" ;;
    oci) cmd_oci "$@" ;;
    *) die "usage: $0 verify|taggable|release|oci ..." ;;
esac
