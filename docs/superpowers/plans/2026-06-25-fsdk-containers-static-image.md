# fsdk-containers `base` image — Implementation Plan

> **Status: DELIVERED (2026-06-25).** Image shipped as `ghcr.io/projectbluefin/base`
> (not `static` — see implementation note in the spec). All tasks below were
> completed. Delta from plan: element and image names use `base-*` not `static-*`;
> the dakota-copied GNOME overrides and unrelated patches were trimmed post-delivery.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish a distroless `base` OCI image carved from freedesktop-sdk (FSDK) components via BuildStream, multi-arch, pushed to `ghcr.io/projectbluefin/base`.

**Architecture:** Mirror the proven dakota BST project shape. Copy dakota's pinned `freedesktop-sdk.bst` + `gnome-build-meta.bst` junctions, their `patches/`, and plugin junctions verbatim (guaranteed-buildable start). Add three small new elements — a `stack` listing the minimal runtime deps, a `compose` that chisels non-runtime domains (the size/CVE killer, including the `shells` domain → distroless), and a `script` that runs FSDK's `oci-builder` to package the image. A Justfile drives local build/export; a GitHub Actions workflow builds per-arch and publishes a multi-arch manifest.

**Tech Stack:** BuildStream 2 (run inside the FSDK `bst2` container via podman), freedesktop-sdk 25.08 components, `oci-builder`, podman (squash + manifest), GitHub Actions, Just.

## Global Constraints

- BuildStream `min-version: 2.5`.
- Image ref prefix: `ghcr.io/projectbluefin` (this image: `ghcr.io/projectbluefin/static`).
- License: `Apache-2.0`. Display name: `fsdk-containers`. Vendor label: `Project Bluefin`.
- Architectures: `x86_64` + `aarch64`. Multi-arch manifest required.
- Distroless-only (no `-dev`/shell variant in this plan).
- **Base image targets baseline `x86_64` — do NOT enable `x86_64_v3`** (broad CPU compat for a base layer). This diverges from dakota's Justfile default.
- All FSDK element references use the junction prefix `freedesktop-sdk.bst:` (e.g. `freedesktop-sdk.bst:components/glibc-gconv-cache.bst`). `oci-builder` is referenced as `freedesktop-sdk.bst:components/oci-builder.bst`.
- Tags derive from the FSDK release parsed out of `elements/freedesktop-sdk.bst` (`:latest`, `:25.08`, `:25.08.13`). No separate version file.
- No emojis in any committed file, commit message, README, or workflow.
- Reference (read-only, do not modify): dakota repo at `/var/home/jorge/src/dakota`. Its staged FSDK source (for verifying element/domain names) is under `/var/home/jorge/src/dakota/.bst/staged-junctions/freedesktop-sdk.bst/<hash>/elements/`.

---

### Task 1: Project scaffold — junctions, plugins, patches, project.conf

Stand up a BuildStream project that resolves the junction graph. Deliverable: `bst show` of a junctioned FSDK element succeeds inside the bst2 container.

**Files:**
- Create: `elements/freedesktop-sdk.bst` (copy verbatim from `/var/home/jorge/src/dakota/elements/freedesktop-sdk.bst`)
- Create: `elements/gnome-build-meta.bst` (copy verbatim from dakota)
- Create: `elements/plugins/buildstream-plugins.bst` (copy verbatim from dakota)
- Create: `elements/plugins/buildstream-plugins-community.bst` (copy verbatim from dakota)
- Create: `include/aliases.yml` (copy verbatim from `/var/home/jorge/src/dakota/include/aliases.yml`)
- Create: `patches/freedesktop-sdk/*` and `patches/gnome-build-meta/*` (copy the whole `patches/` tree verbatim from dakota — 11 files)
- Create: `project.conf`
- Create: `.gitignore`

**Interfaces:**
- Produces: a resolvable BST project named `fsdk-containers` with junctions `freedesktop-sdk.bst` and `gnome-build-meta.bst`, the `collect_initial_scripts` plugin (from the `gnome-build-meta.bst` junction), and the `arch` option (`x86_64`,`aarch64`). Variables `arch`, `go-arch` available. Later tasks consume `freedesktop-sdk.bst:...` element refs.

- [ ] **Step 1: Copy junctions, plugins, aliases, patches verbatim**

```bash
cd /var/home/jorge/src/fsdk-containers
mkdir -p elements/plugins include patches
cp /var/home/jorge/src/dakota/elements/freedesktop-sdk.bst elements/freedesktop-sdk.bst
cp /var/home/jorge/src/dakota/elements/gnome-build-meta.bst elements/gnome-build-meta.bst
cp /var/home/jorge/src/dakota/elements/plugins/buildstream-plugins.bst elements/plugins/
cp /var/home/jorge/src/dakota/elements/plugins/buildstream-plugins-community.bst elements/plugins/
cp /var/home/jorge/src/dakota/include/aliases.yml include/aliases.yml
cp -r /var/home/jorge/src/dakota/patches/. patches/
```

- [ ] **Step 2: Write `project.conf`**

Adapted from dakota: name changed, `x86_64_v3` option **removed** (base image is baseline), keep caches/plugins/source-caches identical.

```yaml
name: fsdk-containers

# Required BuildStream version
min-version: 2.5

# Subdirectory where elements are stored
element-path: elements

(@):
  - gnome-build-meta.bst:freedesktop-sdk.bst:include/runtime.yml
  - include/aliases.yml

options:
  arch:
    type: arch
    description: Machine architecture
    variable: arch
    values:
      - aarch64
      - x86_64

sandbox:
  build-arch: "%{arch}"

variables:
  (?):
    - arch == "x86_64":
        go-arch: "amd64"
    - arch == "aarch64":
        go-arch: "arm64"

# Pull-only: read from the shared GNOME + Bluefin BuildStream CAS caches.
artifacts:
  - url: https://gbm.gnome.org:11003
    connection-config:
      keepalive-time: 180
      retry-limit: 5
      retry-delay: 500
      request-timeout: 180
  - url: https://cache.projectbluefin.io:11001
    connection-config:
      keepalive-time: 180
      retry-limit: 5
      retry-delay: 500
      request-timeout: 180

source-caches:
  - url: https://gbm.gnome.org:11003
    connection-config:
      keepalive-time: 180
      retry-limit: 5
      retry-delay: 500
      request-timeout: 180
  - url: https://cache.projectbluefin.io:11001
    connection-config:
      keepalive-time: 180
      retry-limit: 5
      retry-delay: 500
      request-timeout: 180

plugins:
  - origin: junction
    junction: plugins/buildstream-plugins.bst
    elements:
      - autotools
      - meson
      - cmake
      - make
    sources:
      - patch
  - origin: junction
    junction: plugins/buildstream-plugins-community.bst
    elements:
      - collect_manifest
      - flatpak_image
      - flatpak_repo
      - ostree
      - pyproject
    sources:
      - gen_cargo_lock
      - cargo2
      - git_module
      - git_repo
      - go_module
      - patch_queue
      - zip
  - origin: junction
    junction: gnome-build-meta.bst
    elements:
      - collect_initial_scripts

sources:
  git_repo:
    config:
      ref-format: git-describe
```

- [ ] **Step 3: Write `.gitignore`**

```gitignore
**/__pycache__/
.bst
.bst2
.cache/*
*.img
*.raw
*.tar
.build-out
.worktrees/
```

- [ ] **Step 4: Add the Justfile `bst` wrapper (minimal, baseline arch)**

Create `Justfile` with config vars and the `bst` recipe only (build/export added in Task 3). Note: `DEFAULT_BST_FLAGS` is just `--no-interactive` — **no `x86_64_v3`**.

```just
# List available commands
[group('info')]
default:
    @just --list

# ── Configuration ─────────────────────────────────────────────────────
export image_name := env("BUILD_IMAGE_NAME", "static")
export image_registry := env("BUILD_IMAGE_REGISTRY", "ghcr.io/projectbluefin")

# Same bst2 container image FSDK/dakota CI uses — pinned by SHA.
export bst2_image := env("BST2_IMAGE", "registry.gitlab.com/freedesktop-sdk/infrastructure/freedesktop-sdk-docker-images/bst2:64eb0b4930d57a92710822898fb73af6cc1ae35d")

# OCI metadata (dynamic labels), injected at export time.
export OCI_IMAGE_CREATED := env("OCI_IMAGE_CREATED", "")
export OCI_IMAGE_REVISION := env("OCI_IMAGE_REVISION", "")

# ── BuildStream wrapper ──────────────────────────────────────────────
# Runs any bst command inside the bst2 container via podman.
# Baseline x86_64 (no x86_64_v3) so the base image runs on the widest CPU set.
[group('dev')]
bst *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "${HOME}/.cache/buildstream"
    EFFECTIVE_BST_FLAGS="${BST_FLAGS:-}"
    if [[ ! " ${EFFECTIVE_BST_FLAGS} " =~ [[:space:]]--no-interactive([[:space:]]|$) ]]; then
        EFFECTIVE_BST_FLAGS="${EFFECTIVE_BST_FLAGS} --no-interactive"
    fi
    # shellcheck disable=SC2086
    podman run --rm \
        --privileged \
        --device /dev/fuse \
        --network=host \
        -v "{{justfile_directory()}}:/src:rw" \
        -v "${HOME}/.cache/buildstream:/root/.cache/buildstream:rw" \
        -w /src \
        "{{bst2_image}}" \
        bash -c 'bst --colors "$@"' -- ${EFFECTIVE_BST_FLAGS} {{ARGS}}
```

- [ ] **Step 5: Verify the junction graph resolves**

Run: `just bst show freedesktop-sdk.bst:components/glibc-gconv-cache.bst`
Expected: PASS — prints element state table (e.g. `buildable`/`waiting`/`cached`), exit 0. Junctions clone (may take several minutes cold). No YAML/plugin errors.

- [ ] **Step 6: Commit**

```bash
git add elements include patches project.conf .gitignore Justfile
git commit -m "feat: scaffold fsdk-containers BST project (junctions, plugins, patches, project.conf)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: `static` element graph — stack, compose, init-script, OCI

Define the three new elements that turn FSDK components into a distroless OCI image. Deliverable: the full graph for `oci/static.bst` resolves with `bst show`.

**Files:**
- Create: `elements/base/static-stack.bst`
- Create: `elements/base/static-runtime.bst`
- Create: `elements/base/static-init-script.bst`
- Create: `elements/oci/static.bst`

**Interfaces:**
- Consumes (from FSDK junction, names verified against the pinned ref):
  `freedesktop-sdk.bst:public-stacks/runtime-minimal.bst`,
  `freedesktop-sdk.bst:components/ca-certificates.bst`,
  `freedesktop-sdk.bst:components/tzdata.bst`,
  `freedesktop-sdk.bst:components/os-release.bst`,
  `freedesktop-sdk.bst:integration/extra-fs.bst`,
  `freedesktop-sdk.bst:integration/ldconfig.bst`,
  `freedesktop-sdk.bst:components/oci-builder.bst`,
  and the `collect_initial_scripts` plugin (from `gnome-build-meta.bst` junction).
- Produces: top element `oci/static.bst` whose checkout is an OCI image directory consumable by `podman pull oci:<dir>`.

- [ ] **Step 1: Write `elements/base/static-stack.bst`**

The minimal runtime set. Models FSDK's `oci/layers/minimal-stack.bst` but adds CA certs + tzdata (the two things a backend base image needs that the bare minimal runtime lacks).

```yaml
kind: stack
description: |
  Minimal distroless runtime: glibc + gcc-libs + base files, plus
  CA certificates and timezone data. No package manager. The shell is
  pulled by runtime-minimal but stripped by the `shells` compose domain
  in static-runtime.bst.

depends:
  - freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
  - freedesktop-sdk.bst:components/ca-certificates.bst
  - freedesktop-sdk.bst:components/tzdata.bst
  - freedesktop-sdk.bst:components/os-release.bst
  - freedesktop-sdk.bst:integration/extra-fs.bst
  - freedesktop-sdk.bst:integration/ldconfig.bst
```

- [ ] **Step 2: Write `elements/base/static-runtime.bst` (the chisel)**

`compose` is a core BST element (no plugin needed). Exclude domains exactly as FSDK's `oci/layers/minimal.bst` does — note `shells` is what makes it distroless.

```yaml
kind: compose
description: Chisel the static stack down to runtime-only, distroless.

build-depends:
  - base/static-stack.bst

config:
  exclude:
    - debug
    - devel
    - doc
    - locale
    - extra
    - vm-only
    - tests
    - shells
```

- [ ] **Step 3: Write `elements/base/static-init-script.bst`**

Collects the initial scripts (e.g. ldconfig) the OCI script runs against the layer. Models FSDK's `oci/layers/minimal-init-script.bst`.

```yaml
kind: collect_initial_scripts
description: Collect initial scripts for the static OCI layer.

build-depends:
  - base/static-stack.bst

config:
  path: /initial_scripts
```

- [ ] **Step 4: Write `elements/oci/static.bst`**

`script` element that runs the collected init scripts against the composed layer, then `build-oci`. Static labels live here; dynamic labels (created/revision/version) are injected at export time (Task 4). Models FSDK's `oci/minimal-oci.bst` + dakota's label block.

```yaml
kind: script

build-depends:
  - freedesktop-sdk.bst:components/oci-builder.bst
  - base/static-init-script.bst
  - filename: base/static-runtime.bst
    config:
      location: /layer

config:
  commands:
    - |
      if [ -d /initial_scripts ]; then
        for i in /initial_scripts/*; do
          "${i}" /layer
        done
      fi

    - |
      cd "%{install-root}"
      build-oci <<EOF
      mode: oci
      gzip: disabled
      images:
      - os: linux
        architecture: "%{go-arch}"
        layer: /layer
        comment: "fsdk-containers static base"
        config:
          Labels:
            'org.opencontainers.image.title': 'static'
            'org.opencontainers.image.description': 'Distroless base image carved from freedesktop-sdk'
            'org.opencontainers.image.vendor': 'Project Bluefin'
            'org.opencontainers.image.licenses': 'Apache-2.0'
            'org.opencontainers.image.url': 'https://github.com/projectbluefin/fsdk-containers'
            'org.opencontainers.image.source': 'https://github.com/projectbluefin/fsdk-containers'
        index-annotations:
          'org.opencontainers.image.ref.name': 'ghcr.io/projectbluefin/static:latest'
      EOF
```

- [ ] **Step 5: Verify the full graph resolves**

Run: `just bst show --deps all oci/static.bst`
Expected: PASS — prints the full element list including `freedesktop-sdk.bst:bootstrap/glibc.bst`, `...components/ca-certificates.bst`, `...components/tzdata.bst`, `base/static-stack.bst`, `base/static-runtime.bst`, `base/static-init-script.bst`, `oci/static.bst`. Exit 0, no "element not found" / plugin errors.

If any FSDK element name fails to resolve: list the real name with
`ls /var/home/jorge/src/dakota/.bst/staged-junctions/freedesktop-sdk.bst/*/elements/<dir>/` and correct the `depends` entry. Do not guess.

- [ ] **Step 6: Commit**

```bash
git add elements/base elements/oci
git commit -m "feat: add static distroless OCI element graph (stack, compose, oci)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Local build + distroless verification

Add Justfile `build`/`export` recipes and prove the image is distroless and correct. Deliverable: `just build` produces `ghcr.io/projectbluefin/static:latest` in local podman; shell is absent; certs + tzdata present.

**Files:**
- Modify: `Justfile` (append `build`, `export`, `validate`, `verify` recipes)
- Create: `Containerfile`

**Interfaces:**
- Consumes: `oci/static.bst` from Task 2; `image_name`, `image_registry`, `OCI_IMAGE_*` vars from Task 1.
- Produces: local podman image `${image_registry}/${image_name}:latest`; a `just verify` recipe later reused by CI.

- [ ] **Step 1: Append `validate`, `build`, `export` recipes to `Justfile`**

```just
# ── Validate ──────────────────────────────────────────────────────────
[group('dev')]
validate:
    just bst show --deps all oci/static.bst

# ── Build ─────────────────────────────────────────────────────────────
# Build the static OCI image and load it into podman as
# ${image_registry}/${image_name}:latest.
[group('build')]
build:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "==> Building oci/static.bst with BuildStream..."
    just bst build oci/static.bst
    just export

# ── Export ────────────────────────────────────────────────────────────
# Checkout the built OCI image and squash into a single layer in podman.
[group('build')]
export:
    #!/usr/bin/env bash
    set -euo pipefail
    FINAL_REF="{{image_registry}}/{{image_name}}:latest"
    SUDO_CMD=""
    if [ "$(id -u)" -ne 0 ]; then SUDO_CMD="sudo"; fi

    echo "==> Exporting OCI image -> ${FINAL_REF}..."
    rm -rf .build-out
    just bst artifact checkout oci/static.bst --directory /src/.build-out

    IMAGE_ID=$($SUDO_CMD podman pull -q oci:.build-out)
    rm -rf .build-out

    LABEL_ARGS=()
    [ -n "${OCI_IMAGE_CREATED}" ]  && LABEL_ARGS+=(--label "org.opencontainers.image.created=${OCI_IMAGE_CREATED}")
    [ -n "${OCI_IMAGE_REVISION}" ] && LABEL_ARGS+=(--label "org.opencontainers.image.revision=${OCI_IMAGE_REVISION}")

    # Squash to a single layer and apply dynamic labels.
    printf 'FROM %s\n' "$IMAGE_ID" \
      | $SUDO_CMD podman build --pull=never --squash-all "${LABEL_ARGS[@]}" -t "${FINAL_REF}" -f - .
    echo "==> Built ${FINAL_REF}"
```

- [ ] **Step 2: Build the image**

Run: `just build`
Expected: PASS — BST build completes (pulling most artifacts from the CAS caches), `podman build --squash-all` prints `==> Built ghcr.io/projectbluefin/static:latest`. (Cold build can take a while; CAS hits make it fast.)

- [ ] **Step 3: Add the `verify` recipe (distroless assertions)**

Append to `Justfile`:

```just
# ── Verify ────────────────────────────────────────────────────────────
# Assert the image is distroless and ships certs + tzdata.
[group('test')]
verify:
    #!/usr/bin/env bash
    set -euo pipefail
    REF="{{image_registry}}/{{image_name}}:latest"
    SUDO_CMD=""
    if [ "$(id -u)" -ne 0 ]; then SUDO_CMD="sudo"; fi

    echo "==> [1/3] distroless: a shell must NOT be present"
    if $SUDO_CMD podman run --rm --entrypoint /bin/sh "$REF" -c 'echo reached' 2>/dev/null; then
        echo "FAIL: /bin/sh ran — image is not distroless"; exit 1
    fi
    echo "OK: no runnable /bin/sh"

    echo "==> [2/3] CA certificates present"
    $SUDO_CMD podman create --name verify-static "$REF" >/dev/null
    trap '$SUDO_CMD podman rm -f verify-static >/dev/null 2>&1 || true' EXIT
    $SUDO_CMD podman export verify-static | tar -tf - \
      | grep -qE 'etc/(ssl|pki)/.*(ca-bundle|cert)' && echo "OK: CA bundle present"

    echo "==> [3/3] tzdata present"
    $SUDO_CMD podman export verify-static | tar -tf - \
      | grep -q 'usr/share/zoneinfo/UTC' && echo "OK: tzdata present"
    echo "==> verify passed"
```

- [ ] **Step 4: Run verification**

Run: `just verify`
Expected: PASS — prints `OK: no runnable /bin/sh`, `OK: CA bundle present`, `OK: tzdata present`, `==> verify passed`, exit 0.

If `/bin/sh` runs: the `shells` exclude is not stripping it — inspect the composed layer with `just bst artifact checkout base/static-runtime.bst --directory /tmp/rt` and confirm whether the binary lives in a domain other than `shells`; adjust `static-runtime.bst` excludes accordingly (e.g. some shells land in `extra`). Re-run.

- [ ] **Step 5: Write `Containerfile` (lint helper only)**

```dockerfile
# Lint helper for an already-built static image. Image contents come from
# BuildStream elements + OCI assembly .bst files, not from this file.
# Do not add package installation here.
FROM ghcr.io/projectbluefin/static:latest
```

- [ ] **Step 6: Commit**

```bash
git add Justfile Containerfile
git commit -m "feat: add local build/export/verify recipes and Containerfile

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: FSDK-derived versioning + provenance labels

Derive image tags from the pinned FSDK ref and stamp provenance labels. Deliverable: `just tags` prints the three tags; `just export` applies FSDK provenance labels.

**Files:**
- Modify: `Justfile` (add `fsdk_version`/`fsdk_ref` vars, `tags` recipe; extend `export` labels; add `tag-push` recipe)

**Interfaces:**
- Consumes: `elements/freedesktop-sdk.bst` `ref:` line; `image_registry`/`image_name`.
- Produces: `just tags` → newline list `latest 25.08 25.08.13`; `just tag-push REGISTRY_REF` applied by CI in Task 5. Labels `io.projectbluefin.fsdk.version` + `io.projectbluefin.fsdk.ref` on the image.

- [ ] **Step 1: Add version-derivation vars + `tags` recipe to `Justfile`**

Place near the config block. The ref line looks like
`  ref: freedesktop-sdk-25.08.13-0-g8446990f0a549bb1f3ceb654af64fc176b274488`.

```just
# FSDK release parsed from the pinned junction ref — the single source of truth
# for image versioning. e.g. "25.08.13".
export fsdk_version := `grep -oE 'freedesktop-sdk-[0-9]+\.[0-9]+\.[0-9]+' elements/freedesktop-sdk.bst | head -1 | sed 's/freedesktop-sdk-//'`
# Exact junction commit ref (full ref: value), for provenance.
export fsdk_ref := `grep -E '^\s*ref:' elements/freedesktop-sdk.bst | head -1 | sed -E 's/^\s*ref:\s*//'`

# Print the tag set derived from the FSDK release: latest, minor line, point release.
[group('info')]
tags:
    #!/usr/bin/env bash
    set -euo pipefail
    V="{{fsdk_version}}"
    MINOR="$(echo "$V" | cut -d. -f1,2)"
    printf '%s\n%s\n%s\n' latest "$MINOR" "$V"
```

- [ ] **Step 2: Verify tag derivation**

Run: `just tags`
Expected: PASS — exactly three lines:
```
latest
25.08
25.08.13
```
(`25.08.13` matches whatever ref is pinned in `elements/freedesktop-sdk.bst`.)

- [ ] **Step 3: Extend `export` to stamp FSDK + version labels**

In the `export` recipe, add these to the `LABEL_ARGS` array (after the existing created/revision lines):

```just
    LABEL_ARGS+=(--label "org.opencontainers.image.version={{fsdk_version}}")
    LABEL_ARGS+=(--label "io.projectbluefin.fsdk.version={{fsdk_version}}")
    LABEL_ARGS+=(--label "io.projectbluefin.fsdk.ref={{fsdk_ref}}")
```

- [ ] **Step 4: Add a `tag-push` helper recipe**

Tags the locally built `:latest` image with every derived tag and pushes. Used by CI (Task 5) per-arch with an arch suffix, and for the final manifest.

```just
# Push the locally built :latest under all derived tags to a given repo ref.
# Usage: just tag-push ghcr.io/projectbluefin/static
[group('build')]
tag-push REPO:
    #!/usr/bin/env bash
    set -euo pipefail
    SRC="{{image_registry}}/{{image_name}}:latest"
    SUDO_CMD=""
    if [ "$(id -u)" -ne 0 ]; then SUDO_CMD="sudo"; fi
    while read -r t; do
        $SUDO_CMD podman tag "$SRC" "{{REPO}}:$t"
        $SUDO_CMD podman push "{{REPO}}:$t"
        echo "==> pushed {{REPO}}:$t"
    done < <(just tags)
```

- [ ] **Step 5: Re-export and confirm labels**

Run: `OCI_IMAGE_REVISION=test just export && sudo podman inspect ghcr.io/projectbluefin/static:latest --format '{{ "{{" }} index .Config.Labels "io.projectbluefin.fsdk.version" {{ "}}" }}'`
Expected: PASS — prints the FSDK version (e.g. `25.08.13`).

- [ ] **Step 6: Commit**

```bash
git add Justfile
git commit -m "feat: derive image tags from FSDK ref and add provenance labels

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Multi-arch CI publish workflow

Build per-arch on native runners and publish a multi-arch manifest to ghcr. Deliverable: `.github/workflows/build.yml` that validates on PRs and publishes on push to the default branch.

**Files:**
- Create: `.github/workflows/build.yml`

**Interfaces:**
- Consumes: `just validate`, `just build`, `just tag-push` recipes; `image_registry`/`image_name`.
- Produces: pushed images `ghcr.io/<owner>/static:{latest,25.08,25.08.13}` plus per-arch refs, combined into a multi-arch manifest.

- [ ] **Step 1: Write `.github/workflows/build.yml`**

PR job = `bst show` only (no CAS writes). Build job = matrix over native x86_64 + aarch64 runners, push per-arch tags, then a manifest job.

```yaml
name: Build static image

on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  packages: write

env:
  IMAGE_NAME: static
  IMAGE_REGISTRY: ghcr.io/${{ github.repository_owner }}

jobs:
  validate:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: taiki-e/install-action@v2
        with:
          tool: just
      - name: Resolve element graph
        run: just validate

  build:
    if: github.event_name != 'pull_request'
    strategy:
      fail-fast: false
      matrix:
        include:
          - arch: x86_64
            runner: ubuntu-24.04
          - arch: aarch64
            runner: ubuntu-24.04-arm
    runs-on: ${{ matrix.runner }}
    timeout-minutes: 300
    outputs:
      version: ${{ steps.meta.outputs.version }}
    steps:
      - uses: actions/checkout@v4
      - uses: taiki-e/install-action@v2
        with:
          tool: just
      - name: Image metadata
        id: meta
        run: |
          echo "version=$(just tags | sed -n '3p')" >> "$GITHUB_OUTPUT"
          echo "created=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$GITHUB_OUTPUT"
      - name: Log in to ghcr
        run: echo "${{ secrets.GITHUB_TOKEN }}" | sudo podman login ghcr.io -u "${{ github.actor }}" --password-stdin
      - name: Build
        env:
          OCI_IMAGE_CREATED: ${{ steps.meta.outputs.created }}
          OCI_IMAGE_REVISION: ${{ github.sha }}
        run: just build
      - name: Push per-arch tags
        run: just tag-push "${IMAGE_REGISTRY}/${IMAGE_NAME}-${{ matrix.arch }}"

  manifest:
    needs: build
    if: github.event_name != 'pull_request'
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: taiki-e/install-action@v2
        with:
          tool: just
      - name: Log in to ghcr
        run: echo "${{ secrets.GITHUB_TOKEN }}" | sudo podman login ghcr.io -u "${{ github.actor }}" --password-stdin
      - name: Assemble multi-arch manifests
        run: |
          set -euo pipefail
          REPO="${IMAGE_REGISTRY}/${IMAGE_NAME}"
          for t in $(just tags); do
            sudo podman manifest create "${REPO}:${t}"
            sudo podman manifest add "${REPO}:${t}" "docker://${REPO}-x86_64:${t}"
            sudo podman manifest add "${REPO}:${t}" "docker://${REPO}-aarch64:${t}"
            sudo podman manifest push --all "${REPO}:${t}" "docker://${REPO}:${t}"
            echo "==> published ${REPO}:${t} (multi-arch)"
          done
```

- [ ] **Step 2: Lint the workflow YAML**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/build.yml')); print('yaml ok')"`
Expected: PASS — prints `yaml ok`.

- [ ] **Step 3: Sanity-check the PR job locally**

Run: `just validate`
Expected: PASS — full `oci/static.bst` graph resolves (same as Task 2 Step 5).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/build.yml
git commit -m "ci: multi-arch build and publish workflow for static image

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: README + repo docs

Document what the suite is, how to build, and the versioning model. Deliverable: a README a newcomer can follow to build the image.

**Files:**
- Create: `README.md`
- Create: `LICENSE` (Apache-2.0, copy from `/var/home/jorge/src/dakota/LICENSE`)

**Interfaces:**
- Consumes: nothing. Produces: human docs only.

- [ ] **Step 1: Copy the Apache-2.0 LICENSE**

```bash
cp /var/home/jorge/src/dakota/LICENSE LICENSE
```

- [ ] **Step 2: Write `README.md`**

```markdown
# fsdk-containers

Distroless OCI base images carved from [freedesktop-sdk](https://gitlab.com/freedesktop-sdk/freedesktop-sdk)
(FSDK) using BuildStream. A free, OSS alternative to commercial distroless
suites: images inherit FSDK's existing CVE patching and reproducible builds
instead of maintaining a separate package set.

## Images

| Image | Description |
| ----- | ----------- |
| `ghcr.io/projectbluefin/static` | Distroless base: glibc, CA certificates, timezone data. No shell, no package manager. |

## How it works

Each image is composed from raw FSDK `components/*` (never `platform.bst`),
then chiseled with a BuildStream `compose` element that drops every non-runtime
domain — including `shells`, which makes the image distroless. The result is
glibc + openssl certs + tzdata + base files and nothing else.

Pipeline: `stack` (list deps) -> `compose` (chisel) -> `script` (oci-builder).

## Versioning

There is no application version for a base image, so the version axis is the
FSDK release. Tags are derived from the pinned junction ref in
`elements/freedesktop-sdk.bst`:

- `:latest` — rolling
- `:25.08` — FSDK minor line
- `:25.08.13` — FSDK point release (treated immutable)

Every image self-declares its base via `io.projectbluefin.fsdk.version` and
`io.projectbluefin.fsdk.ref` labels.

## Build locally

Requires `podman` and [`just`](https://github.com/casey/just). BuildStream runs
inside the FSDK `bst2` container — nothing to install.

    just validate        # resolve the element graph
    just build           # build + load ghcr.io/projectbluefin/static:latest
    just verify          # assert distroless + certs + tzdata
    just tags            # show derived tags

## License

Apache-2.0.
```

- [ ] **Step 3: Verify README renders / links sane**

Run: `python3 -c "open('README.md').read(); print('readme ok')"`
Expected: PASS — prints `readme ok`.

- [ ] **Step 4: Commit**

```bash
git add README.md LICENSE
git commit -m "docs: add README and Apache-2.0 LICENSE

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Self-Review notes

- **Spec coverage:** static base (Tasks 2-3), distroless via `shells` exclude (Task 2/3), multi-arch (Task 5), ghcr publish (Task 5), FSDK-derived tags + provenance labels (Task 4), reuse dakota junctions/patches/caches (Task 1), keep GBM junction (Task 1), testing/verification (Task 3), versioning model (Tasks 4, 6). All spec sections map to a task.
- **Element/domain names** verified against the staged FSDK source at the pinned ref (ca-certificates.bst, tzdata.bst, os-release.bst, public-stacks/runtime-minimal.bst, integration/extra-fs.bst, integration/ldconfig.bst, components/oci-builder.bst, compose excludes incl. `shells`).
- **Baseline-arch divergence** from dakota (no `x86_64_v3`) is intentional and called out in Global Constraints + Task 1.
- **Open risk:** if a shell binary lives outside the `shells` domain in this FSDK release, Task 3 Step 4 has the remediation path (inspect composed layer, adjust excludes).
```
