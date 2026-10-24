#!/usr/bin/env bash
# The boot test's QEMU scenarios, in buckets that build.yml's boot-test job
# runs as a matrix, one runner each. Each scenario is one dogfood script call
# with its DOGFOOD_* settings; a bucket runs its scenarios in order and stops
# at the first failure, so that scenario's logs are the ones uploaded.
# Buckets are balanced by duration (figures in docs/skills/ci-tooling.md).
#
#   bash scripts/ci/boot-test.sh <bucket>          run a bucket
#   bash scripts/ci/boot-test.sh --list [<bucket>] print its calls, run nothing
#   bash scripts/ci/boot-test.sh --buckets         print the bucket names
#
# RELEASE=true selects the release scenarios: a release build exports no
# next/broken sets or Ignition signatures, so the update and signed-config
# scenarios run only outside releases. Expects in dist/ the parts of the
# image sets its bucket's scenarios read; build.yml's boot-test matrix lists
# which artifacts each bucket downloads.
set -euo pipefail

buckets=(diskless install installer installer-disks)
release="${RELEASE:-false}"
list=false

# scenario <name> [VAR=value ...] -- <script> [<arg> ...]
scenario() {
    local name="$1" envs=()
    shift
    while [ "$1" != -- ]; do envs+=("$1"); shift; done
    shift
    if [ "${list}" = true ]; then
        printf '%s:' "${name}"
        printf ' %q' "${envs[@]}" bash "$@"
        printf '\n'
        return
    fi
    echo "::group::${name}"
    if ! env "${envs[@]}" bash "$@"; then
        echo "::endgroup::"
        echo "::error title=boot-test (${bucket})::${name} failed"
        exit 1
    fi
    echo "::endgroup::"
}

ignition_probe=(DOGFOOD_EXTRA_PROBE=tests/fixtures/ignition/apply-marker.probe
    "DOGFOOD_EXPECT=PROBE ignition marker=applied unit=active enabled=enabled ran=yes")
config_refusal="DOGFOOD_REFUSAL=bluefin-node.ign.gpg does not verify against /usr/lib/bluefin/ignition-pubring.pgp"

# Diskless boots: network pull, dm-verity /usr, refusal of a tampered image
# or manifest, Ignition, UEFI HTTP boot and the Ignition config gate (#327).
bucket_diskless() {
    scenario "Diskless boot" \
        DOGFOOD_EXTRA_PROBE=tests/fixtures/nfs/netdb.probe \
        "DOGFOOD_EXPECT=PROBE netdb protocols=0 services=0 rpcinfo=0 nfs3-tcp=resolved " \
        -- scripts/dogfood-diskless.sh dist/diskless --check
    scenario "Refuse a tampered image" DOGFOOD_TAMPER=raw \
        -- scripts/dogfood-diskless.sh dist/diskless --check
    scenario "Refuse an unsigned manifest" DOGFOOD_TAMPER=sums \
        -- scripts/dogfood-diskless.sh dist/diskless --check
    scenario "Ignition config from a credential" \
        DOGFOOD_IGNITION=tests/fixtures/ignition/apply-marker.ign "${ignition_probe[@]}" \
        -- scripts/dogfood-diskless.sh dist/diskless --check
    scenario "UEFI HTTP boot with bluefin-node.ign" \
        DOGFOOD_BOOT=http DOGFOOD_NODE_IGN=tests/fixtures/ignition/apply-marker.ign "${ignition_probe[@]}" \
        -- scripts/dogfood-diskless.sh dist/diskless --check
    [ "${release}" != true ] || return 0
    # Only the Ignition config key vouches for bluefin-node.ign; a refusal
    # fails the boot closed.
    scenario "UEFI HTTP boot with a bluefin-node.ign signed with the Ignition config key" \
        DOGFOOD_BOOT=http DOGFOOD_NODE_IGN=tests/fixtures/ignition/apply-marker.ign \
        DOGFOOD_NODE_IGN_SIG=dist/ignition-sigs/apply-marker.ign.config.gpg "${ignition_probe[@]}" \
        -- scripts/dogfood-diskless.sh dist/diskless --check
    scenario "Refuse a bluefin-node.ign signed with the image signing key" \
        DOGFOOD_BOOT=http DOGFOOD_NODE_IGN=tests/fixtures/ignition/apply-marker.ign \
        DOGFOOD_NODE_IGN_SIG=dist/ignition-sigs/apply-marker.ign.release.gpg "${config_refusal}" \
        "DOGFOOD_EXPECT=gpgv: Can't check signature: No public key" \
        -- scripts/dogfood-diskless.sh dist/diskless --check
    scenario "Refuse a bluefin-node.ign with a bad signature" \
        DOGFOOD_BOOT=http DOGFOOD_NODE_IGN=tests/fixtures/ignition/var-on-disk.ign \
        DOGFOOD_NODE_IGN_SIG=dist/ignition-sigs/apply-marker.ign.config.gpg "${config_refusal}" \
        "DOGFOOD_EXPECT=gpgv: BAD signature" \
        -- scripts/dogfood-diskless.sh dist/diskless --check
    scenario "Refuse an unsigned bluefin-node.ign without allow-unsigned" \
        DOGFOOD_BOOT=http DOGFOOD_NODE_IGN=tests/fixtures/ignition/apply-marker.ign \
        "DOGFOOD_REFUSAL=bluefin-node.ign is not signed .* bluefin.ignition.allow-unsigned is not set" \
        -- scripts/dogfood-diskless.sh dist/diskless-next --check
}

# Diskless -> systemd-sysinstall -> disk; outside releases also the A/B
# update and boot-counted rollback, which both kernel-module sysexts (ZFS and
# the NVIDIA driver, plus the toolkit) follow together. The long pole.
bucket_install() {
    if [ "${release}" = true ]; then
        scenario "Install to disk and boot it" -- scripts/dogfood-install.sh dist/diskless
    else
        scenario "Install, A/B update and boot-counted rollback" DOGFOOD_SYSEXT=zfs,nvidia \
            -- scripts/dogfood-install.sh dist/diskless dist/diskless-next dist/diskless-broken
    fi
}

# The offline USB installer onto a blank disk: outside releases also the
# out-of-the-box update contract of a stick install (#310); the supervised
# console path under concurrent noise, including a real prewrite failure
# (#454); and the refusal without Secure Boot (#309).
bucket_installer() {
    if [ "${release}" = true ]; then
        scenario "Install from the offline USB installer and boot it" \
            -- scripts/dogfood-installer.sh dist/diskless
    else
        scenario "Install from the offline USB installer, then update it" \
            -- scripts/dogfood-installer.sh dist/diskless dist/diskless-next
    fi
    scenario "Install from the USB installer at the console under noise and log in" \
        DOGFOOD_INSTALL=console DOGFOOD_CONSOLE_NOISE=1 DOGFOOD_STATE=dist/dogfood-installer-console \
        -- scripts/dogfood-installer.sh dist/diskless
    scenario "Keep a failed USB console install visible under noise" \
        DOGFOOD_INSTALL=console DOGFOOD_CONSOLE_NOISE=1 DOGFOOD_CONSOLE_FAILURE=kernel \
        DOGFOOD_STATE=dist/dogfood-installer-console-failure \
        -- scripts/dogfood-installer.sh dist/diskless
    scenario "Refuse to install from the USB installer without Secure Boot" \
        DOGFOOD_SECURE_BOOT=off DOGFOOD_STATE=dist/dogfood-installer-secure-boot-off \
        -- scripts/dogfood-installer.sh dist/diskless
}

# The offline USB installer onto disks that are not empty (#359): over a
# Bluefin install, and over another OS's GPT disk (ESP, ext4, swap).
bucket_installer-disks() {
    scenario "Install from the offline USB installer, boot it, reinstall over it" \
        DOGFOOD_TARGET=prior-install DOGFOOD_STATE=dist/dogfood-installer-prior-install \
        -- scripts/dogfood-installer.sh dist/diskless
    scenario "Install from the offline USB installer over another OS's disk" \
        DOGFOOD_TARGET=foreign-gpt DOGFOOD_STATE=dist/dogfood-installer-foreign-gpt \
        -- scripts/dogfood-installer.sh dist/diskless
}

usage() { echo "usage: $0 <bucket> | --list [<bucket>] | --buckets (buckets: ${buckets[*]})" >&2; exit 2; }

# A bucket's wall time, passed or failed: a notice, and a row in the job's
# step summary, so rebalancing the buckets starts from real figures.
report_time() {
    local status=$? took=$((SECONDS - started)) result=passed
    [ "${status}" = 0 ] || result=failed
    echo "::notice title=boot-test (${bucket})::bucket ${bucket} took ${took}s (${result})"
    if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
        printf '| Bucket | Result | Wall time |\n| --- | --- | ---: |\n| %s | %s | %dm %02ds |\n' \
            "${bucket}" "${result}" $((took / 60)) $((took % 60)) >> "${GITHUB_STEP_SUMMARY}"
    fi
}

case "${1:-}" in
    --buckets) printf '%s\n' "${buckets[@]}"; exit 0 ;;
    --list) list=true; shift ;;
    '') usage ;;
esac
selected=("${@:-${buckets[@]}}")
[ "${list}" = true ] || [ "$#" = 1 ] || usage
for bucket in "${selected[@]}"; do
    [[ " ${buckets[*]} " == *" ${bucket} "* ]] || usage
    if [ "${list}" != true ]; then
        started=${SECONDS}
        trap report_time EXIT
    fi
    "bucket_${bucket}"
done
