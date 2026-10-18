#!/usr/bin/env bash
# Fail in seconds, before the image build, when the runner lacks something the
# boot test needs: a host tool its dogfood scripts run (#486 found
# `mcopy: command not found` only after a 2 h build), the OVMF firmware, or a
# usable /dev/kvm. build.yml's boot-test-preflight job runs it after
# scripts/ci/install-qemu-ovmf.sh, as every boot-test bucket does.
#
#   bash scripts/ci/dogfood-preflight.sh           check
#   bash scripts/ci/dogfood-preflight.sh --tools   print the host tools
#
# The scanned scripts are the dogfood scripts scripts/ci/boot-test.sh runs,
# and those they run in turn. Every name the `watch` pattern matches on their
# non-comment lines must be listed in host_tools (each checked with
# command -v) or in not_on_host, so a script that starts running a new tool
# fails here until it is listed. PREFLIGHT_KVM overrides /dev/kvm (tests).
set -euo pipefail
export LC_ALL=C

# Read from the three scripts boot-test.sh runs; package in parentheses.
host_tools=(
    bash python3                 # the harness; http.server, QMP over a socket
    qemu-system-x86_64           # (qemu-system-x86)
    mcopy                        # (mtools) the installer stick's loader.conf
    sfdisk blkid mkswap          # (fdisk, util-linux) the foreign-gpt target disk
    mkfs.vfat mkfs.ext4          # (dosfstools, e2fsprogs) the same
    gpg                          # (gnupg) the foreign-signed update source
    sha256sum base64 dd od truncate realpath mktemp awk
)
# Matched, but never run on the runner.
not_on_host=(
    veritysetup                  # dogfood-diskless.sh's guest probe
    gpgv                         # a log prefix that probe filters out
    mkfs.xfs                     # DOGFOOD_TARGET=xfs only, which CI does not run
)
watch='\b(qemu-[a-z0-9_-]+|m(copy|dir|type|md|format|del)|bsdtar|sgdisk|sfdisk|mkfs\.[a-z0-9]+|mkswap|blkid|losetup|veritysetup|cryptsetup|objcopy|ukify|zstd|cpio|gpg[a-z]*|openssl|python3|sha256sum|socat|curl|swtpm|jq)\b'

if [ "${1:-}" = --tools ]; then printf '%s\n' "${host_tools[@]}"; exit 0; fi
[ "$#" = 0 ] || { echo "usage: $0 [--tools]" >&2; exit 2; }

here="${BASH_SOURCE[0]%/*}"
scripts_dir="${here}/.."
errors=0
error() { echo "::error title=boot-test preflight::$*"; errors=$((errors + 1)); }
code() { grep -hvE '^[[:space:]]*#' "$@"; }
listed() { local t="$1"; shift; [[ " $* " == *" ${t} "* ]]; }

scanned=()
queue=("${here}/boot-test.sh")
while [ "${#queue[@]}" -gt 0 ]; do
    file="${queue[0]}"
    queue=("${queue[@]:1}")
    for name in $(code "${file}" | grep -oE 'dogfood-[a-z-]+\.sh' | sort -u); do
        listed "${name}" "${scanned[@]##*/}" && continue
        [ -f "${scripts_dir}/${name}" ] || { error "${file##*/} runs ${name}, which does not exist"; continue; }
        scanned+=("${scripts_dir}/${name}")
        queue+=("${scripts_dir}/${name}")
    done
done
[ "${#scanned[@]}" -gt 0 ] || error "found no dogfood script in ${here}/boot-test.sh"
echo "Scanned: ${scanned[*]##*/}"

for tool in $(code "${scanned[@]}" | grep -ohE "${watch}" | sort -u); do
    listed "${tool}" "${host_tools[@]}" "${not_on_host[@]}" \
        || error "the dogfood scripts run ${tool}, which is in neither host_tools nor not_on_host of ${BASH_SOURCE[0]}"
done

for tool in "${host_tools[@]}"; do
    command -v "${tool}" >/dev/null || error "${tool}: command not found (add its package to scripts/ci/install-qemu-ovmf.sh)"
done

for var in OVMF_CODE OVMF_CODE_INSECURE OVMF_VARS; do
    [ -s "${!var:-}" ] || error "${var} is not set to a firmware file (scripts/ci/install-qemu-ovmf.sh sets it)"
done

kvm="${PREFLIGHT_KVM:-/dev/kvm}"
{ [ -r "${kvm}" ] && [ -w "${kvm}" ]; } || error "${kvm} is not read-writable: QEMU would run without KVM"

[ "${errors}" = 0 ] || exit 1
echo "Host tools present: ${host_tools[*]}"
