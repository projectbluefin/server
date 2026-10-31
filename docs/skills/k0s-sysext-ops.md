---
name: k0s-sysext-ops
description: Operator runbook for the k0s systemd-sysext on Bluefin Server — provisioning, runtime testing, and troubleshooting.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-10-02"
  context7-sources:
    - /systemd/systemd
---
# k0s systemd-sysext Operations

Use this skill when running, testing, or debugging the k0s systemd-sysext
on a live Bluefin Server host.

## KubeStellar

The k0s sysext carries no Kubernetes add-ons. KubeStellar is a homelab
add-on applied by the homelab applier to a k0s or kubeadm control plane;
see [homelab-profile.md](homelab-profile.md), "Add-ons", including what
changed for nodes that used the former k0s KubeStellar appliance.

## Enabling k0s on a host

`k0s-first-boot.service` is **not enabled by default**; the preset
`80-bluefin-opt-in.preset` disables it and its fetcher. To opt in:

```bash
# 1. Place the k0s sysext image at /var/lib/k0s/k0s.raw, or let the fetcher
#    pull it from the release track:
systemd-sysupdate --component=k0s update

# 2. Enable the one-shot activation unit
systemctl enable --now k0s-first-boot.service
```

The unit copies `/var/lib/k0s/k0s.raw` to `/run/extensions/k0s.raw`, runs
`systemd-sysext refresh`, and then enables either `k0scontroller.service` or
`k0sworker.service` depending on whether `/etc/k0s/token` exists.

While either k0s unit runs, the base image's automatic reboot stands down,
and so does the boot-deadline rollback reboot, which flags
`/run/reboot-required` instead; deploy kured to roll staged OS updates (and
rollbacks) across the cluster (see "Updates" in
[updates-operations.md](updates-operations.md)).

### Worker nodes

A node with a join token at `/etc/k0s/token` becomes a worker. The token can be
written by Booty via Ignition at provisioning time; `k0sworker.service` will
start automatically on the next boot when the token is present.

## Verifying

```bash
# Check merged extensions
systemd-sysext status

# Check k0s role
systemctl status k0scontroller.service   # controller node
systemctl status k0sworker.service       # worker node

# Check pods
k0s kubectl get pods -A
```

## Verified QEMU behavior

Opt-in activation in QEMU reaches:

- `k0scontroller.service` active

Placing a token at `/etc/k0s/token` switches the node to `k0sworker.service`.

## Troubleshooting

- **Extension not merged**: Check `systemd-sysext status`. For k0s, verify the
  persistent image is `/var/lib/k0s/k0s.raw`; `k0s-first-boot.service` copies it
  into `/run/extensions/k0s.raw`.
- **Service failed**: Check `journalctl -u k0scontroller -e` or
  `journalctl -u k0sworker -e`.

## See also

- [k0s-sysext.md](k0s-sysext.md)
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary (Sysext definition).
- `systemd-sysext(8)`
