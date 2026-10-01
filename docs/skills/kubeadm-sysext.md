---
name: kubeadm-sysext
description: Build, ship and operate the opt-in kubeadm worker systemd-sysext (kubelet, kubeadm, containerd, runc, CNI plugins) and the base-kernel options it and Cilium need.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-09-29"
---
# kubeadm worker sysext

## When to Use

- Joining a Bluefin Server node to an existing kubeadm cluster as a worker.
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
| `/usr/share/bluefin/containerd/config.toml`, `/usr/share/bluefin/kubeadm/crictl.yaml` | defaults copied to `/etc` if absent |

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

- No preset enables anything; `80-kubeadm.preset` disables both units against
  FSDK's implicit default. Ignition enables the sysext, `containerd.service`
  and `kubelet.service` per node, and runs `kubeadm join`.
- `systemd-sysext.service` is not ordered against tmpfiles, modules-load or
  sysctl, so `containerd.service` re-applies them in `ExecStartPre`:
  `systemd-tmpfiles --create kubeadm.conf` (seeds a writable
  `/etc/containerd/config.toml` and `/etc/crictl.yaml` only when absent),
  `modprobe overlay br_netfilter`, then `systemd-sysctl 90-kubeadm.conf`
  (`ip_forward`, `bridge-nf-call-ip{,6}tables`). kubeadm needs containerd
  running, so these hold before any preflight.
- containerd root is `/var/lib/containerd` (`RequiresMountsFor=` orders it after
  a per-node mount), `SystemdCgroup = true`, sandbox `registry.k8s.io/pause:3.10.1`,
  registry `config_path = /etc/containerd/certs.d`.
- kubelet restarts every 10 s until `kubeadm join` writes
  `/var/lib/kubelet/config.yaml` (standard kubeadm behaviour);
  `--volume-plugin-dir=/var/lib/kubelet/volumeplugins` because `/usr` is read-only.
- `/etc/resolv.conf` links to systemd-resolved's `/run/systemd/resolve/resolv.conf`
  (base image), the path kubelet's `resolvConf` expects.
- While `kubelet.service` runs or restarts, the base image's automatic reboot
  and the boot-deadline rollback reboot stand down and reboots belong to kured
  (the deadline flags `/run/reboot-required`); see "Updates" in
  [ddi-installer.md](ddi-installer.md).

## Host tools

kubeadm v1.34 preflight requires only `losetup`, `mount` and `cp` in `PATH`
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

`just export-image`, then boot diskless with `DOGFOOD_EXTRA_PROBE` activating
`kubeadm_<ver>.raw` (copy to `/run/extensions`, `systemd-sysext refresh`) and
check `crictl info`, `kubeadm init phase preflight`.
