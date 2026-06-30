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
# Build and export both pure DDI artifacts (OS DDI payload + live installer media).
[group('build')]
build:
    just build-ddi
    just export-ddi
    just build-installer
    just export-installer

# ── Export ────────────────────────────────────────────────────────────
# Export both pure DDI artifacts to dist/.
[group('build')]
export:
    just export-ddi
    just export-installer

# Push the locally built :latest under all derived tags to a given repo ref.
# Usage: just tag-push ghcr.io/projectbluefin/base
[group('build')]
tag-push REPO:
    #!/usr/bin/env bash
    set -euo pipefail
    SRC="{{image_registry}}/{{image_name}}:latest"
    while read -r t; do
        {{sudo_cmd}} podman tag "$SRC" "{{REPO}}:$t"
        {{sudo_cmd}} podman push "{{REPO}}:$t"
        echo "==> pushed {{REPO}}:$t"
    done < <(just tags)

# Push the locally built image to Quay.io with zstd:chunked compression.
# Usage: just push-quay quay.io/yourusername/base
[group('build')]
push-quay REPO:
    #!/usr/bin/env bash
    set -euo pipefail
    SRC="{{image_registry}}/{{image_name}}:latest"
    while read -r t; do
        echo "==> Tagging $SRC to {{REPO}}:$t..."
        {{sudo_cmd}} podman tag "$SRC" "{{REPO}}:$t"
        echo "==> Pushing {{REPO}}:$t with zstd:chunked compression..."
        {{sudo_cmd}} podman push --compression-format zstd:chunked --force-compression "{{REPO}}:$t"
    done < <(just tags)

# ── Verify ────────────────────────────────────────────────────────────
# Assert the image meets its contract: distroless images have no shell;
# all images ship CA certs + tzdata (except static-tier Go binaries which
# carry these in their own layer); lab-runner explicitly keeps a shell.
[group('test')]
verify:
    #!/usr/bin/env bash
    set -euo pipefail
    REF="{{image_registry}}/{{image_name}}:latest"
    IMG="{{image_name}}"

    {{sudo_cmd}} podman create --name verify-base "$REF" /verify-placeholder >/dev/null
    trap '{{sudo_cmd}} podman rm -f verify-base >/dev/null 2>&1 || true' EXIT
    LISTING="$(mktemp)"
    {{sudo_cmd}} podman export verify-base | tar -tf - > "$LISTING"

    GATE=1
    if [ "$IMG" = "lab-runner" ]; then
        echo "==> [${GATE}/${GATE}] shell present (lab-runner is intentionally shell-enabled)"
        if ! grep -qE '(^|/)bash$' "$LISTING"; then
            echo "FAIL: bash missing from lab-runner — shell must be present"; exit 1
        fi
        echo "OK: bash present"
        TOTAL=1
    else
        TOTAL=4
        echo "==> [1/${TOTAL}] distroless: no shell present"
        if grep -qE '(^|/)(ba)?sh$' "$LISTING"; then
            echo "FAIL: a shell binary is present in the rootfs"; exit 1
        fi
        echo "OK: no shell"

        echo "==> [2/${TOTAL}] CA certificate bundle present"
        if ! grep -qE '^etc/(pki/tls/certs/ca-bundle\.crt|ssl/certs/ca-certificates\.crt)$' "$LISTING"; then
            echo "FAIL: no CA bundle file found"; exit 1
        fi
        echo "OK: CA bundle present"

        echo "==> [3/${TOTAL}] tzdata present"
        if ! grep -qE '^usr/share/zoneinfo/UTC$' "$LISTING"; then
            echo "FAIL: tzdata (zoneinfo/UTC) missing"; exit 1
        fi
        echo "OK: tzdata present"

        echo "==> [4/${TOTAL}] slim: bloat must NOT be present (terminfo, sanitizers, fortran)"
        if grep -qE 'usr/share/terminfo/|/lib(asan|tsan|lsan|ubsan|hwasan|gfortran)\.so' "$LISTING"; then
            echo "FAIL: slim bloat present — slim recipe regressed"; exit 1
        fi
        echo "OK: slim bloat removed"
    fi

    echo "==> smoke test (executing binary)"
    if [ "$IMG" = "skopeo" ]; then
        if ! {{sudo_cmd}} podman run --rm "$REF" skopeo --version >/dev/null; then
            echo "FAIL: skopeo failed to execute"; exit 1
        fi
        echo "OK: skopeo executes successfully"
    elif [ "$IMG" = "lab-runner" ]; then
        if ! {{sudo_cmd}} podman run --rm "$REF" -c "curl --version && git --version && jq --version && python3 --version" >/dev/null; then
            echo "FAIL: lab-runner tools failed to execute"; exit 1
        fi
        echo "OK: lab-runner tools execute successfully"
    fi

    echo "==> verify passed (${IMG})"

# -- Homebrew nspawn machine image -------------------------------------------
# NOT distroless: a full dev-environment rootfs tarball for systemd-nspawn /
# machinectl import-tar (see docs/skills/nspawn-machine-image.md).
brew_version := "6.0.3"

# Build the brew nspawn machine image (rootfs tarball, not OCI).
[group('brew')]
build-brew:
    just bst build oci/brew-nspawn.bst

# Export the rootfs tarball + SHA256SUMS to dist/.
[group('brew')]
export-brew: build-brew
    rm -rf dist
    just bst artifact checkout oci/brew-nspawn.bst --directory dist
    @echo "==> wrote:" && ls -lh dist/

# Verify the tarball is a machinectl-shaped rootfs with the required contents.
[group('brew')]
verify-brew: export-brew
    #!/usr/bin/env bash
    set -euo pipefail
    T="dist/homebrew-env-{{brew_version}}.tar.zst"
    [ -f "$T" ] || { echo "FAIL: $T not found"; exit 1; }
    L="$(mktemp)"
    tar --zstd -tf "$T" > "$L"
    fail=0
    # usr-merge: /bin and /sbin are symlinks to usr/bin, so check the real paths.
    # Run smoke checks inside the brew machine container.
    for p in ./usr/bin/bash ./usr/bin/ruby ./usr/bin/git ./usr/bin/curl \
             ./usr/bin/patchelf \
             ./usr/lib/systemd/systemd ./usr/bin/init \
             ./home/linuxbrew/.linuxbrew/bin/brew \
             ./home/linuxbrew/.linuxbrew/Homebrew/bin/brew \
             ./etc/passwd ./etc/machine-id ./etc/locale.conf \
             ./etc/subuid ./etc/subgid; do
        if grep -qxF "$p" "$L"; then echo "OK   $p"; else echo "MISS $p"; fail=1; fi
    done
    # linuxbrew user must be present at uid 1001.
    if tar --zstd -xf "$T" -O ./etc/passwd | grep -q '^linuxbrew:x:1001:1001:'; then
        echo "OK   linuxbrew uid 1001 in /etc/passwd"
    else
        echo "MISS linuxbrew uid 1001 in /etc/passwd"; fail=1
    fi
    [ "$fail" -eq 0 ] && echo "==> verify-brew passed" || { echo "==> verify-brew FAILED"; exit 1; }

# -- DDI live installer -------------------------------------------------------
# Produces a bootable GPT disk image that runs systemd-repart to install
# Bluefin Server onto a target disk (see docs/skills/ddi-installer.md).
# OS DDI payload image and live installer media are both first-class artifacts.
# NOTE: build-installer/export-installer are local development commands.
# Release publication is delegated to testing-lab by
# .github/workflows/release-installer.yml.

# Build the OS DDI payload filesystem image.
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

# Export the installer disk image + SHA256SUMS to dist/.
[group('installer')]
export-installer: build-installer
    rm -rf dist
    just bst artifact checkout oci/bluefin-server-installer.bst --directory dist
    @echo "==> wrote:" && ls -lh dist/

# Build, install, and reboot the server in QEMU using the raw installer disk.
[group('test')]
show-me-the-future:
    #!/usr/bin/env bash
    set -euo pipefail

    CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}"
    mkdir -p "$CACHE_DIR"
    WORKDIR="$(mktemp -d "${CACHE_DIR}/bluefin-show-future.XXXXXX")"
    trap 'rm -rf "$WORKDIR"' EXIT

    just build-ddi
    just export-ddi
    # Stash DDI before export-installer wipes dist/.
    cp dist/ddi/bluefin-server-ddi-*.raw.zst "$WORKDIR/ddi.raw.zst"
    just build-installer
    just export-installer

    cp dist/bluefin-server-installer-*.raw.zst "$WORKDIR/installer.raw.zst"
    zstd -d "$WORKDIR/installer.raw.zst" -o "$WORKDIR/installer.raw"
    # DDI raw filesystem image passed as /dev/vdc inside the installer VM.
    # The installer detects this large read-only device and uses it directly
    # via CopyBlocks= instead of downloading from GitHub (avoids tmpfs OOM).
    zstd -d "$WORKDIR/ddi.raw.zst" -o "$WORKDIR/ddi.raw"
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
    qemu-system-x86_64 \
        -enable-kvm \
        -m 4096 \
        -cpu host \
        -smp 2 \
        -drive file="$WORKDIR/installer.raw",format=raw,if=virtio,readonly=on \
        -drive file="$WORKDIR/target.raw",format=raw,if=virtio \
        -drive file="$WORKDIR/ddi.raw",format=raw,if=virtio,readonly=on \
        -netdev user,id=n1,hostname=bluefin-installer \
        -device virtio-net-pci,netdev=n1 \
        -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
        -drive if=pflash,format=raw,file="$WORKDIR/ovmf-vars.fd" \
        -nographic \
        -serial mon:stdio

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

# Generate a BST-native SBOM (SPDX 2.3) using buildstream-sbom.
[group('test')]
sbom variant="base":
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{variant}}" in
        base)       ELEMENT="oci/base.bst";        SPDX_NAME="base" ;;
        static)     ELEMENT="oci/static.bst";      SPDX_NAME="static" ;;
        skopeo)     ELEMENT="oci/skopeo.bst";      SPDX_NAME="skopeo" ;;
        lab-runner) ELEMENT="oci/lab-runner.bst";  SPDX_NAME="lab-runner" ;;
        *) echo "ERROR: unknown variant '{{variant}}'" >&2; exit 1 ;;
    esac
    OUTFILE="${SPDX_NAME}.spdx.json"
    mkdir -p "${HOME}/.cache/buildstream"
    mkdir -p "${HOME}/.cache/pip"
    GIT_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"

    {{sudo_cmd}} podman run --rm \
        --privileged \
        --device /dev/fuse \
        --network=host \
        -v "{{justfile_directory()}}:/src:rw" \
        -v "${HOME}/.cache/buildstream:/root/.cache/buildstream:rw" \
        -v "${HOME}/.cache/pip:/root/.cache/pip:rw" \
        -w /src \
        -e ELEMENT="${ELEMENT}" \
        -e SPDX_NAME="${SPDX_NAME}" \
        -e OUTFILE="${OUTFILE}" \
        -e GIT_SHA="${GIT_SHA}" \
        "{{bst2_image}}" \
        bash -c '
            for attempt in 1 2 3; do
                pip install --quiet \
                    git+https://gitlab.com/BuildStream/buildstream-sbom.git@0706fec3bedf6f73bd9d2fed32c2aed585feef8d \
                    && break
                echo "buildstream-sbom install failed (attempt ${attempt}/3); retrying in 5s..."
                [ "${attempt}" -lt 3 ] && sleep 5
            done
            buildstream-sbom "${ELEMENT}" \
                --spdx-name "${SPDX_NAME}" \
                --spdx-namespace "https://github.com/projectbluefin/fsdk-containers/sbom/${GIT_SHA}/${SPDX_NAME}" \
                --spdx-creator "Tool: buildstream-sbom" \
                --spdx-creator "Organization: projectbluefin" \
                --deps all \
                --output "/src/${OUTFILE}"
        '

# Generate BuildStream-native SBOMs for all images in a single optimized container run
[group('test')]
sboms:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "${HOME}/.cache/buildstream"
    mkdir -p "${HOME}/.cache/pip"
    GIT_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"

    {{sudo_cmd}} podman run --rm \
        --privileged \
        --device /dev/fuse \
        --network=host \
        -v "{{justfile_directory()}}:/src:rw" \
        -v "${HOME}/.cache/buildstream:/root/.cache/buildstream:rw" \
        -v "${HOME}/.cache/pip:/root/.cache/pip:rw" \
        -w /src \
        -e GIT_SHA="${GIT_SHA}" \
        "{{bst2_image}}" \
        bash -c '
            for attempt in 1 2 3; do
                pip install --quiet \
                    git+https://gitlab.com/BuildStream/buildstream-sbom.git@0706fec3bedf6f73bd9d2fed32c2aed585feef8d \
                    && break
                echo "buildstream-sbom install failed (attempt ${attempt}/3); retrying in 5s..."
                [ "${attempt}" -lt 3 ] && sleep 5
            done
            for img in base static skopeo lab-runner; do
                case "$img" in
                    base)       ELEMENT="oci/base.bst" ;;
                    static)     ELEMENT="oci/static.bst" ;;
                    skopeo)     ELEMENT="oci/skopeo.bst" ;;
                    lab-runner) ELEMENT="oci/lab-runner.bst" ;;
                esac
                echo "==> Generating SBOM for ${img}..."
                buildstream-sbom "${ELEMENT}" \
                    --spdx-name "${img}" \
                    --spdx-namespace "https://github.com/projectbluefin/fsdk-containers/sbom/${GIT_SHA}/${img}" \
                    --spdx-creator "Tool: buildstream-sbom" \
                    --spdx-creator "Organization: projectbluefin" \
                    --deps all \
                    --output "/src/${img}.spdx.json"
            done
        '

