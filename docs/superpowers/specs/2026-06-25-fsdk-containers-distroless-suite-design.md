# fsdk-containers — distroless OCI suite (design)

Date: 2026-06-25
Status: in progress

> **Implementation note (2026-06-25):** The tracer bullet was delivered as
> `ghcr.io/projectbluefin/base`. Suite expanded (2026-06-25) to cover all
> supply chain gaps identified in the projectbluefin testing-lab cluster.

## Summary

An OSS distroless container suite carved from
[freedesktop-sdk](https://gitlab.com/freedesktop-sdk/freedesktop-sdk) (FSDK)
components using BuildStream (BST). Inherits FSDK's CVE patching and reproducible
builds. No separate package set to maintain.

Supply chain rule: every image is either from the official upstream project
(e.g. `registry.k8s.io/kubectl`) or built here from FSDK. No vendor images
(Chainguard, Fedora, etc.) except where FSDK has no component and there is no
official upstream distroless equivalent.

## Image suite

| Image | Tier | Contents | Replaces |
|---|---|---|---|
| `base` | base | glibc + CA certs + tzdata | *(tracer bullet — delivered)* |
| `static` | static | CA certs + tzdata, no glibc | `gcr.io/distroless/static` pattern |
| `skopeo` | app on base | base + skopeo + containers-common | `quay.io/skopeo/stable` (Fedora) |
| `lab-runner` | shell on base | base + bash/curl/git/jq/python3/openssh | `wolfi-base` + `apk add` |
| `loki` | app on static | static + loki binary (static Go) | `docker.io/grafana/loki` (Docker Hub) |

### Kept as official upstream (not rebuilt here)

| Image | Reason |
|---|---|
| `registry.k8s.io/kubectl` | Official Kubernetes upstream distroless |
| `registry.k8s.io/pause`, `metrics-server` | Official Kubernetes |
| `quay.io/kubevirt/virt-launcher` | KubeVirt CNCF project |
| `ghcr.io/project-zot/zot-linux-amd64` | Zot project official |
| `ghcr.io/flatcar/nebraska` | Flatcar project official |
| `ghcr.io/actions/actions-runner` | GitHub Actions official |
| `quay.io/argoproj/argocd`, `workflow-controller` | CNCF Graduated, quay.io/argoproj |
| `cgr.dev/chainguard/postgres` | FSDK has no postgresql component; no official upstream distroless |

### Deferred

| Image | Reason |
|---|---|
| `promtail` | Deprecated upstream; replacement (Fluent Bit / OTel Collector) under investigation |

## Tiers (following distroless.dev conventions)

- **static**: CA certs + tzdata, no glibc. For statically compiled Go binaries.
- **base**: static + glibc + gcc-libs. For dynamically linked binaries.
- **app images**: sit on base or static, add only the application binary and its deps.
- **lab-runner**: shell-enabled exception. Not distroless. CI utility container only.

## Hard rule: never duplicate an official upstream distroless image

Before adding ANY image, check whether the tool already ships an official
CNCF / upstream distroless image. If one exists, consume it from upstream.
Chainguard images are vendor images, not official upstream images.

## Architecture

Three-element pattern per image:
1. `stack` — declares FSDK component deps
2. `compose` — chisels by domain (excludes debug/devel/doc/locale/static-blocklist)
3. `oci/*` script — runs `build-oci`, applies SLIM recipe, emits the OCI artifact

## Element layout

```
elements/
  base/         base-stack.bst, base-runtime.bst, base-init-script.bst
  static/       static-stack.bst, static-runtime.bst, static-init-script.bst
  skopeo/       skopeo-stack.bst, skopeo-runtime.bst
  lab-runner/   lab-runner-stack.bst, lab-runner-runtime.bst
  loki/         loki-bin.bst (kind: import, arch-conditional zip sources)
  oci/          base.bst, static.bst, skopeo.bst, lab-runner.bst, loki.bst
```

## Versioning

FSDK release version parsed from the pinned junction ref in
`elements/freedesktop-sdk.bst`. Tags: `:latest`, `:<minor>`, `:<point>`.
Loki image additionally labeled with the Loki upstream version.


## Summary

An OSS, free distroless container suite carved directly from
[freedesktop-sdk](https://gitlab.com/freedesktop-sdk/freedesktop-sdk) (FSDK)
components using BuildStream (BST). A Chainguard-style alternative that inherits
FSDK's existing CVE patching and reproducible-build engineering instead of
maintaining its own package set.

The insight: FSDK already ships security-patched runtimes and C libraries. By
composing OCI images from raw `components/*` (never `platform.bst`) and filtering
out non-runtime domains, we get tiny, shell-less, package-manager-less images
with near-zero added maintenance burden. We have already "paid the BuildStream
tax" (junctions, CAS caches) in the dakota/bluefin factory, so this is cheap to
stand up.

This spec covers the **tracer bullet**: a single `static` base image, multi-arch,
built and pushed end-to-end. Later images (python, node, CNCF Go tools) reuse the
same pipeline and are out of scope here.

## Goals

- One distroless `static` base image (glibc + ca-certificates + tzdata + base
  files), no shell, no package manager.
- Multi-arch from day one: `x86_64` + `aarch64` manifest.
- Built and pushed to `ghcr.io/projectbluefin/static` via GitHub Actions.
- Versioning tracks the FSDK release lifecycle.
- Zero added upstream-patch burden (FSDK owns component CVE patching).

## Non-goals (for the tracer bullet)

- `-dev` / shell variants (distroless-only for now; add later).
- Language-runtime images (python, node) and CNCF Go tool images (only tools
  that lack an official upstream distroless image — see Hard rule below;
  kubectl is excluded because it ships one upstream).
- Argo Workflows orchestration (deferred; GitHub Actions for now).
- Wolfi source tracking (explicitly rejected — FSDK is the source of truth).

## Hard rule: never duplicate an official upstream distroless image

Before adding ANY image to this suite, check whether the tool already ships an
official CNCF / upstream distroless image (e.g. `kubectl`,
`registry.k8s.io/kubectl`, and similar first-party distroless artifacts). If one
exists, **do not rebuild it here** — consume it from upstream. This suite exists
to fill gaps (FSDK-derived bases, runtimes, and tools that lack a maintained
upstream distroless build), not to re-package images the ecosystem already
maintains. This rule governs every future image-scoping decision.

## Architecture

Mirror the proven dakota BST shape:

- **Junctions**: `freedesktop-sdk.bst` + `gnome-build-meta.bst`, copied verbatim
  from dakota (pinned `ref`, `patch_queue`). dakota's FSDK junction `overrides`
  point into `gnome-build-meta.bst:sdk/*`, so GBM is kept even though the static
  base barely needs it. Dropping GBM would mean rewriting the junction; that is
  deferred until the suite no longer needs the GBM overrides.
- **`project.conf`**: name `fsdk-containers`; `arch` option (`x86_64`,
  `aarch64`); pull from the existing GNOME (`gbm.gnome.org`) and Bluefin
  (`cache.projectbluefin.io`) BuildStream CAS caches.
- **Per-image pipeline** (3 small, independently inspectable units):
  1. `stack` — lists the FSDK component deps for the image.
  2. `compose` — chisels by domain (the size/CVE killer).
  3. `script` — runs `oci-builder` / `build-oci` to package the OCI image.

### Element layout

```
elements/
  freedesktop-sdk.bst              # junction (copied from dakota)
  gnome-build-meta.bst             # junction (copied from dakota)
  base/static-stack.bst            # stack: glibc + ca-certificates + tzdata + base-files
  base/static-runtime.bst          # compose: exclude devel/debug/doc/locale/static-blocklist
  oci/static.bst                   # script: build-oci -> ghcr.io/projectbluefin/static
include/
  aliases.yml                      # copied from dakota
patches/
  freedesktop-sdk/                 # copied from dakota
  gnome-build-meta/                # copied from dakota
project.conf
Justfile                           # build/checkout/push recipes (adapted from dakota)
Containerfile
.github/workflows/build.yml
docs/superpowers/specs/            # this spec
README.md
```

Each unit answers: what it does, how it is used, what it depends on. The `stack`
declares intent, the `compose` enforces the chisel, the `script` packages — you
can change one without breaking the others, and `bst show` inspects each in
isolation.

## The chisel (kills size and CVEs)

The `compose` element targets only the required `components/*` and excludes
non-runtime domains:

```yaml
kind: compose
build-depends:
  - base/static-stack.bst
config:
  exclude:
    - devel              # no C headers / .so symlinks / pkgconfig
    - debug              # no debug symbols
    - doc                # no man pages / docs
    - locale             # no translations
    - static-blocklist
```

Because we compose from raw `components/*` rather than `platform.bst`, the image
contains no `bash`, no `dnf`/`rpm`, no Wayland/Mesa/PipeWire desktop bloat — just
glibc, openssl certs, tzdata, and base files. `ldconfig` is run via a BST
`integration-command` so the runtime linker cache is valid in the packaged
sysroot.

## OCI packaging

`oci/static.bst` (`kind: script`) build-depends on
`gnome-build-meta.bst:freedesktop-sdk.bst:components/oci-builder.bst` and stages
the composed runtime at `/layer`, then:

```
build-oci <<EOF
mode: oci
gzip: disabled
images:
- os: linux
  architecture: "%{go-arch}"
  layer: /layer
  config:
    Labels: { ... see Labels below ... }
  index-annotations:
    'org.opencontainers.image.ref.name': 'ghcr.io/projectbluefin/static:latest'
EOF
```

## Versioning

A base image has no application version, so the version axis **is** the FSDK
release. We follow the FSDK lifecycle directly.

- **Tags**: `:latest` (rolling) + `:25.08` (FSDK minor/branch line) +
  `:25.08.13` (FSDK point release, treated immutable).
- **Source of truth**: the junction `ref` in `elements/freedesktop-sdk.bst`. A
  small script parses the FSDK version (e.g. `25.08.13`) out of that ref — no
  separate version file to drift.
- **Bumps**: junction `ref` bump (renovate-style, as in dakota) triggers CI to
  rebuild and retag. Follow the FSDK lifecycle: bump on a new FSDK point release;
  open a new `:25.NN` line when FSDK cuts a new branch.

### Labels

Standard OCI labels, populated dynamically in CI (the dakota `OCI_IMAGE_*`
pattern):

- `org.opencontainers.image.version` = FSDK version (e.g. `25.08.13`)
- `org.opencontainers.image.revision` = git commit sha
- `org.opencontainers.image.created` = build timestamp
- `org.opencontainers.image.source` = repo URL
- `org.opencontainers.image.url` = project URL
- `org.opencontainers.image.vendor` = `Project Bluefin`
- `org.opencontainers.image.licenses` = `Apache-2.0`
- `org.opencontainers.image.title` / `.description`

Custom provenance labels (every image self-declares its FSDK base):

- `io.projectbluefin.fsdk.version` = FSDK release (e.g. `25.08.13`)
- `io.projectbluefin.fsdk.ref` = exact junction commit ref

## CI / build orchestration

`.github/workflows/build.yml`:

1. Matrix `[x86_64, aarch64]`.
2. `bst build oci/static.bst` (pulling from the shared CAS caches).
3. `bst artifact checkout` the OCI image.
4. `podman pull oci:...` to load + squash to a single layer; apply dynamic
   labels.
5. Push per-arch tags.
6. `podman manifest create` + push the multi-arch `:latest` / `:25.08` /
   `:25.08.13` manifest.

Justfile recipes are adapted from dakota where they apply (build, checkout,
squash, push) to keep local and CI builds identical.

## Testing / verification

- **Graph resolves**: `bst show --deps all oci/static.bst`.
- **Distroless proof**: `podman run --rm <image> /bin/sh` (or any shell) must
  **fail** — no shell present.
- **Contents present**: `/etc/ssl/certs` (ca-certificates) and
  `/usr/share/zoneinfo` (tzdata) exist in the checked-out layer.
- **CVE target**: `grype`/scanner reports 0 known CVEs (the headline claim).
- **Multi-arch**: `podman manifest inspect` shows both `amd64` and `arm64`.

## Open implementation-time checks

- Exact FSDK component element names for the static set (`glibc.bst`?
  `base-files.bst`? `ca-certificates.bst`, `tzdata.bst`) are verified against the
  pinned junction `ref` via `bst track` + `bst show` — not guessed.
- Confirm FSDK split-rule domain names (`devel`/`debug`/`doc`/`locale`/
  `static-blocklist`) match the pinned FSDK release.
- Confirm `oci-builder`/`build-oci` invocation matches the pinned FSDK
  `components/oci-builder.bst`.

## Future work (out of scope)

- `-dev` shell variants.
- `python`, `node` runtime images (compose from `components/python3.bst` etc.).
- CNCF Go tool images — ONLY for tools without an official upstream distroless
  image. Tools that already ship one (e.g. kubectl) are consumed from upstream,
  never rebuilt (see Hard rule). Each candidate is checked before scoping.
- Drop the `gnome-build-meta` junction once no image needs its `sdk/*` overrides.
- Argo Workflows fan-out for a large image matrix.
