# List available commands
[group('info')]
default:
    @just --list

# Same bst2 container image FSDK/dakota CI uses -- pinned by SHA.
export bst2_image := env("BST2_IMAGE", "registry.gitlab.com/freedesktop-sdk/infrastructure/freedesktop-sdk-docker-images/bst2:64eb0b4930d57a92710822898fb73af6cc1ae35d")

# Prefix for podman calls: empty when rootless podman works, "sudo" otherwise.
sudo_cmd := if `podman info >/dev/null 2>&1 && echo 1 || echo 0` == "1" { "" } else { "sudo" }

# FSDK release parsed from the pinned junction ref — the single source of truth
# for image versioning. e.g. "25.08.13".
export fsdk_version := `grep -oE 'freedesktop-sdk-[0-9]+\.[0-9]+\.[0-9]+' elements/freedesktop-sdk.bst | head -1 | sed 's/freedesktop-sdk-//'`
# Exact junction commit ref (full ref: value), for provenance.
export fsdk_ref := `grep -E '^\s*ref:' elements/freedesktop-sdk.bst | head -1 | sed -E 's/^\s*ref:\s*//'`

# -- BuildStream wrapper ------------------------------------------------------
# Runs any bst command inside the bst2 container via podman.
# Baseline x86_64 (no x86_64_v3) so the base image runs on the widest CPU set.
[group('dev')]
bst *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    export CONTAINERS_CONF="${CONTAINERS_CONF:-/dev/null}"
    export CONTAINERS_CONF_OVERRIDE="${CONTAINERS_CONF_OVERRIDE:-/dev/null}"
    mkdir -p "${HOME}/.cache/buildstream"
    # shellcheck disable=SC2086
    {{sudo_cmd}} podman run --rm \
        --privileged \
        --device /dev/fuse \
        --network=host \
        -v "{{justfile_directory()}}:/src:rw" \
        -v "${HOME}/.cache/buildstream:/root/.cache/buildstream:rw" \
        -w /src \
        "{{bst2_image}}" \
        bash -c 'bst --colors "$@"' -- --no-interactive --error-lines 500 ${BST_FLAGS:-} {{ARGS}}

# Print the FSDK-derived point release used for asset versioning.
[group('info')]
version:
    @echo "{{fsdk_version}}"

# Print the tag set derived from the FSDK release: latest, minor line, point release.
[group('info')]
tags:
    #!/usr/bin/env bash
    set -euo pipefail
    V="{{fsdk_version}}"
    MINOR="$(echo "$V" | cut -d. -f1,2)"
    printf '%s\n%s\n%s\n' latest "$MINOR" "$V"

# ── Validate ──────────────────────────────────────────────────────────
[group('dev')]
validate:
    python3 .github/scripts/check-release-version.py
    python3 .github/scripts/check-kubernetes-version.py
    python3 .github/scripts/check-renovate-series.py
    just bst show --deps all oci/bluefin-server-ddi.bst
    just bst show --deps all oci/bluefin-server-installer.bst
    just bst show --deps all oci/kubernetes-sysext.bst

# Run the unit test suite (pytest + bats).
[group('dev')]
test-unit:
    python3 -m pytest tests/unit -q
    bats tests/unit

# ── Build ─────────────────────────────────────────────────────────────
# Build and export the installer (DDI is embedded; built as a dependency).
[group('build')]
build:
    just export-installer

# ── Export ────────────────────────────────────────────────────────────
# Export installer disk image to dist/.

# -- DDI live installer -------------------------------------------------------
# Produces a bootable GPT disk image that runs systemd-repart to install
# Bluefin Server onto a target disk (see docs/skills/ddi-installer.md).
# The DDI payload is embedded as a data partition; no network required.
# NOTE: build-installer/export-installer are local development commands.
# Release publication is fully automated on GitHub via
# .github/workflows/build.yml and Renovate.

# Build the OS DDI payload filesystem image (implicit dep of build-installer;
# useful when you need the standalone artifact for release publishing).
[group('installer')]
build-ddi:
    just bst build oci/bluefin-server-ddi.bst

# Export the OS DDI payload + SHA256SUMS to dist/ddi/.
[group('installer')]
export-ddi: build-ddi
    rm -rf dist/ddi
    mkdir -p dist/ddi
    just bst artifact checkout oci/bluefin-server-ddi.bst --directory /src/dist/ddi
    @echo "==> wrote DDI payload:" && ls -lh dist/ddi/

# Build the installer disk image locally.
[group('installer')]
build-installer:
    just bst build oci/bluefin-server-installer.bst

# Submit the build to the cluster using Argo workflows.
[group('build')]
cluster-build REF="main":
    argo submit --from wftmpl/bluefin-server-build-pipeline \
        --parameter ref={{REF}} \
        --parameter repo=https://github.com/projectbluefin/server.git \
        --parameter registry=registry.testing-lab.internal:30500 \
        -n argo \
        --watch

# Export the installer disk image + SHA256SUMS to dist/.
# bst artifact checkout requires an empty destination, and dist/ may
# already hold dist/ddi/ or dist/sysext/ from earlier export steps, so
# check out into a clean staging directory and move the files over.
[group('installer')]
export-installer: build-installer
    rm -rf dist/installer-checkout
    mkdir -p dist dist/installer-checkout
    rm -f dist/bluefin-server-installer-*.raw.zst dist/bluefin-server-*.efi dist/bluefin-server-pxe-* dist/SHA256SUMS
    just bst artifact checkout oci/bluefin-server-installer.bst --directory /src/dist/installer-checkout
    mv dist/installer-checkout/* dist/
    rm -rf dist/installer-checkout
    # Record what this artifact was built from. mtimes cannot answer that: a
    # fresh clone stamps every file at checkout time, and a rebase rewrites
    # commit dates, so both signals lie. A content hash of the build inputs
    # does not.
    @just _record-provenance
    @echo "==> wrote:" && ls -lh dist/

# Write the provenance sidecar naming the sources an export was built from.
[private]
_record-provenance:
    #!/usr/bin/env bash
    set -euo pipefail
    IMG=$(find dist/ -maxdepth 1 -type f -name 'bluefin-server-installer-*.raw.zst' -print -quit)
    [ -n "${IMG}" ] || exit 0
    {
        echo "commit $(git rev-parse HEAD 2>/dev/null || echo unknown)"
        echo "tree $(just _inputs-hash)"
    } > "${IMG}.provenance"
    echo "==> provenance: $(sed -n 2p "${IMG}.provenance")"

# Content hash of everything the installer image is built from. Deterministic
# across clones and rebases, unlike mtimes or commit dates.
[private]
_inputs-hash:
    #!/usr/bin/env bash
    set -euo pipefail
    find elements include files project.conf -type f 2>/dev/null \
        | LC_ALL=C sort \
        | xargs -r sha256sum \
        | sha256sum \
        | cut -d' ' -f1

# Export standalone kernel and initrd for PXE boot. The DDI remains embedded
# in the raw installer image; network DDI fetching is not enabled.
[group('installer')]
export-pxe: export-installer
    @test -n "$(find dist/ -maxdepth 1 -type f -name 'bluefin-server-pxe-vmlinuz-*' -print -quit)" || { echo "ERROR: PXE kernel was not exported." >&2; exit 1; }
    @test -n "$(find dist/ -maxdepth 1 -type f -name 'bluefin-server-pxe-initrd-*.cpio.gz' -print -quit)" || { echo "ERROR: PXE initrd was not exported." >&2; exit 1; }
    @echo "==> wrote PXE artifacts:" && ls -lh dist/bluefin-server-pxe-*

# -- Kubernetes systemd-sysext ------------------------------------------------
# Produces a systemd-sysext extension image carrying kubeadm, kubelet, kubectl
# and the CNI plugins.

# Build the Kubernetes systemd-sysext image.
[group('sysext')]
build-sysext:
    just bst build oci/kubernetes-sysext.bst

# Export the Kubernetes systemd-sysext image + SHA256SUMS to dist/sysext/.
# The artifact checkout also emits an uncompressed .raw; only the
# versioned .raw.zst release asset and its SHA256SUMS are published.
[group('sysext')]
export-sysext: build-sysext
    rm -rf dist/sysext dist/sysext-checkout
    mkdir -p dist/sysext-checkout dist/sysext
    just bst artifact checkout oci/kubernetes-sysext.bst --directory /src/dist/sysext-checkout
    cp dist/sysext-checkout/kubernetes-*.raw.zst dist/sysext/
    cp dist/sysext-checkout/SHA256SUMS dist/sysext/
    rm -rf dist/sysext-checkout
    @echo "==> wrote kubernetes sysext:" && ls -lh dist/sysext/

# -- Flatcar LTS kernel & ZFS --------------------------------------------------
# Build the Flatcar LTS kernel and ZFS sysext.

# Build the Flatcar LTS kernel binary and modules.
[group('kernel')]
build-kernel:
    just bst build flatcar/flatcar-kernel.bst

# Build the Flatcar ZFS system extension.
[group('kernel')]
build-zfs:
    just bst build flatcar/flatcar-zfs.bst

# Export the kernel and ZFS artifacts to dist/kernel/.
[group('kernel')]
export-kernel: build-kernel build-zfs
    rm -rf dist/kernel dist/kernel-checkout dist/zfs-checkout
    mkdir -p dist/kernel dist/kernel-checkout dist/zfs-checkout
    just bst artifact checkout flatcar/flatcar-kernel.bst --directory /src/dist/kernel-checkout
    just bst artifact checkout flatcar/flatcar-zfs.bst --directory /src/dist/zfs-checkout
    cp -a dist/kernel-checkout/* dist/kernel/
    cp -a dist/zfs-checkout/* dist/kernel/
    rm -rf dist/kernel-checkout dist/zfs-checkout
    (cd dist/kernel && find . -type f -exec sha256sum --binary {} + > SHA256SUMS)
    @echo "==> wrote kernel & ZFS artifacts:" && ls -lh dist/kernel/

# Write the raw GPT installer image to a physical USB drive.
[group('installer')]
flash-installer DEVICE="":
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -z "{{DEVICE}}" ]; then
        echo "ERROR: Must specify a target block device. Example: just flash-installer /dev/sdX" >&2
        echo "Available writable disk devices:" >&2
        lsblk -p -d -n -o NAME,TYPE,RO,SIZE -b | awk '$2 == "disk" && $3 == "0" && $4 > 0 {printf "  %-15s (%0.1f GB)\n", $1, $4 / 1073741824}' >&2
        exit 1
    fi
    if [ ! -b "{{DEVICE}}" ]; then
        echo "ERROR: {{DEVICE}} is not a valid block device!" >&2
        exit 1
    fi
    # Refuse the disk backing the running system outright. A single mistyped
    # character here is unrecoverable, and the y/N prompt below is not a
    # meaningful defence against a typo the operator has already committed to.
    #
    # `/` is not always on a block device. On composefs/ostree hosts — including
    # Bluefin itself, which is what a developer runs this from — `findmnt / `
    # reports a composefs digest, and the real device is mounted at /sysroot.
    # Check both, so the guard is not silently inert on exactly the systems this
    # project targets.
    TARGET_NAME=$(lsblk -no KNAME "{{DEVICE}}" 2>/dev/null | head -n1 || true)
    for mp in / /sysroot; do
        SRC=$(findmnt -no SOURCE "${mp}" 2>/dev/null | head -n1 || true)
        case "${SRC}" in /dev/*) ;; *) continue ;; esac
        # PKNAME is the parent disk of a partition, and is empty when the
        # filesystem sits directly on a whole-disk device (no partition table,
        # or a device-mapper/loop node). Falling back to KNAME keeps the guard
        # live on those hosts instead of silently skipping the comparison.
        SRC_DISK=$(lsblk -no PKNAME "${SRC}" 2>/dev/null | head -n1 || true)
        if [ -z "${SRC_DISK}" ]; then
            SRC_DISK=$(lsblk -no KNAME "${SRC}" 2>/dev/null | head -n1 || true)
        fi
        if [ -n "${SRC_DISK}" ] && [ "${SRC_DISK}" = "${TARGET_NAME}" ]; then
            echo "ERROR: {{DEVICE}} is the disk backing the running system." >&2
            echo "  ${mp} is on ${SRC}, which lives on /dev/${SRC_DISK}." >&2
            echo "Refusing to overwrite it." >&2
            exit 1
        fi
    done
    # Refuse a device with anything mounted off it. dd writing under a live
    # filesystem gives a torn image and leaves the kernel holding stale page
    # cache for blocks that no longer exist.
    MOUNTED=$(lsblk -n -o MOUNTPOINTS "{{DEVICE}}" | grep -v '^\s*$' || true)
    if [ -n "${MOUNTED}" ]; then
        echo "ERROR: {{DEVICE}} has mounted partitions:" >&2
        lsblk -p -o NAME,SIZE,MOUNTPOINTS "{{DEVICE}}" >&2
        echo >&2
        echo "Unmount them first, e.g.:" >&2
        # -l (list) not the default tree: tree mode prefixes names with box
        # glyphs, which would make the suggested command uncopyable.
        lsblk -p -n -l -o NAME,MOUNTPOINTS "{{DEVICE}}" \
            | awk 'NF>1 {printf "  udisksctl unmount -b %s\n", $1}' >&2
        exit 1
    fi
    # -maxdepth 1 keeps release images in dist/release/ out of the match, but a
    # stale export beside a fresh one is still ambiguous — fail rather than let
    # `head -n1` pick by directory order.
    mapfile -t IMGS < <(find dist/ -maxdepth 1 -type f -name 'bluefin-server-installer-*.raw.zst' | sort)
    if [ "${#IMGS[@]}" -eq 0 ]; then
        echo "ERROR: No exported installer found in dist/." >&2
        echo "Please run: just build-installer && just export-installer" >&2
        exit 1
    fi
    if [ "${#IMGS[@]}" -gt 1 ]; then
        echo "ERROR: ${#IMGS[@]} installer images in dist/; refusing to guess:" >&2
        printf '  %s\n' "${IMGS[@]}" >&2
        echo "Remove the stale one, then re-run." >&2
        exit 1
    fi
    IMG="${IMGS[0]}"
    # Verify the archive before the prompt, not after. A truncated or corrupt
    # download is exactly what a freshly fetched CI artifact invites, and
    # failing here costs nothing while failing mid-write leaves an unbootable
    # disk that looks like it succeeded.
    echo "Verifying ${IMG}..."
    if ! zstd -t "${IMG}"; then
        echo "ERROR: ${IMG} failed its integrity check; refusing to write it." >&2
        exit 1
    fi
    echo "WARNING: All data on {{DEVICE}} will be COMPLETELY DESTROYED!"
    echo "Double-checking device information:"
    lsblk -p "{{DEVICE}}"
    echo
    read -p "Are you absolutely sure you want to write to {{DEVICE}}? [y/N] " -r CONFIRM
    if [[ ! "${CONFIRM}" =~ ^[yY](es)?$ ]]; then
        echo "Aborted."
        exit 1
    fi
    echo "Writing ${IMG} to {{DEVICE}}..."
    # Digest and byte count of the payload. Both are needed after the write:
    # the count to know how much of the device to read back, the digest to
    # compare it against.
    #
    # Two plain passes rather than one with `tee >(wc -c > file)`. Bash does
    # not wait for process-substitution children, so the count file may still
    # be unwritten when $( ) returns — it happens to work only because wc
    # finishes before sha256sum. An empty count yields a malformed `count=`
    # and fails the flash with a misleading "medium did not retain the image".
    # The extra decompression costs seconds against a write measured in
    # minutes.
    echo "Hashing ${IMG}..."
    EXPECT_SHA=$(zstd -dc "${IMG}" | sha256sum | cut -d' ' -f1)
    EXPECT_BYTES=$(zstd -dc "${IMG}" | wc -c | tr -d ' ')
    # bash with pipefail, not sh. Under POSIX sh the pipeline's status is dd's
    # alone, so zstd dying mid-stream leaves dd exiting 0 after writing a
    # partial image and the success line below printing anyway. The outer
    # `set -o pipefail` does not reach here — there is no pipeline in the outer
    # shell, only this nested one.
    sudo bash -c "set -o pipefail; zstd -dc '${IMG}' | dd of={{DEVICE}} bs=4M iflag=fullblock oflag=direct status=progress conv=fsync"
    # Read the device back and compare. Without this, "flashed" rests on dd's
    # exit status, which says the writes were accepted, not that the medium
    # kept them — the failure mode of a dying USB stick. Do it before the
    # relocation below, which deliberately rewrites the headers and would make
    # the digests differ for a legitimate reason.
    # Drop the kernel's cached view of the device first, so the comparison
    # reads the medium and not the pages just written through it. O_DIRECT
    # would do the same but requires aligned reads, and the trailing block is
    # partial whenever the image is not a multiple of the block size.
    sudo blockdev --flushbufs {{DEVICE}}
    echo "Verifying ${EXPECT_BYTES} bytes read back from {{DEVICE}}..."
    ACTUAL_SHA=$(sudo dd if={{DEVICE}} bs=4M iflag=fullblock,count_bytes \
        count="${EXPECT_BYTES}" status=none | sha256sum | cut -d' ' -f1)
    if [ "${ACTUAL_SHA}" != "${EXPECT_SHA}" ]; then
        echo "ERROR: {{DEVICE}} does not contain what was written." >&2
        echo "  expected ${EXPECT_SHA}" >&2
        echo "  read     ${ACTUAL_SHA}" >&2
        echo "The medium did not retain the image. Replace it." >&2
        exit 1
    fi
    echo "Content verified: ${EXPECT_SHA}"
    # Move the GPT backup header to the end of the DEVICE.
    #
    # dd writes the image verbatim, so the backup header lands at the end of the
    # IMAGE. GPT requires it at the device's last LBA, so on any medium larger
    # than the image the table is only half valid: the primary header points at
    # a backup LBA that is not where the device ends. parted says so directly —
    #
    #   Warning: Not all of the space available to /dev/sdb appears to be used,
    #   you can fix the GPT to use all of the space (an extra 115791863 blocks)
    #
    # — and tools disagree about partition sizes between reads.
    #
    # This does NOT stop the medium booting, and it is worth being precise about
    # that, because assuming otherwise cost a day of chasing a phantom. UEFI
    # reads the PRIMARY header at LBA 1, which dd writes correctly; the backup
    # is a redundancy copy consulted when the primary is damaged. A medium in
    # this state was written to a 58.6 GB sparse file, reproduced the sfdisk
    # error exactly, and booted to systemd PID 1 under OVMF.
    #
    # What it breaks is tooling, and it is invisible to every test we have:
    # `just test-installer-artifact` and the CI installer-test attach the image
    # as a drive sized exactly to the image, so device size always equals image
    # size and the condition cannot arise.
    echo "Relocating the GPT backup header to the end of {{DEVICE}}..."
    sudo sfdisk --relocate gpt-bak-std {{DEVICE}}
    sudo partprobe {{DEVICE}} || true
    sudo sfdisk --verify {{DEVICE}}
    echo "Successfully flashed the Bluefin Server installer to {{DEVICE}}!"

# Boot the installer MEDIUM through firmware, as real hardware does.
#
# This is the only test that exercises the ESP. `test-installer-artifact` and
# CI's installer-test both attach installer.raw as a data disk and inject the
# kernel with -kernel/-initrd, so EFI/BOOT/BOOTX64.EFI is never executed. They
# prove the installer installs; they cannot prove the medium boots.
#
# That gap shipped a medium that does not boot: a single 434 MiB UKI which OVMF
# loads and never executes, with every gate green.
#
# The image is written into a sparse file LARGER than itself, because that is
# what a real stick is, and it reproduces the GPT backup-header condition that
# an image-sized virtual disk cannot.
[group('test')]
test-installer-boot:
    #!/usr/bin/env bash
    set -euo pipefail

    # Same refusal as `flash-installer`: a stale export beside a fresh one is
    # ambiguous, and `head -n1` would quietly gate on whichever sorts first.
    # A boot result is only evidence about a named artifact, so the artifact
    # must not be picked by accident.
    mapfile -t IMGS < <(find dist/ -maxdepth 1 -type f -name 'bluefin-server-installer-*.raw.zst' | sort)
    if [ "${#IMGS[@]}" -eq 0 ]; then
        echo "ERROR: no exported installer in dist/. Run: just export-installer" >&2
        exit 1
    fi
    if [ "${#IMGS[@]}" -gt 1 ]; then
        echo "ERROR: ${#IMGS[@]} installer images in dist/; refusing to guess:" >&2
        printf '  %s\n' "${IMGS[@]}" >&2
        echo "Remove the stale one, then re-run." >&2
        exit 1
    fi
    IMG="${IMGS[0]}"

    # This boots an EXPORTED ARTIFACT. It does not build, and `just validate`
    # only resolves the graph without building either. So a green result is
    # evidence about the bytes in dist/, NOT about the current state of
    # elements/oci/bluefin-server-installer.bst.
    #
    # Say so out loud, and refuse to imply more than that when the tree has
    # moved since the export. Without this, "the medium boots" quietly becomes
    # a claim about a tree that was never built — the same overclaim this
    # recipe exists to prevent.
    #
    # The comparison is a content hash of the build inputs, recorded into a
    # sidecar by `export-installer`. Not mtimes: a fresh clone stamps every
    # file at checkout time and a rebase rewrites commit dates, so both would
    # report a clean tree as stale and a stale tree as clean. Not an allow-list
    # of "important" sources either — that drifts the moment someone edits a
    # repart config or a unit file.
    echo "==> Artifact under test:"
    echo "    ${IMG}"
    echo "    sha256 $(sha256sum "${IMG}" | cut -d' ' -f1)"
    if [ -f "${IMG}.provenance" ]; then
        BUILT_FROM=$(awk '/^tree /{print $2}' "${IMG}.provenance")
        BUILT_AT=$(awk '/^commit /{print $2}' "${IMG}.provenance")
        echo "    commit ${BUILT_AT}"
        NOW=$(just _inputs-hash)
        if [ "${BUILT_FROM}" != "${NOW}" ]; then
            echo "WARNING: the tree has changed since this artifact was built." >&2
            echo "           built from ${BUILT_FROM}" >&2
            echo "           tree now   ${NOW}" >&2
            echo "         A pass proves the exported medium boots. It proves" >&2
            echo "         NOTHING about the current sources. Re-export before" >&2
            echo "         treating this as a gate on your changes." >&2
        else
            echo "    tree   matches current sources"
        fi
    else
        echo "WARNING: no provenance sidecar beside this artifact, so there is" >&2
        echo "         no way to tell what it was built from. A pass proves" >&2
        echo "         these bytes boot and nothing more. Re-export to record" >&2
        echo "         provenance." >&2
    fi

    first_existing() { for f in "$@"; do [ -f "$f" ] && { echo "$f"; return 0; }; done; return 1; }
    OVMF_CODE=$(first_existing \
      /home/linuxbrew/.linuxbrew/Cellar/qemu/*/share/qemu/edk2-x86_64-code.fd \
      /usr/share/edk2/ovmf/OVMF_CODE.fd \
      /usr/share/OVMF/OVMF_CODE.fd \
      /usr/share/OVMF/OVMF_CODE_4M.fd \
      /usr/share/edk2/x64/OVMF_CODE.4m.fd \
      /usr/share/qemu/edk2-x86_64-code.fd \
      /usr/share/qemu/OVMF_CODE.fd) \
      || { echo "ERROR: OVMF_CODE not found" >&2; exit 1; }

    WORK=$(mktemp -d "${XDG_CACHE_HOME:-$HOME/.cache}/bluefin-boot-test.XXXXXX")
    trap 'rm -rf "$WORK"' EXIT INT TERM

    # A stick is bigger than the image. Sparse, so this costs only real bytes.
    truncate -s 62914560000 "$WORK/medium.img"
    zstd -dc "${IMG}" | dd of="$WORK/medium.img" conv=notrunc bs=4M iflag=fullblock status=none
    sfdisk --relocate gpt-bak-std "$WORK/medium.img" >/dev/null
    sfdisk --verify "$WORK/medium.img"

    # OVMF needs a writable vars pflash of the same size as the code image.
    truncate -s "$(stat -c %s "$OVMF_CODE")" "$WORK/vars.fd"

    DEADLINE="${INSTALLER_BOOT_DEADLINE:-240}"
    # A healthy medium boots with `quiet loglevel=3` and prints almost nothing,
    # which is indistinguishable from a hang until you look closely. Setting
    # INSTALLER_BOOT_CMDLINE_EXTRA=loglevel=7 makes a healthy boot loud without
    # rebuilding anything: systemd-stub reads this SMBIOS type-11 string and
    # appends it to the UKI's embedded cmdline.
    CMDLINE_EXTRA="${INSTALLER_BOOT_CMDLINE_EXTRA:-}"
    # if-blocks, not `[ -n x ] && y`: under `set -e` a false test makes the
    # whole recipe exit, so the default (no extra cmdline) would abort the run.
    SMBIOS=()
    if [ -n "${CMDLINE_EXTRA}" ]; then
        SMBIOS=(-smbios "type=11,value=io.systemd.stub.kernel-cmdline-extra=${CMDLINE_EXTRA}")
    fi
    echo "==> Booting the installer medium through firmware (deadline ${DEADLINE}s)..."
    if [ -n "${CMDLINE_EXTRA}" ]; then
        echo "    cmdline-extra: ${CMDLINE_EXTRA}"
    fi
    timeout "${DEADLINE}" qemu-system-x86_64 \
        -enable-kvm -m 4096 -smp 2 -cpu host \
        -drive file="$WORK/medium.img",format=raw,if=virtio \
        -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
        -drive if=pflash,format=raw,file="$WORK/vars.fd" \
        "${SMBIOS[@]}" \
        -nographic -serial file:"$WORK/serial.log" -monitor none -no-reboot \
        >/dev/null 2>&1 || true

    # `strings`, not `cat`. The console is almost entirely ANSI and OSC escape
    # sequences, which a terminal swallows — `cat` on a perfectly good boot log
    # shows two firmware lines and apparent silence. That is what convinced me
    # a working medium was hung.
    echo "==> Serial output:"
    strings -n 4 "$WORK/serial.log" | grep -av '^\[[0-9;]*[A-Za-z]$' || true

    # Criterion 1: firmware must actually start an image, not merely find the
    # medium. A corrupted bootloader makes firmware fall through to PXE, and
    # this is the check that catches it — verified against a medium built by
    # mcopy-ing junk over EFI/BOOT/BOOTX64.EFI, which produced
    # "BdsDxe: failed to load ... Not Found" and no `starting` line.
    #
    # Criterion 2 below does not depend on this one: PXE fallback chatter
    # cannot produce a machineid, and was checked against the corrupt medium's
    # log — no match. Criterion 1 is kept because it names the failure
    # precisely ("firmware never started an image" vs "userspace never came
    # up"), which is the difference between a dead bootloader and a dead boot.
    if ! grep -aq "BdsDxe: starting" "$WORK/serial.log"; then
        echo "ERROR: firmware never started a boot image from the medium." >&2
        exit 1
    fi
    # Firmware handing off is not proof that userspace ran. Assert on something
    # only a running Linux userspace can emit.
    #
    # systemd PID 1 writes an OSC 3008 sequence to the console carrying the
    # machine's identity:
    #
    #   ESC ]3008;start=<id>;user=root;hostname=<h>;machineid=<id>;bootid=<id>;
    #        pid=1;comm=systemd;type=boot
    #
    # Firmware cannot produce a machineid or a bootid. This survives `quiet
    # loglevel=3`, which is what the medium boots with, and it does not depend
    # on guessing kernel log strings.
    # Two earlier criteria were tried and rejected, both against captured logs:
    #
    #   "Linux version|initrd|systemd"  — `quiet` suppresses all of it, while a
    #       FAILING boot prints dracut emergency text. It rewarded failure.
    #   any non-whitespace after handoff — firmware and systemd-stub both emit
    #       CSI cursor codes, so a corrupt bootloader falling through to PXE
    #       scored as success.
    #
    # Honest limit: proven against a booting medium (fires on the real image
    # under both `quiet` and loglevel=7) and against a medium whose bootloader
    # is destroyed (its PXE-fallback log contains no machineid). NOT proven
    # against a genuine start-then-hang, because no such image exists — the
    # 434 MiB UKI was suspected of being one and was exonerated. If one ever
    # turns up, keep it.
    if ! grep -aqE 'machineid=[0-9a-f]{32}|comm=systemd' "$WORK/serial.log"; then
        echo "ERROR: firmware started an image, but userspace never came up." >&2
        echo "       No systemd identity record on the console. Control did not" >&2
        echo "       reach PID 1." >&2
        exit 1
    fi
    echo "==> The installer medium boots: systemd PID 1 reported in."
    grep -ao 'machineid=[0-9a-f]\{32\}' "$WORK/serial.log" | head -1 | sed 's/^/    /'

# Build the installer artifacts, then run the reusable artifact smoke path.
[group('test')]
show-me-the-future:
    just build-installer
    just export-installer
    just test-installer-artifact

# Install and reboot already-exported server artifacts in QEMU.
[group('test')]
test-installer-artifact:
    #!/usr/bin/env bash
    set -euo pipefail

    CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}"
    mkdir -p "$CACHE_DIR"
    WORKDIR="$(mktemp -d "${CACHE_DIR}/bluefin-show-future.XXXXXX")"
    trap 'rm -rf "$WORKDIR"' EXIT

    cp dist/bluefin-server-installer-*.raw.zst "$WORKDIR/installer.raw.zst"
    cp dist/bluefin-server-pxe-vmlinuz-* "$WORKDIR/installer.vmlinuz"
    cp dist/bluefin-server-pxe-initrd-*.cpio.gz "$WORKDIR/installer.initrd"
    zstd -d "$WORKDIR/installer.raw.zst" -o "$WORKDIR/installer.raw"
    TARGET_SIZE="${SHOW_ME_THE_FUTURE_DISK_SIZE:-16G}"
    truncate -s "${TARGET_SIZE}" "$WORKDIR/target.raw"

    # Return the first existing file from a list of candidates.
    first_existing() {
      for candidate in "$@"; do
        if [ -f "$candidate" ]; then
          echo "$candidate"
          return 0
        fi
      done
      return 1
    }

    OVMF_CODE=$(first_existing \
      /home/linuxbrew/.linuxbrew/Cellar/qemu/*/share/qemu/edk2-x86_64-code.fd \
      /home/linuxbrew/.linuxbrew/Cellar/qemu/*/share/qemu/edk2-x86_64-secure-code.fd \
      /usr/share/edk2/ovmf/OVMF_CODE.fd \
      /usr/share/OVMF/OVMF_CODE.fd \
      /usr/share/OVMF/OVMF_CODE_4M.fd \
      /usr/share/edk2/x64/OVMF_CODE.4m.fd \
      /usr/share/qemu/edk2-x86_64-code.fd \
      /usr/share/qemu/edk2-x86_64-secure-code.fd \
      /usr/share/qemu/OVMF_CODE.fd) \
      || { echo "ERROR: OVMF_CODE not found"; exit 1; }

    OVMF_VARS=$(first_existing \
      /home/linuxbrew/.linuxbrew/Cellar/qemu/*/share/qemu/edk2-x86_64-vars.fd \
      /usr/share/edk2/ovmf/OVMF_VARS.fd \
      /usr/share/OVMF/OVMF_VARS.fd \
      /usr/share/OVMF/OVMF_VARS_4M.fd \
      /usr/share/edk2/x64/OVMF_VARS.4m.fd \
      /usr/share/qemu/edk2-x86_64-vars.fd \
      /usr/share/qemu/OVMF_VARS.fd) \
      || true
    if [ -n "$OVMF_VARS" ]; then
      cp "$OVMF_VARS" "$WORKDIR/ovmf-vars.fd"
    else
      truncate -s "$(stat -c '%s' "$OVMF_CODE")" "$WORKDIR/ovmf-vars.fd"
    fi

    SMP_CPUS="${SHOW_ME_THE_FUTURE_SMP:-$(nproc)}"
    MEM_SIZE="${SHOW_ME_THE_FUTURE_MEM:-8192}"

    echo "==> Booting installer media in QEMU..."
    # ponytail: we want QEMU to exit cleanly after install. Since QEMU's -no-reboot
    # suspends/halts on reboot signals, we override systemd-sysinstall.service SuccessAction/FailureAction
    # to poweroff. When the installer triggers poweroff, QEMU terminates, and we boot into the newly installed OS.
    qemu-system-x86_64 \
        -enable-kvm \
        -m "${MEM_SIZE}" \
        -cpu host \
        -smp "${SMP_CPUS}" \
        -drive file="$WORKDIR/installer.raw",format=raw,if=virtio,readonly=on \
        -drive file="$WORKDIR/target.raw",format=raw,if=virtio \
        -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
        -drive if=pflash,format=raw,file="$WORKDIR/ovmf-vars.fd" \
        -kernel "$WORKDIR/installer.vmlinuz" \
        -initrd "$WORKDIR/installer.initrd" \
        -append "systemd.unit=system-install.target console=tty0 console=ttyS0,115200 rw unattended" \
        -nographic \
        -serial mon:stdio \
        -no-reboot < /dev/null

    SERIAL_LOG="$WORKDIR/serial.log"
    TARGET_QEMU_PID=""
    cleanup() {
      EXIT_STATUS=$?
      if [ -n "${TARGET_QEMU_PID:-}" ] && kill -0 "$TARGET_QEMU_PID" 2>/dev/null; then
        kill "$TARGET_QEMU_PID" 2>/dev/null || true
        wait "$TARGET_QEMU_PID" 2>/dev/null || true
      fi
      if [ "$EXIT_STATUS" -eq 0 ]; then
        rm -rf "$WORKDIR"
      else
        echo "ERROR: QEMU smoke failed; retaining artifacts at $WORKDIR" >&2
      fi
      exit "$EXIT_STATUS"
    }
    trap cleanup EXIT INT TERM

    SSH_KEY="$WORKDIR/test_ssh_key"
    rm -f "$SSH_KEY" "$SSH_KEY.pub"
    ssh-keygen -t ed25519 -N "" -f "$SSH_KEY" >/dev/null 2>&1
    SSH_PUB_B64=$(cat "$SSH_KEY.pub" | base64 -w0)

    echo "==> Booting the installed server in QEMU (background)..."
    qemu-system-x86_64 \
        -enable-kvm \
        -m "${MEM_SIZE}" \
        -cpu host \
        -smp "${SMP_CPUS}" \
        -drive file="$WORKDIR/target.raw",format=raw,if=virtio \
        -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
        -drive if=pflash,format=raw,file="$WORKDIR/ovmf-vars.fd" \
        -nic user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:8080-:8080,hostfwd=tcp:127.0.0.1:2222-:22 \
        -smbios "type=11,value=io.systemd.credential.binary:fstab.extra=L2Rldi9kaXNrL2J5LXBhcnRsYWJlbC92YXIgL3ZhciB4ZnMgZGVmYXVsdHMgMCAwCg==" \
        -smbios "type=11,value=io.systemd.credential.binary:ssh.authorized_keys.root=${SSH_PUB_B64}" \
        -smbios "type=11,value=io.systemd.stub.kernel-cmdline-extra=console=tty0 console=ttyS0,,115200 systemd.mask=systemd-firstboot.service systemd.mask=systemd-homed-firstboot.service systemd.wants=sshd.service" \
        -nographic \
        -serial file:"$SERIAL_LOG" \
        -monitor none &
    TARGET_QEMU_PID=$!

    DEADLINE_SECS="${SHOW_ME_THE_FUTURE_DEADLINE:-${SHOW_ME_THE_FUTURE_TIMEOUT:-600}}"
    START_TIME=$(date +%s)
    echo "==> Polling KubeStellar Console readiness (deadline: ${DEADLINE_SECS}s)..."

    while true; do
      if ! kill -0 "$TARGET_QEMU_PID" 2>/dev/null; then
        echo "ERROR: Target QEMU process ($TARGET_QEMU_PID) died unexpectedly!" >&2
        if [ -f "$SERIAL_LOG" ]; then
          echo "==> Serial log tail (last 100 lines):" >&2
          tail -n 100 "$SERIAL_LOG" >&2
        fi
        exit 1
      fi

      # Probe guest directly over SSH tunnel or in-guest curl to 127.0.0.1:8080.
      # The kiosk serves TLS with an in-cluster CA, hence --insecure. Plain HTTP
      # is not probed: nginx answers it with a 302 to https, so a fallback would
      # report 302 rather than the real status.
      HEALTHZ_RESP=$(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=2 -p 2222 root@127.0.0.1 "curl --silent --insecure --max-time 2 https://127.0.0.1:8080/healthz 2>/dev/null || true" 2>/dev/null || true)
      if [ -n "$HEALTHZ_RESP" ]; then
        ROOT_CODE=$(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=2 -p 2222 root@127.0.0.1 "curl --silent --insecure --max-time 2 --output /dev/null --write-out '%{http_code}' https://127.0.0.1:8080/ 2>/dev/null || true" 2>/dev/null || true)
        if [ "$ROOT_CODE" = "200" ]; then
          if echo "$HEALTHZ_RESP" | jq -e '.status == "ok"' >/dev/null 2>&1; then
            echo "==> KubeStellar Console is healthy: /healthz status ok, / returned HTTP 200"
            break
          fi
        fi
      fi
      NOW=$(date +%s)
      ELAPSED=$((NOW - START_TIME))
      if [ "$ELAPSED" -ge "$DEADLINE_SECS" ]; then
        echo "ERROR: Timed out after ${DEADLINE_SECS}s waiting for KubeStellar Console readiness!" >&2
        if [ -f "$SERIAL_LOG" ]; then
          echo "==> Serial log tail (last 100 lines):" >&2
          tail -n 100 "$SERIAL_LOG" >&2
        fi
        exit 1
      fi

      sleep 2
    done

# Interactively install and boot a persistent local KubeStellar kiosk VM.
[group('test')]
install-vm:
    #!/usr/bin/env bash
    set -euo pipefail

    STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/bluefin-server/vm-{{fsdk_version}}"
    INSTALLER_RAW="$STATE_DIR/installer.raw"
    TARGET_RAW="$STATE_DIR/target.raw"
    OVMF_VARS="$STATE_DIR/ovmf-vars.fd"
    INSTALL_COMPLETE="$STATE_DIR/installed"
    mkdir -p "$STATE_DIR"

    first_existing() {
      for candidate in "$@"; do
        if [ -f "$candidate" ]; then
          echo "$candidate"
          return 0
        fi
      done
      return 1
    }

    OVMF_CODE=$(first_existing \
      /home/linuxbrew/.linuxbrew/Cellar/qemu/*/share/qemu/edk2-x86_64-code.fd \
      /home/linuxbrew/.linuxbrew/Cellar/qemu/*/share/qemu/edk2-x86_64-secure-code.fd \
      /usr/share/edk2/ovmf/OVMF_CODE.fd \
      /usr/share/OVMF/OVMF_CODE.fd \
      /usr/share/OVMF/OVMF_CODE_4M.fd \
      /usr/share/edk2/x64/OVMF_CODE.4m.fd \
      /usr/share/qemu/edk2-x86_64-code.fd \
      /usr/share/qemu/edk2-x86_64-secure-code.fd \
      /usr/share/qemu/OVMF_CODE.fd) \
      || { echo "ERROR: OVMF_CODE not found"; exit 1; }

    if [ ! -f "$OVMF_VARS" ]; then
      OVMF_TEMPLATE=$(first_existing \
        /home/linuxbrew/.linuxbrew/Cellar/qemu/*/share/qemu/edk2-x86_64-vars.fd \
        /usr/share/edk2/ovmf/OVMF_VARS.fd \
        /usr/share/OVMF/OVMF_VARS.fd \
        /usr/share/OVMF/OVMF_VARS_4M.fd \
        /usr/share/edk2/x64/OVMF_VARS.4m.fd \
        /usr/share/qemu/edk2-x86_64-vars.fd \
        /usr/share/qemu/OVMF_VARS.fd) \
        || true
      if [ -n "$OVMF_TEMPLATE" ]; then
        cp "$OVMF_TEMPLATE" "$OVMF_VARS"
      else
        truncate -s "$(stat -c '%s' "$OVMF_CODE")" "$OVMF_VARS"
      fi
    fi

    SMP_CPUS="${INSTALL_VM_SMP:-$(nproc)}"
    MEM_SIZE="${INSTALL_VM_MEM:-8192}"

    if [ ! -f "$INSTALL_COMPLETE" ]; then
      just export-installer
      INSTALLER_ARCHIVE=$(find dist/ -maxdepth 1 -type f -name 'bluefin-server-installer-*.raw.zst' -print -quit)
      [ -n "$INSTALLER_ARCHIVE" ] || { echo "ERROR: No exported installer found in dist/." >&2; exit 1; }
      zstd -d -f "$INSTALLER_ARCHIVE" -o "$INSTALLER_RAW"
      truncate -s "${INSTALL_VM_DISK_SIZE:-16G}" "$TARGET_RAW"

      echo "==> Booting the interactive installer in QEMU..."
      qemu-system-x86_64 \
        -enable-kvm \
        -m "${MEM_SIZE}" \
        -cpu host \
        -smp "${SMP_CPUS}" \
        -drive file="$INSTALLER_RAW",format=raw,if=virtio,readonly=on \
        -drive file="$TARGET_RAW",format=raw,if=virtio \
        -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
        -drive if=pflash,format=raw,file="$OVMF_VARS"
      touch "$INSTALL_COMPLETE"
    fi

    echo "==> Booting the installed kiosk..."
    qemu-system-x86_64 \
      -enable-kvm \
      -m "${MEM_SIZE}" \
      -cpu host \
      -smp "${SMP_CPUS}" \
      -drive file="$TARGET_RAW",format=raw,if=virtio \
      -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
      -drive if=pflash,format=raw,file="$OVMF_VARS" \
      -nic user,model=virtio-net-pci,hostfwd=tcp::8080-:8080,hostfwd=tcp::2222-:22,hostfwd=tcp::6443-:6443 &
    QEMU_PID=$!
    cleanup() {
      if kill -0 "$QEMU_PID" 2>/dev/null; then
        kill "$QEMU_PID"
        wait "$QEMU_PID" || true
      fi
    }
    trap cleanup INT TERM

    until curl --silent --show-error --insecure --max-time 2 --output /dev/null https://127.0.0.1:8080/; do
      if ! kill -0 "$QEMU_PID" 2>/dev/null; then
        wait "$QEMU_PID"
        exit 1
      fi
      sleep 2
    done

    HOST_IP="$(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -n1)"
    echo "==> KubeStellar Console is ready!"
    echo "==> Access URL (LAN): https://${HOST_IP:-localhost}:8080/"
    echo "==> Access URL (Local): https://localhost:8080/"
    xdg-open "https://${HOST_IP:-localhost}:8080/" || xdg-open https://localhost:8080/ || true
    wait "$QEMU_PID"

# Set up KubeStellar kc-agent for the user in ONE command.
[group('test')]
setup-kubestellar ORIGIN="https://localhost:8080,https://127.0.0.1:8080":
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -x "files/bin/bluefin-kubestellar" ]; then
      exec ./files/bin/bluefin-kubestellar start --origin "{{ORIGIN}}"
    else
      if ! command -v kc-agent >/dev/null 2>&1; then
        echo "==> Installing kc-agent from kubestellar/tap..."
        brew tap kubestellar/tap
        brew install kc-agent
      fi
      export KAGENTI_CONTROLLER_URL="none"
      kc-agent -kubeconfig "${KUBECONFIG:-$HOME/.kube/config}" -allowed-origins "{{ORIGIN}}" &
    fi

# Run fully automated headless browser test against the KubeStellar console.
[group('test')]
test-e2e-browser CONSOLE_URL="https://127.0.0.1:8080":
    python3 tests/e2e/test_kubestellar_browser_login.py --console-url "{{CONSOLE_URL}}"

# Complete end-to-end Lima VM orchestration test.
[group('test')]
test-e2e-lima:
    #!/usr/bin/env bash
    set -euo pipefail
    limactl validate files/lima/bluefin-server-kiosk.yaml
    echo "==> Lima VM template validation passed: files/lima/bluefin-server-kiosk.yaml"
    if [ "${RUN_LIMA_VM:-0}" = "1" ]; then
      ./scripts/lima-e2e-kubestellar-test.sh
    fi
