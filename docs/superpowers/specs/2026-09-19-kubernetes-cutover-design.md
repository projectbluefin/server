# Design Spec: Upstream Kubernetes Cutover with Argo CD Core GitOps

## Context & Purpose

Bluefin Server currently delivers Kubernetes as k0s: a single static binary carrying an
embedded control plane, an embedded container runtime, and a proprietary manifest deployer
that reconciles `/var/lib/k0s/manifests/`.

This specification defines the complete removal of k0s and its replacement with upstream
Kubernetes (`kubeadm`, `kubelet`, `kubectl`) delivered as a `systemd-sysext`, Cilium as CNI,
containerd sourced from Flatcar's `/usr`, and **Argo CD Core** as the reconciler for all
in-cluster workload.

The decision to run upstream Kubernetes is a product decision and is not re-litigated here.
This document records how the cutover is executed and which properties must be rebuilt.

---

## What k0s Provided That Must Be Rebuilt

k0s's stack applier supplied four properties for free. Upstream Kubernetes ships no addon
manager, so each must be replaced explicitly:

| Property | k0s mechanism | Replacement |
|---|---|---|
| Apiserver readiness | applier runs inside the controller process | `kubeadm-init.service` ordering edge |
| Ordering | alphabetical directory scan with retry | explicit seed phases, then Argo sync waves |
| Drift correction | continuous reconcile loop | Argo `selfHeal: true` |
| Pruning | label-tracked stack membership | Argo `prune: true` |

Upstream's only in-tree mechanisms are static pods (Pod kind only, node-local),
`kubeadm init phase addon` (hardcoded to CoreDNS and kube-proxy), and `kubectl` with
kustomize. The historical `kube-addon-manager` was removed. Every distro that offers a
manifest directory implements it privately; leaving k0s means leaving that layer, not
losing a k0s-specific feature.

---

## Architecture

### Delivery layers

| Layer | Mechanism | Contents |
|---|---|---|
| Base DDI | BuildStream, Flatcar `/usr` | systemd, networkd, sysupdate, `crictl` |
| Runtime sysext | Flatcar `containerd-flatcar.raw` | containerd, runc, containerd shims |
| Kubernetes sysext | BuildStream re-bake of the bakery recipe | `kubeadm`, `kubelet`, `kubectl`, CNI plugins |
| Seed | `kubectl apply -k`, four directories | Cilium, Argo CD Core, git-daemon, root Application |
| Workload | Argo CD Core | everything else, including Argo itself |

### First-boot unit sequence

```
systemd-sysext.service          merge containerd + kubernetes sysexts into /usr
  -> daemon-reload              (see "Sysext activation" below)
bluefin-cluster-repo.service    init /var/lib/bluefin/cluster.git from /usr/share/bluefin/cluster
kubeadm-init.service            kubeadm init --config, skipping the kube-proxy addon
bluefin-cluster-bootstrap.service
    apply 00-cilium/            CNI; nothing schedules before this
    wait node Ready
    apply 10-argocd-core/       Argo CRDs, RBAC, redis, repo-server, application-controller
    apply 15-gitd/              git-daemon serving /var/lib/bluefin/cluster.git
    apply 20-root-app/          one Application; Argo owns everything downstream
```

### Seed contents

```
/usr/share/bluefin/seed/
  00-cilium/        CNI, kube-proxy replacement
  10-argocd-core/   upstream core-install.yaml, applicationset-controller patched out
  15-gitd/          git-daemon Deployment + Service, hostPath /var/lib/bluefin/cluster.git
  20-root-app/      AppProject + root Application
```

The seed is **append-only by construction**. It is never pruned. See "Closed decision:
pruning" below for why this matters.

### Argo-owned tree

```
/usr/share/bluefin/cluster/
  cert-manager + SelfSigned -> CA Issuer
  kubelet-csr-approver
  KubeFlex CRDs + operator
  PostgreSQL
  KubeStellar core controller-manager
  KubeStellar console
  kiosk proxy
  ControlPlane CR + local-cluster registration
  argocd-core self-management
```

---

## Detailed Component Specifications

### 1. Kubernetes sysext (`elements/oci/kubernetes-sysext.bst`)

Re-bakes the `flatcar/sysext-bakery` `kubernetes.sysext` recipe under BuildStream rather
than consuming the published artifact, so release signing and provenance remain in-repo.
The output layout stays wire-compatible with `extensions.flatcar.org`, so an operator can
repoint the sysupdate source at upstream without changing anything else.

Contents, mirroring the upstream recipe:

- `/usr/bin/{kubectl,kubeadm,kubelet}` from `dl.k8s.io/<version>/bin/linux/<arch>/`, each
  pinned and verified against its published `.sha256`.
- `/usr/local/bin/cni/` from the `containernetworking/plugins` release tarball.
- `/usr/local/share/kubernetes-version`, `/usr/local/share/kubernetes-cni-version`.
- `/usr/lib/extension-release.d/extension-release.kubernetes`.

`include/kubernetes.yml` replaces `include/k0s.yml` as the single version source.
`.github/scripts/check-kubernetes-version.py` replaces the k0s checker and fails closed
when a consumer restates the version instead of deriving it.

The sysupdate transfer tracks a **minor-pinned** track (`kubernetes-v1.NN.conf`) because
Kubernetes does not support unattended cross-minor in-place upgrades.

### 2. containerd

Flatcar's `/usr` tarball already contains the runtime as a sysext blob. Verified against
the Flatcar 4593.2.5 image contents listing:

```
./usr/share/flatcar/sysext/containerd-flatcar.raw   26,001,408
./usr/share/flatcar/sysext/docker-flatcar.raw       57,118,720
./usr/bin/crictl                                    31,488,432
```

No `containerd`, `dockerd`, `runc` or `ctr` binaries exist in `/usr/bin`; only `crictl`.
Acquisition is therefore free and `elements/flatcar/container-runtime-reference-sysexts.bst`
stays reference-only.

`elements/flatcar/flatcar-usr.bst` gains explicit removals in the existing no-wildcard
style:

- `usr/share/flatcar/sysext/docker-flatcar.raw`
- `usr/share/flatcar/etc/extensions/docker-flatcar.raw`

Docker is not shipped: it is a second unused runtime and 57 MiB charged against the 1 GiB
verity budget that the verity `/usr` work introduces.

### 3. Sysext activation

`flatcar-usr.bst` removes Flatcar's `ensure-sysext.service`, `download_sysext`, and the
`sysinit.target.wants` enablement symlink. Bluefin does not run Flatcar's `/etc` seeding
either, so the `usr/share/flatcar/etc/extensions/` symlinks are inert.

Activation therefore requires an explicit replacement. `systemd-sysext.service` is present
and enabled in Flatcar's `/usr` and scans the standard extension search paths.

**Must verify before implementation:** whether `systemd-sysext.service` performs a
`daemon-reload` after merging at the FSDK systemd version. A merge makes unit files appear
under `/usr`; it does not by itself make systemd notice a new `containerd.service`. Both
the bakery (`RELOAD_SERVICES_ON_MERGE="true"`) and this repo's own `k0s-first-boot.service`
(merge, then `daemon-reload`, then `enable --now`) reload explicitly. If the FSDK unit does
not, carry a drop-in that does. Failing to confirm this reproduces a silent failure mode:
image merged, no runtime running.

`kubeadm-init.service` carries an explicit ordering edge on the merge completing.

### 4. Cilium

Cilium is applied by the seed, not by Argo: Argo's pods require pod networking, and a node
without CNI stays `NotReady` and carries a `NoSchedule` taint.

`kubeadm init` runs with `--skip-phases=addon/kube-proxy`; Cilium provides kube-proxy
replacement.

### 5. Argo CD Core (`10-argocd-core/`)

Upstream `manifests/core-install.yaml`, not a hand-vendored subset. Verified workload
delta against `manifests/install.yaml`:

| Workload | `install.yaml` | `core-install.yaml` |
|---|---|---|
| `argocd-application-controller` | yes | yes |
| `argocd-repo-server` | yes | yes |
| `argocd-redis` | yes | yes |
| `argocd-applicationset-controller` | yes | yes |
| `argocd-server` | yes | no |
| `argocd-dex-server` | yes | no |
| `argocd-notifications-controller` | yes | no |

Core additionally drops one of the three `redis.server` consumers along with
`argocd-server`. Two remain: `repo-server` and `application-controller`. Redis is an
in-memory cache with no PersistentVolumeClaim anywhere in the manifest; it caches rendered
manifests and the live resource tree. There is no supported redis-free Argo CD, so redis is
the floor, not a choice.

`argocd-applicationset-controller` is removed by kustomize patch: the deployment generates
Applications from templates and this design has exactly one root Application. Its CRD is
left in place, harmlessly.

Two residual `argocd-server` references survive in Core as NetworkPolicy `podSelector`
rules admitting traffic from a pod that never exists. Inert; left untouched to keep the
upstream manifest unmodified.

Resulting footprint: three pods — `application-controller`, `repo-server`, `redis`.

No web UI and no `argocd` CLI, which speaks gRPC to `argocd-server`. Applications are
managed as plain Kubernetes custom resources. This removes a second authenticated web
surface from the appliance; the KubeStellar console remains the only dashboard.

### 6. Manifest source bridge (`15-gitd/`)

Argo's `Application.source` accepts git, Helm, or OCI. There is no filesystem source, so
Argo cannot read `/usr/share/bluefin/cluster/` directly. This is an impedance mismatch
between how an image-based OS delivers files and how Argo consumes them.

`bluefin-cluster-repo.service` initialises a bare repository at
`/var/lib/bluefin/cluster.git` from the seed tree on first boot. A minimal git-daemon
Deployment serves it over the cluster network with a hostPath mount, and the root
Application targets it.

The git-daemon **must** live in the seed and **cannot** be an Argo manifest: the root
Application needs the repository to exist and be served before Argo can read anything.
Same class of circular dependency as Cilium.

This is preferred over `repoURL: file://` against a hostPath-mounted bare repo. That
pattern is undocumented, repo-server runs non-root with its own volume layout, and the
failure would surface mid-implementation.

Offline behaviour is preserved: no external git host is contacted. Manifests remain
available with the network unplugged, satisfying the offline-install constraint.

### 7. Certificates

No certificate or key material ships in any image.

- kubelet **client** certificates: `kubeadm`'s native TLS bootstrap, with
  `rotateCertificates: true`.
- kubelet **serving** certificates: `serverTLSBootstrap: true` plus `kubelet-csr-approver`
  with a strict `--provider-regex` and bounded `--max-expiration-sec`.
  kube-controller-manager does not auto-approve serving CSRs, so this component is
  mandatory rather than optional.
- Console, kiosk and in-cluster TLS: cert-manager, SelfSigned bootstrap into a CA Issuer,
  auto-renewed leaf certificates.

This permanently replaces the build-time self-signed key currently baked into the k0s
sysext.

---

## Closed decision: pruning

The seed is applied with `kubectl apply --server-side --force-conflicts` and is **never
pruned**. Argo owns pruning for all downstream workload via `prune: true`.

Both upstream kubectl pruning modes are alpha and unsuitable:

- Allowlist `--prune`: "Alpha since Kubernetes v1.5", and per upstream documentation "still
  in alpha due to usability, correctness and performance issues with its design".
- ApplySet `--prune --applyset`: "Alpha since Kubernetes v1.27", gated behind
  `KUBECTL_APPLYSET=true`, carrying an explicit warning that "backwards incompatible
  changes might be introduced in subsequent releases".

The decisive constraint is ApplySet's namespace rule: "ApplySets spanning multiple
namespaces must use a cluster-scoped custom resource as the parent object." The seed spans
`kube-system`, `argocd`, and later `cert-manager` and the KubeStellar namespaces, so
pruning it would require defining a custom CRD purely to act as an ApplySet parent.

`--prune` is additionally incompatible with `--server-side`; only the ApplySet path is
server-side-apply compatible.

Append-only seed plus Argo-owned reconciliation avoids the entire question. This decision
is closed and should not be reopened without upstream promoting ApplySet to beta.

---

## Installer

`systemd-sysinstall` and `systemd-repart` have no Kubernetes awareness and will not gain
any; AGENTS.md scopes the installer to `systemd-sysinstall`-native, `systemd-repart`-based
behaviour. Their native capability is file placement via `CopyFiles=`, which is how the k0s
sysext is seeded today.

Manifests therefore ship inside the DDI at `/usr/share/bluefin/`, with the OEM partition
available for per-site overrides once the Flatcar partition layout lands. Defaults stay
immutable inside the verity-sealed image; site-specific material lives on OEM alongside
`systemd-creds`.

---

## Purge & Replacement Matrix

| k0s component | Action | Replacement |
|---|---|---|
| `include/k0s.yml` | Deleted | `include/kubernetes.yml` |
| `elements/k0s/k0s-bin.bst` | Deleted | `elements/kubernetes/` binary imports |
| `elements/oci/k0s-sysext.bst` | Deleted | `elements/oci/kubernetes-sysext.bst` |
| `elements/bluefin-server/os-k0s-first-boot.bst` | Deleted | `os-cluster-bootstrap.bst` |
| `elements/bluefin-server/os-k0s-sysupdate.bst` | Deleted | `os-kubernetes-sysupdate.bst` |
| `files/k0s/sysext/k0scontroller.service` | Deleted | `kubeadm-init.service` + kubelet unit |
| `files/k0s/sysext/k0s-manifests.conf` | Deleted | none; manifests applied from `/usr` |
| `files/k0s/k0s.yaml` | Deleted | `/usr/share/bluefin/kubeadm.yaml` |
| `files/k0s/manifests/argocd/install.yaml` | Deleted | upstream `core-install.yaml` |
| `files/k0s/manifests/kubestellar/01-*-github-oauth.yaml` | Deleted | none; no baked secrets |
| `files/k0s/manifests/kubestellar/*` | Moved | `/usr/share/bluefin/cluster/`, digest-pinned |
| `files/k0s/kubeflex/generate-postgres-secret.sh` | Deleted | in-cluster generated Secret |
| `files/k0s/kiosk/{cert,key}.pem` | Deleted | cert-manager issued |
| `files/k0s/kiosk/{nginx.conf,kiosk-gate.js,kiosk-gate.css}` | Moved | ConfigMap; hostPath removed |
| `files/os/systemd/system/k0s-first-boot.service` | Deleted | `bluefin-cluster-bootstrap.service` |
| `files/os/systemd/system/k0s-first-boot-fetch.service` | Deleted | sysupdate handles fetch |
| `files/os/systemd/system-preset/zz-enable-k0s-first-boot.preset` | Deleted | equivalent preset |
| `files/os/sysupdate.k0s.d/70-k0s.transfer` | Deleted | `70-kubernetes.transfer` |
| `files/installer/repart.d/30-var.conf` k0s `CopyFiles` | Deleted | sysext seeding |
| `.github/scripts/check-k0s-version.py` | Deleted | `check-kubernetes-version.py` |
| `tests/unit/test_k0s_first_boot.py` | Deleted | `test_cluster_bootstrap.py` |
| `tests/unit/test_k0s_manifests.py` | Deleted | `test_cluster_manifests.py` |
| `tests/unit/test_k0s_version.py` | Deleted | `test_kubernetes_version.py` |
| `docs/skills/k0s-sysext.md` | Deleted | `docs/skills/kubernetes-sysext.md` |
| `docs/skills/k0s-sysext-ops.md` | Deleted | `docs/skills/kubernetes-sysext-ops.md` |
| `Justfile` `k8s` target | Updated | targets `kubeadm`/`kubectl` |
| `AGENTS.md` hard rule 4 | Updated | see ADR scope below |
| `docs/skills/index.md`, `factory-integration.md`, `CONTEXT.md`, `NOTES.md` | Updated | k0s references purged |

Acceptance gate: `grep -ri k0s` matches only the ADR and the changelog.

### ADR scope

Hard rule 4 currently reads: *"Deliver k0s as an optional `systemd-sysext`; never bundle
Kubernetes or container runtimes into the base OS DDI."*

Only the k0s mandate changes, to deliver **Kubernetes** as an optional sysext. The
container-runtime clause is untouched and remains satisfied: containerd ships as a sysext,
not as base-DDI content.

### Superseded pull requests

| PR | Disposition | Reason |
|---|---|---|
| #178 | Close as superseded | hand-vendors 422 lines into a deleted directory; ships no `argoproj.io` CRDs; dead `ARGOCD_GIT_SHARED_DIR` emptyDir; port 443 named `https` fronting plaintext |
| #81 | Close as superseded | pins an EOL `argocd-server` image that Core does not ship |
| #169 | Close as superseded | superseded by #80 |
| #177 | Close against `core-install.yaml` | Core supplies the complete, correctly wired stack |

---

## Verification & Testing Strategy

1. **Element graph** — `just validate` resolves with zero dangling k0s nodes.
2. **Unit tests**
   - `test_kubernetes_version.py`: version single-source invariants.
   - `test_flatcar_usr.py`: extended to assert both Docker paths removed and containerd
     present exactly once.
   - `test_cluster_manifests.py`: every seed and cluster overlay builds under
     `kubectl kustomize` offline, and every image carries a digest.
   - Secret-material scan across `files/` and `elements/` returns nothing loadable.
3. **Sysext build** — `just build-sysext && just export-sysext` produce the Kubernetes
   sysext and `SHA256SUMS`.
4. **Boot proof** — `just show-me-the-future` reaches multi-user; containerd active;
   `kubectl get nodes` reports `Ready`; the three Argo Core pods reach `Running`; the root
   Application syncs; the KubeStellar console serves live cluster state behind a
   cert-manager certificate of under 100 days validity.
5. **Manifest-source proof** — with no external git host reachable, the root Application
   syncs from `/var/lib/bluefin/cluster.git` via the git-daemon bridge. This proves the
   manifest tree needs no external host. It does **not** prove a fully offline boot:
   workload images are still pulled from public registries, so a complete
   network-unavailable boot is gated on open item 2 below and is not an acceptance
   criterion for this spec.

---

## Open items requiring verification before implementation

1. `systemd-sysext.service` post-merge `daemon-reload` behaviour at the FSDK systemd
   version; carry a reload drop-in if absent.
2. Image pre-seeding into containerd. Every workload manifest currently pulls from
   `quay.io`, `ghcr.io` and `docker.io`. Until images are pre-seeded, "fully automated
   first boot" means "with network present". This is a pre-existing condition, not a
   regression, and is tracked separately.
3. **No OTA channel for the containerd sysext.** `elements/flatcar/containerd-sysext.bst`
   pins one Flatcar runtime image (containerd 2.1.5, runc 1.3.3) and
   `files/installer/repart.d/30-var.conf` seeds it to
   `/var/lib/extensions/containerd-flatcar.raw`. There is no
   `sysupdate.containerd.d` transfer, and the `ID=_any` repack means the seeded image
   keeps merging across every OS update rather than being rejected, so an installed
   host holds that exact containerd/runc until it is reinstalled — no patch path for a
   runtime CVE. This is a regression against k0s, whose embedded runtime rode the
   `k0s-@v` transfer.

   It is deliberately not closed by pointing a transfer at Flatcar's published
   `rootfs-included-sysexts/containerd-flatcar.raw`: that image carries
   `ID=flatcar` with a concrete `VERSION_ID`, which is exactly the metadata this
   element repacks away. Fetching it unmodified would reintroduce the os-release
   mismatch, `systemd-sysext` would refuse the merge, and `containerd.service`
   would vanish on the next boot. A transfer must therefore consume a
   *repacked* image published on this repository's own release feed, alongside
   `kubernetes-@v.raw.zst` — i.e. the sysext has to become a release artifact
   before `70-containerd.transfer` can exist. Until then, runtime CVEs are
   remediated by reinstall.
