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
    python3 .github/scripts/check-k0s-version.py
    python3 .github/scripts/check-renovate-series.py
    python3 .github/scripts/check-flatcar-version.py
    just bst show --deps all oci/bluefin-server-ddi.bst
    just bst show --deps all oci/bluefin-server-installer.bst
    just bst show --deps all oci/k0s-sysext.bst

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
#
# os-base selects the payload base for the FSDK-vs-Flatcar parity harness
# (projectbluefin/server#129):
#   fsdk            FSDK-composed payload, the shipped base (default).
#   flatcar-reference Imported Flatcar reference tree, the known-good control.
#                     Routes to bluefin-server-ddi-flatcar-reference.bst, added
#                     alongside the #126 imported Flatcar reference tree.
[group('installer')]
build-ddi $OS_BASE="fsdk":
    #!/usr/bin/env bash
    set -euo pipefail
    case "$OS_BASE" in
        fsdk)
            DDI_ELEMENT="oci/bluefin-server-ddi.bst"
            ;;
        flatcar-reference)
            if [ ! -f "elements/oci/bluefin-server-ddi-flatcar-reference.bst" ]; then
                echo "ERROR: os-base=flatcar-reference requires the imported Flatcar reference tree" >&2
                echo "       (projectbluefin/server#126); element oci/bluefin-server-ddi-flatcar-reference.bst" >&2
                echo "       does not exist yet. Add it alongside the #126 tree, then re-run." >&2
                exit 1
            fi
            DDI_ELEMENT="oci/bluefin-server-ddi-flatcar-reference.bst"
            ;;
        *)
            echo "ERROR: unknown os-base '${OS_BASE}' (expected 'fsdk' or 'flatcar-reference')" >&2
            exit 1
            ;;
    esac
    just bst build "${DDI_ELEMENT}"

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
    @echo "==> wrote:" && ls -lh dist/

# Export standalone kernel and initrd for PXE boot. The DDI remains embedded
# in the raw installer image; network DDI fetching is not enabled.
[group('installer')]
export-pxe: export-installer
    @test -n "$(find dist/ -maxdepth 1 -type f -name 'bluefin-server-pxe-vmlinuz-*' -print -quit)" || { echo "ERROR: PXE kernel was not exported." >&2; exit 1; }
    @test -n "$(find dist/ -maxdepth 1 -type f -name 'bluefin-server-pxe-initrd-*.cpio.gz' -print -quit)" || { echo "ERROR: PXE initrd was not exported." >&2; exit 1; }
    @echo "==> wrote PXE artifacts:" && ls -lh dist/bluefin-server-pxe-*

# -- k0s systemd-sysext -------------------------------------------------------
# Produces a systemd-sysext extension image for k0s.

# Build the k0s systemd-sysext image.
[group('sysext')]
build-sysext:
    just bst build oci/k0s-sysext.bst

# Export the k0s systemd-sysext image + SHA256SUMS to dist/sysext/.
# The artifact checkout also emits an uncompressed .raw; only the
# versioned .raw.zst release asset and its SHA256SUMS are published.
[group('sysext')]
export-sysext: build-sysext
    rm -rf dist/sysext dist/sysext-checkout
    mkdir -p dist/sysext-checkout dist/sysext
    just bst artifact checkout oci/k0s-sysext.bst --directory /src/dist/sysext-checkout
    cp dist/sysext-checkout/k0s-*.raw.zst dist/sysext/
    cp dist/sysext-checkout/SHA256SUMS dist/sysext/
    rm -rf dist/sysext-checkout
    @echo "==> wrote k0s sysext:" && ls -lh dist/sysext/

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
    # Refuse the disk backing the running system outright. Resolve the target
    # to its parent disk first, the same way the root source is resolved below,
    # so naming a partition (/dev/sda3) is caught just like naming the whole
    # disk it lives on.
    TARGET_NAME=$(lsblk -no PKNAME "{{DEVICE}}" 2>/dev/null | head -n1 || true)
    if [ -z "${TARGET_NAME}" ]; then
        TARGET_NAME=$(lsblk -no KNAME "{{DEVICE}}" 2>/dev/null | head -n1 || true)
    fi
    for mp in / /sysroot; do
        SRC=$(findmnt -no SOURCE "${mp}" 2>/dev/null | head -n1 || true)
        # btrfs reports the source as /dev/sdXn[/subvolume]; strip the suffix
        # so lsblk is handed a real device node.
        SRC="${SRC%%\[*}"
        case "${SRC}" in /dev/*) ;; *) continue ;; esac
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
    # Refuse a device with anything mounted off it. The MOUNTPOINTS column
    # requires util-linux >= 2.37, so fall back to the older MOUNTPOINT column
    # and refuse outright if neither can be read, rather than assuming the
    # device is idle.
    if MOUNTED=$(lsblk -n -o MOUNTPOINTS "{{DEVICE}}" 2>/dev/null); then
        MOUNT_COL="MOUNTPOINTS"
    elif MOUNTED=$(lsblk -n -o MOUNTPOINT "{{DEVICE}}" 2>/dev/null); then
        MOUNT_COL="MOUNTPOINT"
    else
        echo "ERROR: Could not read the mount state of {{DEVICE}} with lsblk." >&2
        echo "Refusing to write to a device whose mounts cannot be checked." >&2
        exit 1
    fi
    MOUNTED=$(printf '%s\n' "${MOUNTED}" | grep -v '^[[:space:]]*$' || true)
    if [ -n "${MOUNTED}" ]; then
        echo "ERROR: {{DEVICE}} has mounted partitions:" >&2
        lsblk -p -o "NAME,SIZE,${MOUNT_COL}" "{{DEVICE}}" >&2
        echo >&2
        echo "Unmount them first, e.g.:" >&2
        lsblk -p -n -l -o "NAME,${MOUNT_COL}" "{{DEVICE}}" \
            | awk 'NF>1 {printf "  udisksctl unmount -b %s\n", $1}' >&2
        exit 1
    fi
    mapfile -t IMGS < <(find dist/ -maxdepth 1 -type f -name 'bluefin-server-installer-*.raw.zst' | sort -V)
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
    echo "WARNING: All data on {{DEVICE}} will be COMPLETELY DESTROYED!"
    echo "Double-checking device information:"
    lsblk -p "{{DEVICE}}"
    echo
    read -p "Are you absolutely sure you want to write to {{DEVICE}}? [y/N] " -r CONFIRM
    if [[ ! "${CONFIRM}" =~ ^[yY](es)?$ ]]; then
        echo "Aborted."
        exit 1
    fi
    echo "Verifying ${IMG}..."
    if ! zstd -t "${IMG}"; then
        echo "ERROR: ${IMG} failed its integrity check; refusing to write it." >&2
        exit 1
    fi
    echo "Writing ${IMG} to {{DEVICE}}..."
    echo "Hashing ${IMG}..."
    # One decompression pass feeds both the digest and the byte count; a FIFO
    # plus an explicit wait keeps the hash file complete before it is read.
    HASH_DIR=$(mktemp -d)
    trap 'rm -rf "${HASH_DIR}"' EXIT
    mkfifo "${HASH_DIR}/stream"
    ( sha256sum < "${HASH_DIR}/stream" | cut -d' ' -f1 > "${HASH_DIR}/sha" ) &
    HASH_PID=$!
    EXPECT_BYTES=$(zstd -dc "${IMG}" | tee "${HASH_DIR}/stream" | wc -c | tr -d ' ')
    wait "${HASH_PID}"
    EXPECT_SHA=$(cat "${HASH_DIR}/sha")
    sudo bash -c 'set -o pipefail; zstd -dc "$1" | dd of="$2" bs=4M iflag=fullblock oflag=direct status=progress conv=fsync' \
        bash "${IMG}" "{{DEVICE}}"
    sudo blockdev --flushbufs "{{DEVICE}}"
    echo "Verifying ${EXPECT_BYTES} bytes read back from {{DEVICE}}..."
    ACTUAL_SHA=$(sudo dd if="{{DEVICE}}" bs=4M iflag=fullblock,count_bytes \
        count="${EXPECT_BYTES}" status=none | sha256sum | cut -d' ' -f1)
    if [ "${ACTUAL_SHA}" != "${EXPECT_SHA}" ]; then
        echo "ERROR: {{DEVICE}} does not contain what was written." >&2
        echo "  expected ${EXPECT_SHA}" >&2
        echo "  read     ${ACTUAL_SHA}" >&2
        echo "The medium did not retain the image. Replace it." >&2
        exit 1
    fi
    echo "Content verified: ${EXPECT_SHA}"
    echo "Relocating the GPT backup header to the end of {{DEVICE}}..."
    sudo sfdisk --relocate gpt-bak-std "{{DEVICE}}"
    echo "Verifying partition table on {{DEVICE}}..."
    sudo blockdev --rereadpt "{{DEVICE}}" 2>/dev/null || sudo partprobe "{{DEVICE}}" 2>/dev/null || {
        echo "ERROR: Failed to reread partition table on {{DEVICE}} after flashing!" >&2
        exit 1
    }
    sudo udevadm trigger --subsystem-match=block || true
    sudo udevadm settle --timeout=10 || true
    if lsblk -p -n -o PARTLABEL "{{DEVICE}}" 2>/dev/null | grep -Fxq 'bluefin-installer-data'; then
        echo "Verified: 'bluefin-installer-data' partition present on {{DEVICE}}."
    else
        echo "ERROR: 'bluefin-installer-data' partition label not detected on {{DEVICE}} after flashing!" >&2
        lsblk -p -o NAME,TYPE,PARTLABEL,SIZE "{{DEVICE}}" >&2 || true
        exit 1
    fi
    sudo sfdisk --verify "{{DEVICE}}"
    echo "Successfully flashed the Bluefin Server installer to {{DEVICE}}!"
# Build the installer artifacts, then run the reusable artifact smoke path.
[group('test')]
show-me-the-future:
    just build-installer
    just export-installer
    just test-installer-artifact

# INSTALLER_BOOT_MODE selects how the installer itself is started:
#   usb (default) — firmware (OVMF) boots the raw image off an emulated xHCI USB
#                   drive, the bare-metal USB install path.
#   pxe           — QEMU boots the exported PXE vmlinuz/initrd pair directly with
#                   -kernel/-initrd/-append, the network install path.
# Everything after the install (target partition check, booting the installed
# system, kiosk readiness probe) is identical for both modes.
# Install and reboot already-exported server artifacts in QEMU.
[group('test')]
test-installer-artifact:
    #!/usr/bin/env bash
    set -euo pipefail

    BOOT_MODE="${INSTALLER_BOOT_MODE:-usb}"
    case "${BOOT_MODE}" in
      usb|pxe) ;;
      *) echo "ERROR: INSTALLER_BOOT_MODE must be 'usb' or 'pxe', got '${BOOT_MODE}'." >&2; exit 1 ;;
    esac

    CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}"
    mkdir -p "$CACHE_DIR"
    WORKDIR="$(mktemp -d "${CACHE_DIR}/bluefin-show-future.XXXXXX")"
    trap 'rm -rf "$WORKDIR"' EXIT

    # The raw installer image is always needed; usb mode boots it through firmware
    # so it consumes nothing else. The PXE vmlinuz/initrd pair is only copied in pxe
    # mode, because copying it unconditionally would fail the usb test on hosts that
    # have the installer image but no PXE artifacts.
    cp dist/bluefin-server-installer-*.raw.zst "$WORKDIR/installer.raw.zst"
    if [ "${BOOT_MODE}" = "pxe" ]; then
      PXE_KERNEL=$(find dist/ -maxdepth 1 -type f -name 'bluefin-server-pxe-vmlinuz-*' | head -n1)
      PXE_INITRD=$(find dist/ -maxdepth 1 -type f -name 'bluefin-server-pxe-initrd-*.cpio.gz' | head -n1)
      if [ -z "${PXE_KERNEL}" ] || [ -z "${PXE_INITRD}" ]; then
        echo "ERROR: INSTALLER_BOOT_MODE=pxe needs an exported PXE kernel and initrd in dist/." >&2
        echo "Please run: just build-installer && just export-pxe" >&2
        exit 1
      fi
      cp "${PXE_KERNEL}" "$WORKDIR/installer.vmlinuz"
      cp "${PXE_INITRD}" "$WORKDIR/installer.initrd"
    fi
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
      /home/linuxbrew/.linuxbrew/Cellar/qemu/*/share/qemu/edk2-i386-vars.fd \
      /usr/share/edk2/ovmf/OVMF_VARS.fd \
      /usr/share/OVMF/OVMF_VARS.fd \
      /usr/share/OVMF/OVMF_VARS_4M.fd \
      /usr/share/edk2/x64/OVMF_VARS.4m.fd \
      /usr/share/qemu/edk2-x86_64-vars.fd \
      /usr/share/qemu/edk2-i386-vars.fd \
      /usr/share/qemu/OVMF_VARS.fd) \
      || true
    if [ -n "${OVMF_VARS}" ]; then
      cp "$OVMF_VARS" "$WORKDIR/ovmf-vars.fd"
    else
      # Hosts that ship only OVMF_CODE still boot: firmware initialises a blank
      # variable store on first use, it just has no preseeded boot entries.
      echo "WARNING: no OVMF_VARS template found; using a blank variable store sized to $OVMF_CODE" >&2
      truncate -s "$(stat -c '%s' "$OVMF_CODE")" "$WORKDIR/ovmf-vars.fd"
    fi

    SMP_CPUS="${SHOW_ME_THE_FUTURE_SMP:-$(nproc)}"
    MEM_SIZE="${SHOW_ME_THE_FUTURE_MEM:-8192}"

    echo "==> Booting installer media in QEMU (mode: ${BOOT_MODE})..."
    # ponytail: we want QEMU to exit cleanly after install. Since QEMU's -no-reboot
    # suspends/halts on reboot signals, we override systemd-sysinstall.service SuccessAction/FailureAction
    # to poweroff. When the installer triggers poweroff, QEMU terminates, and we boot into the newly installed OS.
    INSTALLER_TIMEOUT="${SHOW_ME_THE_FUTURE_INSTALL_TIMEOUT:-600}"
    INSTALL_ARGS=(
        -enable-kvm
        -m "${MEM_SIZE}"
        -cpu host
        -smp "${SMP_CPUS}"
        -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE"
        -drive if=pflash,format=raw,file="$WORKDIR/ovmf-vars.fd"
    )
    if [ "${BOOT_MODE}" = "usb" ]; then
      # Firmware boots the image's own bootloader, so the unattended flag has to
      # reach the UKI through systemd-stub rather than QEMU's -append.
      #
      # NOTE: systemd-stub deliberately ignores io.systemd.stub.kernel-cmdline-extra
      # when Secure Boot is enabled, because the SMBIOS string is not covered by the
      # signature. Point $OVMF_CODE at a secure-boot firmware build and this run
      # boots interactive instead of unattended, then sits there until
      # SHOW_ME_THE_FUTURE_INSTALL_TIMEOUT expires with a misleading "install did
      # not finish" failure. Use INSTALLER_BOOT_MODE=pxe (-append is always honoured)
      # to exercise unattended installs under Secure Boot firmware.
      INSTALL_ARGS+=(
        -device qemu-xhci,id=xhci
        -drive file="$WORKDIR/installer.raw",format=raw,if=none,id=installer-disk,readonly=on
        -device usb-storage,bus=xhci.0,drive=installer-disk,bootindex=1
        -drive file="$WORKDIR/target.raw",format=raw,if=none,id=target-disk
        -device virtio-blk-pci,drive=target-disk,bootindex=2
        -smbios "type=11,value=io.systemd.stub.kernel-cmdline-extra=console=tty0 console=ttyS0,,115200 rw unattended"
      )
    else
      INSTALL_ARGS+=(
        -drive file="$WORKDIR/installer.raw",format=raw,if=virtio,readonly=on
        -drive file="$WORKDIR/target.raw",format=raw,if=virtio
        -kernel "$WORKDIR/installer.vmlinuz"
        -initrd "$WORKDIR/installer.initrd"
        -append "systemd.unit=system-install.target console=tty0 console=ttyS0,115200 rw unattended"
      )
    fi
    timeout "${INSTALLER_TIMEOUT}" qemu-system-x86_64 \
        "${INSTALL_ARGS[@]}" \
        -nographic \
        -serial mon:stdio \
        -no-reboot < /dev/null

    echo "==> Validating target disk partitions after installer execution..."
    for tool in sfdisk jq; do
      command -v "$tool" >/dev/null 2>&1 \
        || { echo "ERROR: '$tool' is required to validate the target disk layout but is not installed." >&2; exit 1; }
    done

    # Keep sfdisk and jq failures distinguishable from "the installer did not
    # partition the disk", otherwise a broken host tool is misreported as a
    # failed install.
    if ! TARGET_TABLE=$(sfdisk --json "$WORKDIR/target.raw"); then
      echo "ERROR: sfdisk could not read a partition table from $WORKDIR/target.raw!" >&2
      sfdisk -l "$WORKDIR/target.raw" >&2 || true
      exit 1
    fi
    if ! TARGET_PARTS=$(jq -r '.partitiontable.partitions[]?.name // empty' <<<"$TARGET_TABLE"); then
      echo "ERROR: jq failed to parse the sfdisk JSON output!" >&2
      echo "$TARGET_TABLE" >&2
      exit 1
    fi
    if ! echo "$TARGET_PARTS" | grep -Fxq 'bluefin-server-root-a' || \
       ! echo "$TARGET_PARTS" | grep -Fxq 'var'; then
      echo "ERROR: Target disk did not receive expected partition layout from installer!" >&2
      echo "Observed partitions:" >&2
      echo "$TARGET_PARTS" >&2
      sfdisk -l "$WORKDIR/target.raw" >&2 || true
      exit 1
    fi
    echo "==> Target disk successfully partitioned and populated!"
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

    # The kiosk proxy publishes hostPort 8080 on the guest's loopback only
    # (files/k0s/manifests/kubestellar/41-kubestellar-kiosk-proxy.yaml), and a
    # QEMU hostfwd with an unspecified guest address is delivered to the guest's
    # DHCP address, never to 127.0.0.1 — so no host-side probe can reach it
    # without exposing the console on the guest's external interface. Probe from
    # inside the guest instead and report the verdict on the system console,
    # which is already captured in $SERIAL_LOG. The proxy terminates TLS with the
    # self-signed certificate baked into the k0s sysext, so the probe speaks
    # https and skips certificate verification, matching tests/e2e.
    READY_MARKER="KIOSK_CONSOLE_READY"
    READY_UNIT=$(base64 -w0 <<'UNIT'
    [Unit]
    Description=Report KubeStellar Console readiness on the system console
    ConditionPathExists=!/etc/initrd-release
    After=k0s-first-boot.service

    [Service]
    Type=oneshot
    TimeoutStartSec=infinity
    StandardOutput=journal+console
    ExecStart=/usr/bin/bash -c 'echo "<4>kiosk-ready: polling https://127.0.0.1:8080"; i=0; until [ "$(curl --silent --fail --insecure --max-time 2 https://127.0.0.1:8080/healthz | jq -r .status)" = ok ] && [ "$(curl --silent --fail --insecure --max-time 2 --output /dev/null --write-out "%%{http_code}" https://127.0.0.1:8080/)" = 200 ]; do i=$((i+1)); if [ $((i %% 15)) -eq 0 ]; then echo "<4>kiosk-ready: waiting k0s=$(systemctl is-active k0scontroller.service) hz=$(curl -sk -o /dev/null -w "%%{http_code}" --max-time 2 https://127.0.0.1:8080/healthz) root=$(curl -sk -o /dev/null -w "%%{http_code}" --max-time 2 https://127.0.0.1:8080/) pods=$(k0s kubectl get pods -A --no-headers 2>/dev/null | wc -l) running=$(k0s kubectl get pods -A --no-headers 2>/dev/null | grep -c Running)"; k0s kubectl get pods -A --no-headers 2>/dev/null | sed "s/^/<4>kiosk-pods: /"; k0s kubectl get nodes -o wide --no-headers 2>/dev/null | sed "s/^/<4>kiosk-node: /"; k0s kubectl get events -A --no-headers 2>/dev/null | grep -v FailedScheduling | tail -n 8 | sed "s/^/<4>kiosk-events: /"; journalctl -u k0scontroller --no-pager -n 800 2>/dev/null | grep -iE "error|fail|taint" | grep -vE "FailedScheduling|apply.*retrying" | tail -n 8 | sed "s/^/<4>kiosk-k0s: /"; fi; sleep 2; done; echo "<4>KIOSK_CONSOLE_READY"'
    UNIT
    )

    echo "==> Booting the installed server in QEMU (background)..."
    qemu-system-x86_64 \
        -enable-kvm \
        -m "${MEM_SIZE}" \
        -cpu host \
        -smp "${SMP_CPUS}" \
        -drive file="$WORKDIR/target.raw",format=raw,if=virtio \
        -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
        -drive if=pflash,format=raw,file="$WORKDIR/ovmf-vars.fd" \
        -nic user,model=virtio-net-pci \
        -smbios "type=11,value=io.systemd.credential.binary:fstab.extra=L2Rldi9kaXNrL2J5LXBhcnRsYWJlbC92YXIgL3ZhciB4ZnMgZGVmYXVsdHMgMCAwCg==" \
        -smbios "type=11,value=io.systemd.credential.binary:systemd.extra-unit.bluefin-kiosk-ready.service=${READY_UNIT}" \
        -smbios "type=11,value=io.systemd.stub.kernel-cmdline-extra=console=tty0 console=ttyS0,,115200 systemd.mask=systemd-firstboot.service systemd.mask=systemd-homed-firstboot.service systemd.wants=bluefin-kiosk-ready.service" \
        -nographic \
        -serial file:"$SERIAL_LOG" \
        -monitor none &
    TARGET_QEMU_PID=$!

    DEADLINE_SECS="${SHOW_ME_THE_FUTURE_DEADLINE:-${SHOW_ME_THE_FUTURE_TIMEOUT:-600}}"
    START_TIME=$(date +%s)
    echo "==> Polling KubeStellar Console readiness from inside the guest (deadline: ${DEADLINE_SECS}s)..."

    while true; do
      if ! kill -0 "$TARGET_QEMU_PID" 2>/dev/null; then
        echo "ERROR: Target QEMU process ($TARGET_QEMU_PID) died unexpectedly!" >&2
        if [ -f "$SERIAL_LOG" ]; then
          echo "==> Serial log tail (last 100 lines):" >&2
          tail -n 100 "$SERIAL_LOG" >&2
        fi
        exit 1
      fi

      if grep -q "$READY_MARKER" "$SERIAL_LOG" 2>/dev/null; then
        echo "==> KubeStellar Console is healthy: /healthz status ok, / returned HTTP 200"
        break
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

# This is the default mode of test-installer-artifact; the recipe exists so the USB
# boot path is discoverable by name.
# Boot the exported installer media via firmware (OVMF) as an xHCI USB drive.
[group('test')]
test-installer-boot-usb:
    INSTALLER_BOOT_MODE=usb just test-installer-artifact

# `just export-pxe` only checks that the two files exist, so this recipe is the only
# thing that proves they still boot and install.
# Boot the exported PXE kernel/initrd pair directly (QEMU -kernel/-initrd/-append).
[group('test')]
test-installer-boot-pxe:
    INSTALLER_BOOT_MODE=pxe just test-installer-artifact

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
        /home/linuxbrew/.linuxbrew/Cellar/qemu/*/share/qemu/edk2-i386-vars.fd \
        /usr/share/edk2/ovmf/OVMF_VARS.fd \
        /usr/share/OVMF/OVMF_VARS.fd \
        /usr/share/OVMF/OVMF_VARS_4M.fd \
        /usr/share/edk2/x64/OVMF_VARS.4m.fd \
        /usr/share/qemu/edk2-x86_64-vars.fd \
        /usr/share/qemu/edk2-i386-vars.fd \
        /usr/share/qemu/OVMF_VARS.fd) \
        || true
      if [ -n "${OVMF_TEMPLATE}" ]; then
        cp "$OVMF_TEMPLATE" "$OVMF_VARS"
      else
        # Hosts that ship only OVMF_CODE still boot: firmware initialises a blank
        # variable store on first use, it just has no preseeded boot entries.
        echo "WARNING: no OVMF_VARS template found; using a blank variable store sized to $OVMF_CODE" >&2
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
      # The interactive installer is driven by hand, so it can be aborted or
      # fail without a non-zero exit here. Marking the install complete in that
      # case caches a broken target that every later run boots forever. Gate
      # the marker on the partition labels files/repart.d creates; an aborted
      # install now fails loudly and re-runs the installer next invocation
      # instead of silently booting an unusable disk.
      echo "==> Verifying target partition layout before marking installation complete..."
      TARGET_PARTS=$(sfdisk --json "$TARGET_RAW" 2>/dev/null | jq -r '.partitiontable.partitions[]?.name // empty' || true)
      if ! echo "$TARGET_PARTS" | grep -Fxq 'bluefin-server-root-a' || \
         ! echo "$TARGET_PARTS" | grep -Fxq 'var'; then
        echo "ERROR: Target disk $TARGET_RAW does not contain expected partitions (bluefin-server-root-a, var)!" >&2
        echo "The installation did not complete; re-run 'just install-vm' to install again." >&2
        echo "Observed partitions:" >&2
        echo "$TARGET_PARTS" >&2
        sfdisk -l "$TARGET_RAW" >&2 || true
        exit 1
      fi
      touch "$INSTALL_COMPLETE"
    fi

    echo "==> Booting the installed kiosk..."
    SERIAL_LOG="$STATE_DIR/kiosk-serial.log"
    : > "$SERIAL_LOG"

    # The kiosk proxy binds hostPort 8080 on the guest's loopback interface only
    # (files/k0s/manifests/kubestellar/41-kubestellar-kiosk-proxy.yaml) and
    # terminates TLS (files/k0s/kiosk/nginx.conf, `listen 8080 ssl`). A
    # QEMU/libslirp hostfwd with an unspecified guest address is delivered to
    # the guest's DHCP address, never to 127.0.0.1, so a host-side forward of
    # 8080 can never reach the proxy, and a plaintext probe would fail against
    # its TLS listener regardless. Probe readiness from inside the guest
    # instead and report the verdict on the system console, which is captured
    # in $SERIAL_LOG — the same in-guest-probe approach proposed for
    # test-installer-artifact in #220. Host access, when wanted, goes over
    # the existing SSH hostfwd rather than a direct (non-working) 8080
    # forward. The readiness check deliberately does not parse the /healthz
    # response body: curl --fail already fails on a non-2xx response, which
    # is exactly "healthz ok and / returns 200", and it avoids embedding
    # quotes inside a systemd ExecStart= line, where escaping rules differ
    # from a plain shell.
    # The installed image carries no fstab entry for /var and gpt-auto cannot
    # mount it, so /var (which holds k0s state and therefore the kiosk proxy)
    # stays empty unless the same SMBIOS fstab.extra credential
    # test-installer-artifact passes is supplied here too. Without it k0s never
    # starts and the readiness marker never appears.
    READY_MARKER="KIOSK_CONSOLE_READY"
    READY_UNIT=$(base64 -w0 <<'UNIT'
    [Unit]
    Description=Report KubeStellar Console readiness on the system console
    ConditionPathExists=!/etc/initrd-release
    After=k0s-first-boot.service

    [Service]
    Type=oneshot
    TimeoutStartSec=infinity
    StandardOutput=journal+console
    ExecStart=/usr/bin/bash -c 'until curl --silent --fail --insecure --max-time 2 --output /dev/null https://127.0.0.1:8080/healthz && curl --silent --fail --insecure --max-time 2 --output /dev/null https://127.0.0.1:8080/; do sleep 2; done; echo KIOSK_CONSOLE_READY'
    UNIT
    )

    qemu-system-x86_64 \
      -enable-kvm \
      -m "${MEM_SIZE}" \
      -cpu host \
      -smp "${SMP_CPUS}" \
      -drive file="$TARGET_RAW",format=raw,if=virtio \
      -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
      -drive if=pflash,format=raw,file="$OVMF_VARS" \
      -nic user,model=virtio-net-pci,hostfwd=tcp::2222-:22,hostfwd=tcp::6443-:6443 \
      -smbios "type=11,value=io.systemd.credential.binary:fstab.extra=L2Rldi9kaXNrL2J5LXBhcnRsYWJlbC92YXIgL3ZhciB4ZnMgZGVmYXVsdHMgMCAwCg==" \
      -smbios "type=11,value=io.systemd.credential.binary:systemd.extra-unit.bluefin-kiosk-ready.service=${READY_UNIT}" \
      -smbios "type=11,value=io.systemd.stub.kernel-cmdline-extra=console=tty0 console=ttyS0,,115200 systemd.wants=bluefin-kiosk-ready.service" \
      -serial file:"$SERIAL_LOG" &
    QEMU_PID=$!
    cleanup() {
      if kill -0 "$QEMU_PID" 2>/dev/null; then
        kill "$QEMU_PID"
        wait "$QEMU_PID" || true
      fi
    }
    trap cleanup INT TERM

    READY_DEADLINE_SECS="${INSTALL_VM_READY_DEADLINE:-600}"
    READY_START_TIME=$(date +%s)
    echo "==> Waiting for the KubeStellar Console to become ready inside the guest (deadline: ${READY_DEADLINE_SECS}s)..."
    until grep -q "$READY_MARKER" "$SERIAL_LOG" 2>/dev/null; do
      if ! kill -0 "$QEMU_PID" 2>/dev/null; then
        echo "ERROR: QEMU process ($QEMU_PID) died before the kiosk became ready!" >&2
        if [ -f "$SERIAL_LOG" ]; then
          echo "==> Serial log tail (last 100 lines):" >&2
          tail -n 100 "$SERIAL_LOG" >&2
        fi
        wait "$QEMU_PID"
        exit 1
      fi

      NOW=$(date +%s)
      ELAPSED=$((NOW - READY_START_TIME))
      if [ "$ELAPSED" -ge "$READY_DEADLINE_SECS" ]; then
        echo "ERROR: Timed out after ${READY_DEADLINE_SECS}s waiting for KubeStellar Console readiness!" >&2
        if [ -f "$SERIAL_LOG" ]; then
          echo "==> Serial log tail (last 100 lines):" >&2
          tail -n 100 "$SERIAL_LOG" >&2
        fi
        cleanup
        exit 1
      fi

      sleep 2
    done

    echo "==> KubeStellar Console is ready!"
    echo "==> The kiosk proxy binds the guest's loopback interface only and terminates"
    echo "==> TLS with a self-signed certificate, so it is not directly reachable from"
    echo "==> the host. To view it in a host browser, start sshd inside the VM"
    echo "==> (systemctl start sshd) and open a tunnel over the forwarded SSH port:"
    echo "==>   ssh -p 2222 -L 8080:127.0.0.1:8080 <your-user>@127.0.0.1"
    echo "==> then browse https://localhost:8080/ and accept the self-signed certificate."
    wait "$QEMU_PID"

# Set up KubeStellar kc-agent for the user in ONE command.
[group('test')]
setup-kubestellar ORIGIN="http://localhost:8080,http://127.0.0.1:8080":
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
test-e2e-browser CONSOLE_URL="http://127.0.0.1:8080":
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
