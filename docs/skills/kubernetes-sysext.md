---
name: kubernetes-sysext
description: Build, ship, and version the upstream Kubernetes systemd-sysext (kubeadm, kubelet, kubectl, CNI plugins) for Bluefin Server.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-09-19"
  context7-sources:
    - /systemd/systemd
---
# Kubernetes systemd-sysext

Use this skill when working on the Kubernetes `systemd-sysext` extension shipped as an
optional overlay for Bluefin Server.

## When to Use

- Bumping the pinned Kubernetes or CNI plugin version and its SHA256 pins.
- Modifying the sysext image contents (`elements/kubernetes/`, `files/kubernetes/sysext/`).
- Changing the `kubeadm` cluster configuration (`files/kubernetes/kubeadm.yaml`).
- Adding or changing the sysupdate transfer definition
  (`files/os/sysupdate.kubernetes.d/70-kubernetes.transfer`).
- Debugging why a host cannot pull or merge the Kubernetes sysext.

## When NOT to Use

- Bringing up, troubleshooting, or operating a live cluster — use
  [kubernetes-sysext-ops.md](kubernetes-sysext-ops.md).
- Seed and Argo-owned manifest content — that tree lives under `files/cluster/`.
- General OS image composition questions (use `ddi-installer.md` or `avoid-over-engineering.md`).
- systemd-sysupdate signature verification (use `systemd-sysupdate-verification.md`).

## Architecture

Bluefin Server's base DDI image includes bash for login and bring-up, while heavy
developer and debug tools live in sysexts or system containers. Kubernetes is not baked
into the OS stack. It is delivered as a `systemd-sysext` EROFS image that overlays `/usr`
at runtime.

Design choices:

- **Upstream binaries, no distribution.** `elements/kubernetes/` imports `kubeadm`,
  `kubelet`, and `kubectl` from `dl.k8s.io`, each pinned to a published SHA256. There is
  no embedded control plane and no vendor-specific control-plane wrapper.
- **Re-baked in-repo.** The element re-bakes the `flatcar/sysext-bakery` `kubernetes.sysext`
  recipe under BuildStream rather than consuming the published artifact, so release signing
  and provenance stay in this repository. The output layout is wire-compatible with
  `extensions.flatcar.org`, so an operator can repoint the sysupdate source upstream
  without changing anything else.
- **containerd is a separate sysext.** The runtime ships as Flatcar's
  `containerd-flatcar.raw`; it is never part of this image and never part of the base DDI.
- **Flatcar sysext pattern.** The extension uses `ID=_any` in its release metadata so it
  merges on any host image.
- **Minor-pinned OTA track.** `70-kubernetes.transfer` tracks a minor-pinned track because
  Kubernetes does not support unattended cross-minor in-place upgrades. Crossing a minor
  is a deliberate operator action, not an automatic one.

## Repository Layout

| Path | Purpose |
|------|---------|
| `include/kubernetes.yml` | **Single source of truth for the version axis** (`%{k8s-version}`, `%{cni-version}`). |
| `elements/kubernetes/` | Pins the upstream `kubeadm`, `kubelet`, `kubectl` and CNI plugin SHA256s; release URLs are derived from `include/kubernetes.yml`. |
| `elements/oci/kubernetes-sysext.bst` | Builds the EROFS sysext image (`kubernetes-<k8s-version>.raw`). |
| `files/kubernetes/sysext/extension-release.kubernetes` | Static sysext identity (`NAME=kubernetes`, `ID=_any`); `VERSION_ID=`/`ARCHITECTURE=` are appended at build time. |
| `files/kubernetes/kubeadm.yaml` | `kubeadm` cluster configuration, staged to `/usr/share/bluefin/kubeadm.yaml`. |
| `files/cluster/seed/` | Seed phases applied before Argo owns the cluster; staged to `/usr/share/bluefin/seed/`. |
| `files/cluster/manifests/` | Argo-owned workload tree; staged to `/usr/share/bluefin/cluster/`. |
| `files/os/sysupdate.kubernetes.d/70-kubernetes.transfer` | sysupdate transfer track for the Kubernetes sysext component. |
| `Justfile` | `build-sysext` / `export-sysext` targets. |
| `.github/workflows/build.yml` | Builds, signs, and publishes sysext assets. |
| `.github/scripts/check-kubernetes-version.py` | Fails closed if any consumer restates the version instead of deriving it. |

## Image Contents

Mirroring the upstream bakery recipe:

- `/usr/bin/{kubectl,kubeadm,kubelet}`
- `/usr/local/bin/cni/` from the `containernetworking/plugins` release tarball
- `/usr/local/share/kubernetes-version`, `/usr/local/share/kubernetes-cni-version`
- `/usr/lib/extension-release.d/extension-release.kubernetes`

No certificate or key material ships in any image. kubelet client certificates come from
`kubeadm`'s native TLS bootstrap; kubelet serving certificates come from
`serverTLSBootstrap` plus `kubelet-csr-approver`; everything else is issued by
cert-manager in-cluster.

## Build Outputs

`elements/oci/kubernetes-sysext.bst` produces:

- `kubernetes-<k8s-version>.raw` — uncompressed EROFS sysext image.
- `kubernetes-<k8s-version>.raw.zst` — zstd-compressed release asset.
- `SHA256SUMS` — checksum manifest for the compressed asset.

## Bumping the version

1. Edit `include/kubernetes.yml` — it is the only place a version literal may appear.
2. Replace every affected SHA256 in `elements/kubernetes/` with the value published
   alongside the upstream artifact. Never invent a checksum.
3. If the Kubernetes **minor** changed, update the minor-pinned track name in
   `files/os/sysupdate.kubernetes.d/70-kubernetes.transfer`.
4. Run `just validate`; `check-kubernetes-version.py` fails closed when a consumer
   restates the version instead of deriving it from `include/kubernetes.yml`.

## Justfile Commands

```bash
just validate              # resolve the element graph and check the version axis
just build-sysext          # build oci/kubernetes-sysext.bst
just export-sysext         # export sysext artifacts to dist/sysext/
```

## Operations and runtime testing

For bringing a cluster up on a host, the seed phases, and troubleshooting guidance,
see [kubernetes-sysext-ops.md](kubernetes-sysext-ops.md).

## See also

- [kubernetes-sysext-ops.md](kubernetes-sysext-ops.md)
- [systemd-sysext-extensions.md](systemd-sysext-extensions.md) — extension identity and loading.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary (Sysext definition).
- `systemd-sysext(8)`, `systemd-confext(8)`
