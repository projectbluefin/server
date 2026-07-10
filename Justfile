# List available commands
[group('info')]
default:
    @just --list

# -- Configuration ---------------------------------------------------------
export image_name := env("BUILD_IMAGE_NAME", "bluefin-server-installer")
export image_registry := env("BUILD_IMAGE_REGISTRY", "ghcr.io/projectbluefin")

# Same bst2 container image FSDK/dakota CI uses -- pinned by SHA.
export bst2_image := env("BST2_IMAGE", "registry.gitlab.com/freedesktop-sdk/infrastructure/freedesktop-sdk-docker-images/bst2:64eb0b4930d57a92710822898fb73af6cc1ae35d")

# OCI metadata (dynamic labels), injected at export time.
export OCI_IMAGE_CREATED := env("OCI_IMAGE_CREATED", "")
export OCI_IMAGE_REVISION := env("OCI_IMAGE_REVISION", "")

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
        bash -c 'bst --colors "$@"' -- --no-interactive ${BST_FLAGS:-} {{ARGS}}

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
    just bst show --deps all oci/bluefin-server-ddi.bst
    just bst show --deps all oci/bluefin-server-installer.bst

# ── Build ─────────────────────────────────────────────────────────────
# Build and export the installer (DDI is embedded; built as a dependency).
[group('build')]
build:
    just build-installer
    just export-installer

# ── Export ────────────────────────────────────────────────────────────
# Export installer disk image to dist/.
[group('build')]
export:
    just export-installer

# -- DDI live installer -------------------------------------------------------
# Produces a bootable GPT disk image that runs systemd-repart to install
# Bluefin Server onto a target disk (see docs/skills/ddi-installer.md).
# The DDI payload is embedded as a data partition; no network required.
# NOTE: build-installer/export-installer are local development commands.
# Release publication is delegated to testing-lab by
# .github/workflows/release-installer.yml.

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

# Validate the installer element graph without building.
[group('installer')]
validate-installer:
    just bst show --deps all oci/bluefin-server-installer.bst

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
[group('installer')]
export-installer: build-installer
    rm -rf dist
    just bst artifact checkout oci/bluefin-server-installer.bst --directory dist
    @echo "==> wrote:" && ls -lh dist/

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
    IMG=$(find dist/ -type f -name 'bluefin-server-installer-*.raw.zst' | head -n1)
    if [ -z "${IMG}" ]; then
        echo "ERROR: No exported installer found in dist/." >&2
        echo "Please run: just build-installer && just export-installer" >&2
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
    sudo sh -c "zstd -dc ${IMG} | dd of={{DEVICE}} bs=4M iflag=fullblock oflag=direct status=progress conv=fsync"
    echo "Successfully flashed the Bluefin Server installer to {{DEVICE}}!"

# Build, install, and reboot the server in QEMU using the raw installer disk.
[group('test')]
show-me-the-future:
    #!/usr/bin/env bash
    set -euo pipefail

    CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}"
    mkdir -p "$CACHE_DIR"
    WORKDIR="$(mktemp -d "${CACHE_DIR}/bluefin-show-future.XXXXXX")"
    trap 'rm -rf "$WORKDIR"' EXIT

    just build-installer
    just export-installer

    cp dist/bluefin-server-installer-*.raw.zst "$WORKDIR/installer.raw.zst"
    zstd -d "$WORKDIR/installer.raw.zst" -o "$WORKDIR/installer.raw"
    truncate -s 16G "$WORKDIR/target.raw"

    OVMF_CODE=""
    for candidate in \
        /home/linuxbrew/.linuxbrew/Cellar/qemu/*/share/qemu/edk2-x86_64-code.fd \
        /home/linuxbrew/.linuxbrew/Cellar/qemu/*/share/qemu/edk2-x86_64-secure-code.fd \
        /usr/share/edk2/ovmf/OVMF_CODE.fd \
        /usr/share/OVMF/OVMF_CODE.fd \
        /usr/share/OVMF/OVMF_CODE_4M.fd \
        /usr/share/edk2/x64/OVMF_CODE.4m.fd \
        /usr/share/qemu/OVMF_CODE.fd; do
        if [ -f "$candidate" ]; then
            OVMF_CODE="$candidate"
            break
        fi
    done
    [ -n "$OVMF_CODE" ] || { echo "ERROR: OVMF_CODE not found"; exit 1; }

    OVMF_VARS=""
    for candidate in \
        /home/linuxbrew/.linuxbrew/Cellar/qemu/*/share/qemu/edk2-x86_64-vars.fd \
        /usr/share/edk2/ovmf/OVMF_VARS.fd \
        /usr/share/OVMF/OVMF_VARS.fd \
        /usr/share/OVMF/OVMF_VARS_4M.fd \
        /usr/share/edk2/x64/OVMF_VARS.4m.fd \
        /usr/share/qemu/OVMF_VARS.fd; do
        if [ -f "$candidate" ]; then
            OVMF_VARS="$candidate"
            break
        fi
    done
    if [ -n "$OVMF_VARS" ]; then
        cp "$OVMF_VARS" "$WORKDIR/ovmf-vars.fd"
    else
        truncate -s "$(stat -c '%s' "$OVMF_CODE")" "$WORKDIR/ovmf-vars.fd"
    fi

    echo "==> Booting installer media in QEMU..."
    # ponytail: we want QEMU to exit cleanly after install. Since QEMU's -no-reboot
    # suspends/halts on reboot signals, we override systemd-sysinstall.service SuccessAction/FailureAction
    # to poweroff. When the installer triggers poweroff, QEMU terminates, and we boot into the newly installed OS.
    qemu-system-x86_64 \
        -enable-kvm \
        -m 4096 \
        -cpu host \
        -smp 2 \
        -drive file="$WORKDIR/installer.raw",format=raw,if=virtio,readonly=on \
        -drive file="$WORKDIR/target.raw",format=raw,if=virtio \
        -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
        -drive if=pflash,format=raw,file="$WORKDIR/ovmf-vars.fd" \
        -nographic \
        -serial mon:stdio \
        -no-reboot < /dev/null

    echo "==> Rebooting into the installed server..."
    qemu-system-x86_64 \
        -enable-kvm \
        -m 4096 \
        -cpu host \
        -smp 2 \
        -drive file="$WORKDIR/target.raw",format=raw,if=virtio \
        -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
        -drive if=pflash,format=raw,file="$WORKDIR/ovmf-vars.fd" \
        -nographic \
        -serial mon:stdio
