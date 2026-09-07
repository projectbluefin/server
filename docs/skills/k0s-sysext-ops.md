---
name: k0s-sysext-ops
description: Operator runbook for the k0s systemd-sysext extension — provisioning, runtime testing, and troubleshooting.
metadata:
  type: how-to
  status: stable
  last_updated: 2026-09-06
  context7-sources:
    - /systemd/systemd
---
# k0s systemd-sysext Operations

Use this skill when running, testing, or debugging the k0s systemd-sysext on a live Bluefin Server host.

## Enabling k0s on a Host

On a running Bluefin Server system:

```bash
just k8s
```

Or manually:

```bash
# 1. Fetch extension image if not already present
systemd-sysupdate update

# 2. Merge extension into /usr
systemctl enable --now systemd-sysext.service
systemd-sysext merge

# 3. Seed declarative manifest stacks into /var/lib/k0s/manifests/
systemd-tmpfiles --create /usr/lib/tmpfiles.d/k0s-manifests.conf

# 4. Start the controller service
systemctl enable --now k0scontroller.service
```

## Verifying Manifest Reconciliation

k0s automatically applies all `.yaml` files under `/var/lib/k0s/manifests/argocd/` and `/var/lib/k0s/manifests/kubestellar/`.

```bash
# Verify pods in argocd and kubestellar namespaces
k0s kubectl get pods -A
```

## Troubleshooting

- **Extension not merged**: Check `systemd-sysext status`. Verify `/var/lib/extensions/k0s.raw` exists.
- **Manifests not applied**: Check `/var/lib/k0s/manifests/`. Ensure files end in `.yaml` (not `.yml`).
- **Service failed**: Check `journalctl -u k0scontroller -e`.

## See also

- [k0s-sysext.md](k0s-sysext.md)
- `systemd-sysext(8)`
