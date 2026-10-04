---
name: kubeadm-sysext
description: Build, ship and operate the opt-in kubeadm systemd-sysext (kubelet, kubeadm, containerd, runc, CNI plugins) as a worker or a single-node control plane, and the base-kernel options it and Cilium need.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-10-02"
---
# kubeadm sysext

## When to Use

- Joining a Bluefin Server node to an existing kubeadm cluster as a worker.
- Running a single-node kubeadm control plane (`kubeadm-init.service`).
- Bumping kubelet/kubeadm/kubectl, crictl, containerd, runc or CNI plugins.
- Changing `containerd.service`, `kubelet.service`, the containerd config, or
  the kernel options Kubernetes networking needs.

## When NOT to Use

- k0s nodes (`k0s-sysext.md`).
- Generic sysext identity and merge rules (`systemd-sysext-extensions.md`).

## Contents

`oci/kubeadm-sysext.bst` emits `kubeadm_<image-version>.raw.zst`, version-locked
to the image like ZFS (`extension-release.kubeadm_<ver>`, `ID=bluefin-server`),
listed in the signed release `SHA256SUMS`, and fetched on installed nodes by the
optional `kubeadm` sysupdate feature (`files/os/sysupdate.d/32-kubeadm.transfer`).
Versions live in `include/kubeadm.yml`; every download is pinned by sha256 in
`elements/kubeadm/kubeadm-bin.bst` (upstream release binaries).

| Path | Source |
|---|---|
| `/usr/bin/{kubelet,kubeadm,kubectl}` | dl.k8s.io |
| `/usr/bin/crictl` | cri-tools |
| `/usr/bin/{containerd,containerd-shim-runc-v2,ctr}` | containerd static build |
| `/usr/bin/runc` | runc static build |
| `/usr/libexec/cni/*` | containernetworking/plugins (whole tarball) |
| `containerd.service`, `kubelet.service`, `kubelet.service.d/10-kubeadm.conf` | `files/kubeadm/sysext/` |
| `/usr/libexec/bluefin-kubeadm-containerd-migrate` | `containerd.service` `ExecStartPre` ([Migration](#migration)) |
| `/usr/share/bluefin/containerd/config.toml`, `/usr/share/bluefin/kubeadm/crictl.yaml` | defaults copied to `/etc` if absent |
| `kubeadm-init.service`, `kubeadm-init-config.service`, `/usr/libexec/bluefin-kubeadm-init`, `/usr/share/bluefin/kubeadm/{init.yaml,init-tmpfiles.conf}` | opt-in control plane ([Single-node control plane](#single-node-control-plane)) |

Nothing ships under `/opt`: `/opt/cni/bin` stays a writable host directory for
the cluster CNI (Cilium's `cilium-cni`). containerd searches
`/opt/cni/bin` then `/usr/libexec/cni`.

## Versions

The sysext runs the Kubernetes minor of the cluster it joins: the series of
`kubernetes-version` in `include/kubeadm.yml`. It does not follow k0s, which
bundles its own Kubernetes for a separate cluster
([k0s-sysext.md](k0s-sysext.md)); the two minors move independently.
`kubeadm join` must use the minor that last ran `kubeadm init` or
`kubeadm upgrade` on that cluster, and kubelet may be older than the API server
but never newer. Patch releases change neither constraint.

- **Patches** are automatic. `.github/workflows/track-binaries.yml` opens one
  pull request per component (Kubernetes, cri-tools, containerd, runc, CNI
  plugins) when a newer patch of its pinned series is out, with the version
  and its sha256 refs (amd64 and arm64) changed together and checked against
  the checksum files upstream publishes. A release missing either
  architecture's asset or checksum is not proposed.
- **Minors** are manual, once the cluster's control plane runs the new minor:
  1. `python3 .github/scripts/track-binaries.py apply kubernetes --version X.Y.Z`,
     and the same for `cri-tools` (its minor follows Kubernetes). `apply`
     verifies the checksums exactly as the tracker does.
  2. Set `pause-image` to the tag that
     `kubeadm config images list --kubernetes-version vX.Y.Z` prints.
  3. Check containerd's `RELEASES.md` support table for the new minor; move
     `containerd` and `runc` with `apply` if it asks for newer ones.
  4. Move the series in `tests/unit/test_kubeadm_sysext.py`, then boot-verify
     as in [Verify](#verify).

## Runtime contract

- No preset enables anything; `80-kubeadm.preset` disables `containerd.service`,
  `kubelet.service` and `kubeadm-init.service` against FSDK's implicit default.
  A worker's Ignition enables the sysext, `containerd.service` and
  `kubelet.service`, and runs `kubeadm join`.
- `systemd-sysext.service` is not ordered against tmpfiles, modules-load or
  sysctl, so `containerd.service` re-applies them in `ExecStartPre`:
  `systemd-tmpfiles --create kubeadm.conf` (seeds a writable
  `/etc/containerd/config.toml` and `/etc/crictl.yaml` only when absent),
  `/usr/libexec/bluefin-kubeadm-containerd-migrate` (backfills the
  `imports` glob on a config that pre-dates drop-in glob support, see
  [Migration](#migration)),
  `modprobe overlay br_netfilter`, then `systemd-sysctl 90-kubeadm.conf`
  (`ip_forward`, `bridge-nf-call-ip{,6}tables`). kubeadm needs containerd
  running, so these hold before any preflight.
- containerd root is `/var/lib/containerd` (`RequiresMountsFor=` orders it after
  a per-node mount), `SystemdCgroup = true`, sandbox `registry.k8s.io/pause:3.10.1`,
  registry `config_path = /etc/containerd/certs.d`.
- The config `imports` two globs, `/usr/share/bluefin/containerd/conf.d/*.toml`
  (drop-ins other sysexts ship: the NVIDIA Container Toolkit's `nvidia`
  runtime handler, [nvidia-sysext.md](nvidia-sysext.md)) and
  `/etc/containerd/conf.d/*.toml` (the node's own). containerd deep-merges
  plugin sections, so a drop-in adds a runtime without restating the rest;
  a glob that matches nothing imports nothing. `/etc/containerd/config.toml`
  is seeded only when absent, so an installed node from before the imports
  existed keeps its old copy; the [migration](#migration) adds the line on
  its next containerd start. Diskless nodes reseed every boot.
- kubelet restarts every 10 s until `kubeadm join` writes
  `/var/lib/kubelet/config.yaml` (standard kubeadm behaviour);
  `--volume-plugin-dir=/var/lib/kubelet/volumeplugins` because `/usr` is read-only.
- `/etc/resolv.conf` links to systemd-resolved's `/run/systemd/resolve/resolv.conf`
  (base image), the path kubelet's `resolvConf` expects.
- While `kubelet.service` runs or restarts, the base image's automatic reboot
  and the boot-deadline rollback reboot stand down and reboots belong to kured
  (the deadline flags `/run/reboot-required`); see "Updates" in
  [ddi-installer.md](ddi-installer.md).

## Migration

`/usr/libexec/bluefin-kubeadm-containerd-migrate` backfills the `imports`
line into an `/etc/containerd/config.toml` seeded before the shipped config
declared it. It runs on every `containerd.service` start, after the tmpfiles
seed and before `modprobe overlay`, so containerd loads its result:

- A config that already declares a **top-level** `imports` key (anywhere
  ahead of the first `[table]` header, leading whitespace allowed) is left
  alone: no write and no mtime change, so DaemonSets and kured see nothing.
  Every config seeded from the current default has one, so fresh installs and
  diskless boots (worker or `kubeadm-init.service` control plane) are
  untouched. A missing file is a no-op too. An `imports =` written *after* a
  table header is nested in that table, which containerd ignores, so such a
  node is still migrated.
- Otherwise it prepends the shipped `imports` line, under a comment naming
  the helper, at line 1. Top-level placement is load-bearing: containerd only
  consults a top-level `imports`, and a key appended after a `[table]` header
  (the old config ends inside `[plugins.'io.containerd.cri.v1.runtime'.cni]`)
  belongs to that table and is silently ignored. Line 1 is the only insertion
  point that is always valid TOML; scanning for the first header cannot tell
  one from the last element of a multi-line top-level array of arrays.
- It writes the new content to a sibling `config.toml.new.<pid>`, checks it
  parses as TOML (`python3`'s `tomllib`, else `containerd config dump`) and
  only then copies it back over the original inode, so mode, owner and
  SELinux label survive. Installing content containerd cannot parse would
  crash-loop it, and the `-` prefix cannot undo a write that succeeded. If
  validation or that copy fails (ENOSPC, read-only or immutable `/etc`), the
  sibling keeps the complete migrated content and the log names it. The
  `ExecStartPre` is `-`-prefixed, so containerd still starts with the old
  config.

An installed node picks it up on its first containerd start after updating
to a kubeadm sysext that ships the helper. The NVIDIA Container Toolkit's
activate unit restarts containerd after merging
([nvidia-sysext.md](nvidia-sysext.md)), so the `nvidia` runtime handler
reaches the GPU Operator on the boot that activates the toolkit sysext.

## Single-node control plane

`kubeadm-init.service` turns the node into a one-node cluster that also runs
workloads. Opt-in: nothing enables it, and a worker never sees its config.

- **Enable it** by linking it into `multi-user.target.wants`. Its unit exists
  only once `systemd-sysext.service` has merged the image after
  switch-root. Ignition's `enabled: true` (a preset line) is applied in the
  initrd's files stage, where the image is not merged, so the unit is absent
  and the selection is skipped on every boot. Ignition writes `/etc/extensions/kubeadm_<ver>.raw`
  (with a sha256 `verification`) and the link
  `/etc/systemd/system/multi-user.target.wants/kubeadm-init.service ->
  /usr/lib/systemd/system/kubeadm-init.service`; after the merge,
  `bluefin-sysext-activate.service` starts it. On an installed node,
  `systemctl enable kubeadm-init.service` once the sysext is merged.
- **Config.** `kubeadm-init-config.service` (static, pulled in only by
  `kubeadm-init.service`) applies `/usr/share/bluefin/kubeadm/init-tmpfiles.conf`
  by absolute path: a tmpfiles `C` that copies the read-only default
  `/usr/share/bluefin/kubeadm/init.yaml` to `/etc/kubernetes/bluefin/init.yaml`
  only if absent. The rule is outside `tmpfiles.d`, so boot-time tmpfiles runs
  never apply it. The default is kubeadm `v1beta4` `InitConfiguration` +
  `ClusterConfiguration` + `KubeletConfiguration`: containerd's CRI socket,
  `cgroupDriver: systemd`, cluster name `bluefin`, pods `10.244.0.0/16`,
  services `10.96.0.0/12`, `imageRepository: registry.k8s.io`, and
  `kubernetesVersion` set by the build from `include/kubeadm.yml`. The build
  fails if the sysext's own `kubeadm config validate` rejects it. The advertise
  address (default route's interface) and Node name (hostname) are left to
  kubeadm. To override them or anything else, write the `/etc` copy (Ignition
  or by hand) before the first init.
- **Run.** After `containerd.service` (`Requires=`), `network-online.target`
  and the seed, if `/etc/kubernetes/admin.conf` is absent and
  `/etc/kubernetes/bluefin/init.yaml` exists, `/usr/libexec/bluefin-kubeadm-init`:
  1. enables `containerd.service` and `kubelet.service`
  2. runs `kubeadm init --config /etc/kubernetes/bluefin/init.yaml --skip-phases=addon/kube-proxy`
     (Cilium replaces kube-proxy, and kubeadm records `proxy.disabled`)
  3. links `/root/.kube/config` to `admin.conf`
  4. removes the `node-role.kubernetes.io/control-plane:NoSchedule` taint

  A failed `kubeadm init` runs `kubeadm reset --force` because a leftover
  `admin.conf` would skip every retry. The unit then retries
  (`Restart=on-failure`, 30 s).
- **Idempotency.** An installed node keeps `admin.conf` and the enable
  symlinks, so later boots skip the unit and start containerd and kubelet
  directly. A diskless node loses `/etc` and `/var` on reboot and initialises
  a fresh cluster on every boot.
- **No CNI ships.** Until one is applied (Cilium with
  `kubeProxyReplacement=true` and `k8sServiceHost` set to the node address),
  the node stays NotReady and CoreDNS Pending.
- **Images are pulled at init** (network required). Offline install will need
  `kubeadm config images list --config /etc/kubernetes/bluefin/init.yaml`
  (kube-apiserver, kube-controller-manager, kube-scheduler, coredns, pause,
  etcd; kube-proxy is listed but not used), which is not solved yet.

**Multi-node homelab.** With the homelab sysext and `HOMELAB_ROLE=control-plane`
in `/etc/bluefin/homelab.conf`, `bluefin-cluster-prepare.service` runs between
the seed and the init: it renames a `localhost` node to
`bluefin-<machine-id[:8]>` and adds `controlPlaneEndpoint: <host>.local:6443`
plus `apiServer.certSANs` to the `/etc` copy (unless it already sets an
endpoint), so nodes reach the API by mDNS name. Nodes (`HOMELAB_ROLE=node`)
join with a passphrase-authenticated bootstrap token; protocol, files and
threat model: [`files/homelab/cluster/README.md`](../../files/homelab/cluster/README.md).
`just dogfood-homelab-cluster` checks it in QEMU. The homelab Ignition
templates set all of this up from one file
([homelab-profile.md](homelab-profile.md)).

`just dogfood-kubeadm` checks the whole path in QEMU: a diskless boot whose
Ignition does only the above, then a test-only pinned Cilium. It needs `helm`
on the host and internet access from the guest.

## Host tools

kubeadm v1.35 preflight requires only `losetup`, `mount` and `cp` in `PATH`
(base image); `conntrack` stopped being required in v1.32. `iptables`,
`ethtool`, `socat` and `conntrack` are not shipped: Cilium carries its own
iptables, kube-proxy is replaced, and containerd 2 port-forwards in-process.

## Kernel options

Cilium (VXLAN tunnel, kube-proxy replacement, L7 proxy, iptables masquerade)
needs options FSDK's kernel lacks. `patches/freedesktop-sdk/0006-*.patch`
appends them to FSDK's `files/linux/fdsdk-config.sh`, whose expected-config
check fails the kernel build if Kconfig drops one: `VXLAN`, `GENEVE`,
`NET_CLS_BPF`, `NET_SCH_INGRESS`, `NET_ACT_BPF`, `INET_DIAG`, `INET_TCP_DIAG`,
`INET_UDP_DIAG`, `NETFILTER_XT_TARGET_NOTRACK` (all `=m`)
and `INET_DIAG_DESTROY` (socket-LB termination). The rest of Cilium's and
kubeadm's system-validator lists is already in FSDK's config. These are base
image options; modules are signed by `bluefin-server/kernel-modules.bst`.

## iSCSI

The base image (not this sysext) ships FSDK's open-iscsi: `/usr/bin/iscsiadm`
and `iscsid`, with `iscsid.socket` enabled by `80-bluefin-iscsi.preset` so
iscsid starts on first use. `iscsid.service` requires `iscsi-init.service`,
which writes `/etc/iscsi/initiatorname.iscsi` only if absent (a fresh name per
diskless boot; an Ignition-written file wins). `iscsi.service` auto-login is
off. `/etc/iscsi/iscsid.conf` comes from the factory `/etc`
(`30-bluefin-iscsi.conf` restores it and creates `/var/lib/iscsi`), which is
what democratic-csi's `chroot /host ... iscsiadm` node plugin needs.

## NFS

The base image ships an NFS client built from source
(`bluefin-server/nfs-utils.bst`, `bluefin-server/rpcbind.bst`; FSDK 26.08
has neither): `mount.nfs`/`mount.nfs4`/`umount.nfs` in `/usr/bin` (reached
through `/sbin -> usr/sbin -> bin`), `rpc.statd`, `sm-notify`, `nfsidmap`,
`nfsstat`, `showmount`. Without `mount.nfs`, util-linux `mount -t nfs`
falls through to the new mount API and the kernel refuses (`fsconfig()
failed: NFS: mount program didn't pass remote address`), which is what
kubelet reported for every NFS PV. Client only: no server daemons, no
GSS/Kerberos (`sec=krb5*` mounts are unsupported). `80-bluefin-nfs.preset`
enables `nfs-client.target` and `rpcbind.socket`; `mount.nfs` starts
`rpc-statd.service` on demand for NFSv3 locking (NFSv4 needs neither).
NFSv3's portmapper and mountd lookups go through libtirpc, which resolves
`tcp`/`udp` and `sunrpc` from `/etc/protocols` and `/etc/services`; without
them `mount.nfs` fails with `Failed to find 'tcp' protocol`. Both come from
FSDK's `components/iana-config.bst` in `os-base.bst` and are linked (tmpfiles
`L`, not copied) from the factory `/etc`, so an A/B update refreshes them.
`/var/lib/nfs/statd` comes from tmpfiles.d, owned by `rpcuser`; on a
diskless node it is lost at reboot, so NFSv3 servers are not notified when a
rebooted diskless client held locks. NFSv4 id mapping uses the kernel
`request-key` upcall to `nfsidmap` (`/etc/request-key.d/id_resolver.conf`).

## Known gaps

- aarch64: the arm64 release binaries are pinned, but no aarch64 image has
  been built or booted.

## Verify

`just export-image`, then `just dogfood-kubeadm` (single-node control plane:
node Ready, CoreDNS Ready). For a worker, boot diskless with
`DOGFOOD_EXTRA_PROBE` activating `kubeadm_<ver>.raw` (copy to
`/run/extensions`, `systemd-sysext refresh`) and check `crictl info`,
`kubeadm init phase preflight`.
