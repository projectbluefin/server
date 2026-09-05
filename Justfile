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

# Verify the BuildStream release version matches the pinned FSDK point release.
[group('info')]
check-version:
    #!/usr/bin/env bash
    set -euo pipefail
    project_version="$(grep -oE 'release-version: "[0-9]+\.[0-9]+\.[0-9]+"' project.conf | sed -E 's/.*"([0-9]+\.[0-9]+\.[0-9]+)"/\1/')"
    fsdk_version="$(grep -oE 'freedesktop-sdk-[0-9]+\.[0-9]+\.[0-9]+' elements/freedesktop-sdk.bst | head -1 | sed 's/freedesktop-sdk-//')"
    [[ "$project_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "invalid project release-version: $project_version" >&2; exit 1; }
    [[ "$fsdk_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "invalid FSDK release: $fsdk_version" >&2; exit 1; }
    [[ "$project_version" == "$fsdk_version" ]] || { echo "release version mismatch: project.conf=$project_version FSDK=$fsdk_version" >&2; exit 1; }

# Print the FSDK-derived point release used for asset versioning.
[group('info')]
version: check-version
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
validate: check-version
    just bst show --deps all oci/bluefin-server-ddi.bst
    just bst show --deps all oci/bluefin-server-installer.bst
    just bst show --deps all oci/k3s-sysext.bst

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

# Export the installer disk image + SHA256SUMS to dist/.
# bst artifact checkout requires an empty destination, and dist/ may
# already hold dist/ddi/ or dist/sysext/ from earlier export steps, so
# check out into a clean staging directory and move the files over.
[group('installer')]
export-installer: build-installer
    rm -rf dist/installer-checkout
    mkdir -p dist dist/installer-checkout
    rm -f dist/bluefin-server-installer-*.raw.zst dist/bluefin-server-*.efi dist/SHA256SUMS
    just bst artifact checkout oci/bluefin-server-installer.bst --directory /src/dist/installer-checkout
    mv dist/installer-checkout/* dist/
    rm -rf dist/installer-checkout
    @echo "==> wrote:" && ls -lh dist/

# -- k3s systemd-sysext -------------------------------------------------------
# Produces a systemd-sysext extension image for k3s.

# Build the k3s systemd-sysext image.
[group('sysext')]
build-sysext:
    just bst build oci/k3s-sysext.bst

# Export the k3s systemd-sysext image + SHA256SUMS to dist/sysext/.
# The artifact checkout also emits an uncompressed .raw; only the
# versioned .raw.zst release asset and its SHA256SUMS are published.
[group('sysext')]
export-sysext: build-sysext
    rm -rf dist/sysext dist/sysext-checkout
    mkdir -p dist/sysext-checkout dist/sysext
    just bst artifact checkout oci/k3s-sysext.bst --directory /src/dist/sysext-checkout
    cp dist/sysext-checkout/k3s-*.raw.zst dist/sysext/
    cp dist/sysext-checkout/SHA256SUMS dist/sysext/
    rm -rf dist/sysext-checkout
    @echo "==> wrote k3s sysext:" && ls -lh dist/sysext/

# -- SBOM --------------------------------------------------------------------
# BuildStream-native SPDX SBOMs via buildstream-sbom, generated from the
# build graph. Post-hoc rootfs scanners are useless here (no RPM/dpkg
# database), so the build graph is the only authoritative package source.
# See docs/skills/signing-and-sbom.md.

# Generate a BuildStream-native SPDX SBOM for one artifact:
# bluefin-server-ddi, bluefin-server-installer, or k3s.
[group('sbom')]
sbom artifact="bluefin-server-ddi":
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{artifact}}" in
        bluefin-server-ddi)       ELEMENT="oci/bluefin-server-ddi.bst" ;;
        bluefin-server-installer) ELEMENT="oci/bluefin-server-installer.bst" ;;
        k3s)                      ELEMENT="oci/k3s-sysext.bst" ;;
        *) echo "ERROR: unknown artifact '{{artifact}}' (expected bluefin-server-ddi, bluefin-server-installer, or k3s)" >&2; exit 1 ;;
    esac
    OUTFILE="{{artifact}}-{{fsdk_version}}.spdx.json"
    mkdir -p "${HOME}/.cache/buildstream" "${HOME}/.cache/pip"
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
        -e SPDX_NAME="{{artifact}}" \
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
                --spdx-namespace "https://github.com/projectbluefin/server/sbom/${GIT_SHA}/${SPDX_NAME}" \
                --spdx-creator "Tool: buildstream-sbom" \
                --spdx-creator "Organization: projectbluefin" \
                --deps all \
                --output "/src/${OUTFILE}"
        '
    @echo "==> wrote ${OUTFILE}"

# Generate SBOMs for all three release artifacts in a single container run.
[group('sbom')]
sboms:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "${HOME}/.cache/buildstream" "${HOME}/.cache/pip"
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
        -e VERSION="{{fsdk_version}}" \
        "{{bst2_image}}" \
        bash -c '
            for attempt in 1 2 3; do
                pip install --quiet \
                    git+https://gitlab.com/BuildStream/buildstream-sbom.git@0706fec3bedf6f73bd9d2fed32c2aed585feef8d \
                    && break
                echo "buildstream-sbom install failed (attempt ${attempt}/3); retrying in 5s..."
                [ "${attempt}" -lt 3 ] && sleep 5
            done
            for pair in bluefin-server-ddi:oci/bluefin-server-ddi.bst \
                        bluefin-server-installer:oci/bluefin-server-installer.bst \
                        k3s:oci/k3s-sysext.bst; do
                NAME="${pair%%:*}"
                ELEMENT="${pair#*:}"
                echo "==> Generating SBOM for ${NAME}..."
                buildstream-sbom "${ELEMENT}" \
                    --spdx-name "${NAME}" \
                    --spdx-namespace "https://github.com/projectbluefin/server/sbom/${GIT_SHA}/${NAME}" \
                    --spdx-creator "Tool: buildstream-sbom" \
                    --spdx-creator "Organization: projectbluefin" \
                    --deps all \
                    --output "/src/${NAME}-${VERSION}.spdx.json"
            done
        '
    @echo "==> wrote SBOMs:" && ls -lh *.spdx.json

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

# Build, install, and boot the server in QEMU using the exported raw installer disk.
[group('test')]
test: export-installer
    ./tests/installer-smoke-test "{{bst2_image}}"
