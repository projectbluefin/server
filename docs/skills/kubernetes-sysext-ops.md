---
name: kubernetes-sysext-ops
description: Operator runbook for the Kubernetes systemd-sysext — kubeadm bring-up, the seed phases, Argo CD Core troubleshooting, and runtime testing.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-09-19"
  context7-sources:
    - /systemd/systemd
---
# Kubernetes systemd-sysext Operations

Use this skill when running, testing, or debugging Kubernetes on a live Bluefin Server
host. For building and versioning the image itself, see
[kubernetes-sysext.md](kubernetes-sysext.md).

## Bring-up model

First boot is fully unit-driven. Nothing here is a manual step on a correctly
provisioned host; the commands below are for inspection and recovery.

```
systemd-sysext.service            merge containerd + kubernetes sysexts into /usr
  -> daemon-reload                a merge makes unit files appear; systemd must be told
bluefin-cluster-repo.service      init /var/lib/bluefin/cluster.git from /usr/share/bluefin/cluster
kubeadm-init.service              kubeadm init --config /usr/share/bluefin/kubeadm.yaml
bluefin-cluster-bootstrap.service apply the four seed phases in order
```

`kubeadm-init.service` carries `ConditionPathExists=!/etc/kubernetes/admin.conf`, so it
is a no-op on an already-initialised host. `bluefin-cluster-bootstrap.service` carries no
such condition on purpose: a failed condition marks a unit *skipped* rather than *failed*,
which would silently no-op the first boot.

## Enabling Kubernetes on a Host

On a running Bluefin Server system:

```bash
just k8s
```

Or manually:

```bash
# 1. Fetch the extension image into /var/lib/extensions/.
systemd-sysupdate --component=kubernetes update

# 2. Merge into /usr, then let systemd see the new unit files.
systemd-sysext merge
systemctl daemon-reload

# 3. Bring the cluster up. bluefin-cluster-bootstrap orders itself after
#    kubeadm-init and bluefin-cluster-repo, and pulls both in (Wants= on the
#    former, Requires= on the latter).
systemctl enable --now bluefin-cluster-bootstrap.service
```

`kubeadm init` runs with `--skip-phases=addon/kube-proxy`; Cilium supplies the
kube-proxy replacement.

## The seed phases

The seed is applied by `bluefin-cluster-bootstrap.service` from
`/usr/share/bluefin/seed/`, with `kubectl apply --server-side --force-conflicts`, in
directory order:

| Phase | Contents | Why it is in the seed and not in Argo |
|---|---|---|
| `00-cilium/` | CNI, kube-proxy replacement | Argo's own pods need pod networking; a node without CNI stays `NotReady` with a `NoSchedule` taint. |
| `10-argocd-core/` | Argo CRDs, RBAC, redis, repo-server, application-controller | Argo cannot install Argo. |
| `15-gitd/` | git-daemon serving `/var/lib/bluefin/cluster.git` | The root Application needs the repository served before Argo can read anything. |
| `20-root-app/` | `AppProject` + root `Application` | Hands ownership of everything downstream to Argo. |

The bootstrap unit waits for the node to report `Ready` between `00-cilium/` and
`10-argocd-core/`.

The seed is **append-only by construction and is never pruned**. Argo owns pruning for
all downstream workload via `prune: true`; both upstream `kubectl` pruning modes are
alpha and unsuitable. Do not reopen this.

## Argo CD Core

Core runs exactly three pods: `argocd-application-controller`, `argocd-repo-server`, and
`argocd-redis`. There is no `argocd-server`, no `argocd-dex-server`, and no
`argocd-notifications-controller`.

Consequences for operators:

- **There is no web UI and the `argocd` CLI does not work.** The CLI speaks gRPC to
  `argocd-server`, which Core does not ship. Manage Applications as plain Kubernetes
  custom resources with `kubectl`.
- `argocd-applicationset-controller` is patched out; this design has exactly one root
  Application. Its CRD is left in place, harmlessly.
- Redis is an in-memory cache with no PersistentVolumeClaim. There is no supported
  redis-free Argo CD, so a missing redis is a fault, not a configuration choice.
- Two residual `argocd-server` NetworkPolicy `podSelector` rules admit traffic from a pod
  that never exists. They are inert and deliberately left unmodified.

Inspecting sync state:

```bash
kubectl -n argocd get applications
kubectl -n argocd describe application bluefin-cluster
kubectl -n argocd logs deploy/argocd-repo-server
kubectl -n argocd logs statefulset/argocd-application-controller
```

## Manifest source bridge

Argo's `Application.source` accepts git, Helm, or OCI — there is no filesystem source, so
Argo cannot read `/usr/share/bluefin/cluster/` directly. `bluefin-cluster-repo.service`
initialises a bare repository at `/var/lib/bluefin/cluster.git` from that tree on first
boot, and the `15-gitd/` git-daemon serves it over the cluster network. No external git
host is contacted, so the manifest tree stays available with the network unplugged.

Updating the tree means updating the image: a new DDI re-seeds
`/usr/share/bluefin/cluster/`, and `bluefin-cluster-repo.service` refreshes the bare repo.

## Troubleshooting

- **Extension not merged**: `systemd-sysext status`. Verify a
  `/var/lib/extensions/kubernetes-<version>.raw` exists; if not, the sysupdate fetch is
  the failure, not the merge.
- **Merged but nothing runs**: the merge makes unit files appear under `/usr` but does not
  by itself make systemd notice them. Run `systemctl daemon-reload` and re-check.
- **`kubeadm-init.service` skipped, cluster absent**: `/etc/kubernetes/admin.conf` already
  exists from a previous partial run. Inspect it before removing it; `kubeadm reset` is
  the supported way back to a clean state.
- **Node stays `NotReady`**: CNI is not up. `kubectl -n kube-system get pods -l k8s-app=cilium`
  and `journalctl -u bluefin-cluster-bootstrap -e`.
- **Pods `Pending` with a `NoSchedule` taint**: same cause; the taint clears when Cilium
  reports the node `Ready`.
- **kubelet serving certificate never issued**: kube-controller-manager does not
  auto-approve serving CSRs. `kubelet-csr-approver` is mandatory, not optional. Check
  `kubectl get csr` for `Pending` entries and the approver's `--provider-regex`.
- **Root Application will not sync**: check the git-daemon first —
  `kubectl -n bluefin-system logs deploy/bluefin-git-daemon` — then the bare repo at
  `/var/lib/bluefin/cluster.git` on the host.
- **Bootstrap unit failed**: `journalctl -u bluefin-cluster-bootstrap -e`. The unit is
  ordered `After=kubeadm-init.service` but only `Wants=` it, so a control plane that
  never came up shows here as the `ExecStartPre` readiness probe timing out against the
  API server; `journalctl -u kubeadm-init -e` names the underlying cause. `Requires=` is
  deliberately not used: a job killed with result `dependency` never runs, so its own
  `Restart=on-failure` never engages and one transient `kubeadm init` failure would
  strand the seed permanently.

## Runtime testing

```bash
just show-me-the-future     # QEMU installer smoke test through to multi-user
```

Acceptance on a booted host: containerd active, `kubectl get nodes` reports `Ready`, the
three Argo Core pods reach `Running`, and the root Application syncs.

Workload images are still pulled from public registries, so "fully automated first boot"
currently means "with network present". Image pre-seeding into containerd is tracked
separately.

## See also

- [kubernetes-sysext.md](kubernetes-sysext.md)
- [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md) — OTA trust model.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary (Sysext definition).
- `systemd-sysext(8)`
