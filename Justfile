# List available commands
[group('info')]
default:
    @just --list

# Same bst2 container image FSDK/dakota CI uses -- pinned by commit-named tag.
export oras_image := env("ORAS_IMAGE", "ghcr.io/oras-project/oras:v1.3.4")
export bst2_image := env("BST2_IMAGE", "registry.gitlab.com/freedesktop-sdk/infrastructure/freedesktop-sdk-docker-images/bst2:1775c49af80653f9cd86cbc92761eae4ab95204e")
# bats for `just test-unit` when none is installed -- pinned by digest.
export bats_image := env("BATS_IMAGE", "docker.io/bats/bats:1.14.0@sha256:5322b877351fda0cc435de8c6116de7d0a2ec79d7c680132a0ef329a633bc66f")
# butane (v2.27.0, built from the Ignition tree) for `just homelab-templates` -- pinned by digest.
export butane_image := env("BUTANE_IMAGE", "quay.io/coreos/butane:release@sha256:d264fba5a02ec7a5525b7cd4ab04090e8c70d0ee42a74a90a0e2f89633ae720c")

# Prefix for podman calls: empty when rootless podman works, "sudo" otherwise.
sudo_cmd := if `podman info >/dev/null 2>&1 && echo 1 || echo 0` == "1" { "" } else { "sudo" }

# FSDK point release of the pinned junction ref, e.g. "26.08.0".
# check-release-version.py is its one parser.
export fsdk_version := `python3 .github/scripts/check-release-version.py --print-fsdk`
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
    # On systemd-resolved hosts /etc/resolv.conf may name a stub or VPN
    # resolver that only the host's NSS path can use; hand the container the
    # real upstream list instead.
    resolv_args=()
    if [ -s /run/systemd/resolve/resolv.conf ]; then
        resolv_args=(-v /run/systemd/resolve/resolv.conf:/etc/resolv.conf:ro)
    fi
    # shellcheck disable=SC2086
    {{sudo_cmd}} podman run --rm \
        --privileged \
        --device /dev/fuse \
        --network=host \
        "${resolv_args[@]}" \
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

# ── Validate ──
# Version-invariant checks + resolve every shipped element graph.
[group('dev')]
validate: gen-dev-keys
    python3 .github/scripts/check-release-version.py
    python3 .github/scripts/check-k0s-version.py
    python3 .github/scripts/check-renovate-series.py
    just bst show --deps all oci/bluefin-server-image.bst oci/k0s-sysext.bst oci/zfs-sysext.bst oci/kubeadm-sysext.bst oci/homelab-sysext.bst oci/argo-workflows-sysext.bst oci/mcp-sysext.bst oci/kubestellar-sysext.bst oci/nvidia-open-595-sysext.bst oci/nvidia-container-toolkit-sysext.bst

# Run the unit test suite (pytest + bats; bats from a container if not installed).
[group('dev')]
test-unit:
    #!/usr/bin/env bash
    set -euo pipefail
    python3 -m pytest tests/unit -q
    if command -v bats >/dev/null 2>&1; then
        exec bats tests/unit
    fi
    echo "==> bats is not installed; running it from ${bats_image}" >&2
    exec {{sudo_cmd}} podman run --rm --security-opt label=disable -e CI \
        -v "{{justfile_directory()}}:/code:ro" -w /code "${bats_image}" tests/unit

# Lint the Python (ruff) and type-check the scripts (mypy), as the unit-tests workflow does.
[group('dev')]
lint-python:
    python3 -m ruff check
    python3 -m mypy

# ── Build ─────────────────────────────────────────────────────────────
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

# -- Diskless /usr image + signed boot chain ----------------------------------

# Generate local Secure Boot + module signing keys in files/boot-keys/.
[group('diskless')]
gen-dev-keys *ARGS:
    bash scripts/gen-dev-keys.sh {{ARGS}}

# Build the release image set: DDI, sysupdate sources, signed UKIs, netboot ESP.
[group('diskless')]
build-image: gen-dev-keys
    just bst build oci/bluefin-server-image.bst

# Export the release image set (default: dist/diskless/).
[group('diskless')]
export-image OUT="dist/diskless": build-image
    rm -rf {{OUT}}
    just bst artifact checkout oci/bluefin-server-image.bst --directory /src/{{OUT}}
    @echo "==> wrote image artifacts:" && ls -lh {{OUT}}/

# Set the image version in include/image.yml; it must increase under
# strverscmp() (CI uses YY.MM.<run number>).
[group('diskless')]
set-version VERSION:
    #!/usr/bin/env bash
    set -euo pipefail
    [[ "{{VERSION}}" =~ ^[0-9][0-9A-Za-z.]{0,16}$ ]] || { echo "invalid version (digits/letters/dots, at most 17 chars): {{VERSION}}" >&2; exit 1; }
    sed -i 's/^  image-version: .*/  image-version: "{{VERSION}}"/' include/image.yml
    grep image-version include/image.yml

# Install diskless -> disk, then (with NEXT) sysupdate A->B and reboot, and (with
# BROKEN) break that update and prove the boot-counted rollback, all in QEMU.
# DOGFOOD_SYSEXT=nvidia follows the NVIDIA driver and toolkit sysexts instead of ZFS,
# DOGFOOD_SYSEXT=zfs,nvidia follows both.
[group('diskless')]
dogfood-install NEXT="" BROKEN="":
    bash scripts/dogfood-install.sh dist/diskless {{NEXT}} {{BROKEN}}

# Boot the offline USB installer, install unattended to a blank disk, boot it, and
# (with NEXT) prove its updates: failed checks on the banner, sysupdate to NEXT, boot
# it (QEMU). NEXT=release checks against the image's own source (GitHub Releases).
# DOGFOOD_TARGET=foreign-gpt|ext4|xfs|prior-install installs onto a disk that is
# not empty (prior-install: install, then again over that install; no NEXT).
[group('diskless')]
dogfood-installer NEXT="":
    bash scripts/dogfood-installer.sh dist/diskless {{NEXT}}

# REF=ghcr.io/<owner>/bluefin-server or <registry-host>:30500/bluefin-server
# (PLAIN_HTTP=1); log in with podman login first. One layer per file.
# Local rehearsal only: releases are published by scripts/publish-release.sh
# from .github/workflows/build.yml, which also verifies the pushed manifest
# against the local files. This recipe pushes the same artifact type,
# annotations and layout, and nothing else.
# Publish an image set as an ORAS OCI artifact tagged <version> and latest.
[group('diskless')]
publish-oci REF DIR="dist/diskless" PLAIN_HTTP="0":
    #!/usr/bin/env bash
    set -euo pipefail
    revision="$(git rev-parse HEAD)"
    cd "{{DIR}}"
    uki="$(ls bluefin-server-netboot_*.efi)"
    ver="${uki#bluefin-server-netboot_}"; ver="${ver%.efi}"
    mapfile -t files < <(find . -maxdepth 1 -type f -printf '%f\n' | sort)
    extra=()
    [ "{{PLAIN_HTTP}}" = 1 ] && extra+=(--plain-http)
    auth="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/containers/auth.json"
    [ -f "${auth}" ] && extra+=(--registry-config /auth.json) && mounts=(-v "${auth}:/auth.json:ro") || mounts=()
    podman run --rm --network=host --security-opt label=disable "${mounts[@]}" -v "$PWD:/w:ro" -w /w \
        {{oras_image}} push "${extra[@]}" \
        --artifact-type application/vnd.projectbluefin.server.release.v1 \
        --annotation "org.opencontainers.image.version=${ver}" \
        --annotation "org.opencontainers.image.source=${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-projectbluefin/server}" \
        --annotation "org.opencontainers.image.revision=${revision}" \
        "{{REF}}:${ver},latest" "${files[@]}"

# Boot dist/diskless/ in QEMU with Secure Boot, pulling /usr over HTTP.
[group('diskless')]
dogfood:
    bash scripts/dogfood-diskless.sh dist/diskless

# Headless dogfood boot; passes when the in-guest probe reports no failed units.
[group('diskless')]
dogfood-check:
    bash scripts/dogfood-diskless.sh dist/diskless --check

# QEMU: two diskless appliances on one L2 segment resolve each other as
# <hostname>.local over mDNS (a default bluefin-<machine-id> and a provisioned name).
[group('diskless')]
dogfood-mdns:
    bash scripts/dogfood-mdns.sh dist/diskless

# Build the OpenZFS systemd-sysext (locked to one image version).
[group('sysext')]
build-zfs-sysext: gen-dev-keys
    just bst build oci/zfs-sysext.bst

# Export the OpenZFS sysext + SHA256SUMS to dist/sysext/.
[group('sysext')]
export-zfs-sysext: build-zfs-sysext
    rm -rf dist/zfs-checkout
    mkdir -p dist/sysext
    just bst artifact checkout oci/zfs-sysext.bst --directory /src/dist/zfs-checkout
    cp dist/zfs-checkout/zfs_*.raw.zst dist/sysext/
    grep 'raw.zst$' dist/zfs-checkout/SHA256SUMS >> dist/sysext/SHA256SUMS
    rm -rf dist/zfs-checkout
    @echo "==> wrote zfs sysext:" && ls -lh dist/sysext/

# Build the homelab sysext (component manifests + bluefin-homelab-apply) and
# its add-on sysexts (Argo Workflows, MCP server, KubeStellar).
[group('sysext')]
build-homelab-sysext:
    just bst build oci/homelab-sysext.bst oci/argo-workflows-sysext.bst oci/mcp-sysext.bst oci/kubestellar-sysext.bst

# Export the homelab sysext and its add-ons + SHA256SUMS to dist/sysext/.
[group('sysext')]
export-homelab-sysext: build-homelab-sysext
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p dist/sysext
    for name in homelab argo-workflows mcp kubestellar; do
        rm -rf dist/homelab-checkout
        just bst artifact checkout "oci/${name}-sysext.bst" --directory /src/dist/homelab-checkout
        cp dist/homelab-checkout/${name}_*.raw.zst dist/sysext/
        grep 'raw.zst$' dist/homelab-checkout/SHA256SUMS >> dist/sysext/SHA256SUMS
    done
    rm -rf dist/homelab-checkout
    echo "==> wrote homelab sysexts:" && ls -lh dist/sysext/

# Re-render files/homelab/manifests/ and files/homelab/addons/ from the pins in the render script (network, podman).
[group('sysext')]
render-homelab-manifests:
    python3 scripts/render-homelab-manifests.py

# Compile the homelab Butane templates (files/homelab/templates/*.bu) to the
# Ignition .ign next to each; CHECK=1 only fails if a committed .ign differs.
[group('sysext')]
homelab-templates CHECK="":
    #!/usr/bin/env bash
    set -euo pipefail
    rc=0
    for bu in files/homelab/templates/*.bu; do
        ign="${bu%.bu}.ign"
        out="$({{sudo_cmd}} podman run --rm -i --network=none "${butane_image}" --strict --pretty < "${bu}")"
        if [ -n "{{CHECK}}" ]; then
            [ "${out}" = "$(cat "${ign}")" ] || { echo "ERROR: ${ign} is not the compiled ${bu}; run just homelab-templates" >&2; rc=1; }
        else
            printf '%s\n' "${out}" > "${ign}"
            echo "==> ${ign}"
        fi
    done
    exit "${rc}"

# Build an NVIDIA driver sysext (open kernel modules; locked to one image version).
[group('sysext')]
build-nvidia-sysext FLAVOUR="nvidia-open-595": gen-dev-keys
    just bst build oci/{{FLAVOUR}}-sysext.bst

# Export an NVIDIA driver sysext + SHA256SUMS to dist/sysext/.
[group('sysext')]
export-nvidia-sysext FLAVOUR="nvidia-open-595": (build-nvidia-sysext FLAVOUR)
    rm -rf dist/{{FLAVOUR}}-checkout
    mkdir -p dist/sysext
    just bst artifact checkout oci/{{FLAVOUR}}-sysext.bst --directory /src/dist/{{FLAVOUR}}-checkout
    cp dist/{{FLAVOUR}}-checkout/{{FLAVOUR}}_*.raw.zst dist/sysext/
    grep 'raw.zst$' dist/{{FLAVOUR}}-checkout/SHA256SUMS >> dist/sysext/SHA256SUMS
    rm -rf dist/{{FLAVOUR}}-checkout
    @echo "==> wrote {{FLAVOUR}} sysext:" && ls -lh dist/sysext/

# Install dist/diskless/ in QEMU, merge its NVIDIA sysext and probe it (no GPU).
[group('sysext')]
dogfood-nvidia FLAVOUR="nvidia-open-595":
    bash scripts/dogfood-nvidia.sh dist/diskless "dist/diskless/{{FLAVOUR}}_$(sed -n 's/^  image-version: "\(.*\)"$/\1/p' include/image.yml).raw.zst"

# Boot dist/diskless/ in QEMU as a single-node kubeadm control plane (needs helm
# and guest internet for the control-plane and Cilium images).
[group('sysext')]
dogfood-kubeadm:
    bash scripts/dogfood-kubeadm.sh dist/diskless

# Boot dist/diskless/ in QEMU as a two-node homelab (control plane + a node that
# joins with the passphrase over mDNS) plus a wrong-passphrase node (guest internet).
[group('sysext')]
dogfood-homelab-cluster:
    bash scripts/dogfood-homelab-cluster.sh dist/diskless

# QEMU: a diskless control plane and node from the homelab templates as
# published (needs guest internet).
[group('sysext')]
dogfood-homelab-templates:
    bash scripts/dogfood-homelab-templates.sh dist/diskless

# QEMU: offline installs of a control plane and a node from the USB
# installer's Homelab entries, then the cluster (needs guest internet).
[group('sysext')]
dogfood-homelab-installer:
    bash scripts/dogfood-homelab-installer.sh dist/diskless

# Build the NVIDIA Container Toolkit (CDI) systemd-sysext (own version axis).
[group('sysext')]
build-nvidia-container-toolkit-sysext:
    just bst build oci/nvidia-container-toolkit-sysext.bst

# Export the NVIDIA Container Toolkit sysext + SHA256SUMS to dist/sysext/.
[group('sysext')]
export-nvidia-container-toolkit-sysext: build-nvidia-container-toolkit-sysext
    rm -rf dist/nvidia-ctk-checkout
    mkdir -p dist/sysext
    just bst artifact checkout oci/nvidia-container-toolkit-sysext.bst --directory /src/dist/nvidia-ctk-checkout
    cp dist/nvidia-ctk-checkout/nvidia-container-toolkit-*.raw.zst dist/sysext/
    grep 'raw.zst$' dist/nvidia-ctk-checkout/SHA256SUMS >> dist/sysext/SHA256SUMS
    rm -rf dist/nvidia-ctk-checkout
    @echo "==> wrote nvidia-container-toolkit sysext:" && ls -lh dist/sysext/

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
