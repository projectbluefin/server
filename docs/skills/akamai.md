---
name: akamai
description: Running Bluefin Server on Akamai Cloud (Linode). Load when deploying to Linode, debugging Ignition from the Metadata service, or asking why Akamai nodes are diskless.
metadata:
  type: reference
  status: stable
  last_updated: "2026-11-25"
---
# Akamai Cloud (Linode)

## What works and why

Linode instances boot legacy BIOS (no `/sys/firmware/efi`; `direct-disk` boots
the disk's MBR), so the UEFI paths do not apply: no installed disk UKI, no
`systemd-sysupdate` A/B, no boot counting. The supported shape is the diskless
BIOS path described in [booty-integration.md](booty-integration.md): a BIOS
bootloader (iPXE, or the syslinux boot disk the Akamai tooling builds) boots the netboot UKI's kernel and initrd sections with the UKI's own
`.cmdline` (`rd.systemd.pull` pointing at the release), and the initrd pulls
the signed OS DDI into RAM, so size the instance as in
[diskless-troubleshooting.md](diskless-troubleshooting.md). Keep state on a
second disk (`/var`, provisioned by Ignition). The console is `ttyS0` (Lish);
a virtual UART ignores the baud rate, so the sealed `115200` works.

The initrd ships `/etc/resolv.conf` as a symlink to the resolved stub
(`files/initrd/etc/resolv.conf`, covered by `tests/unit/test_initrd_resolv.py`).
Without it nothing resolves a hostname in the initrd, so only IP-literal pull
URLs worked; the `tmpfiles.d` rules for it are not applied there.

Deployment tooling (OpenTofu, the iPXE boot disk, e2e) lives outside this
repo: [idvoretskyi/bluefin-server-on-akamai](https://github.com/idvoretskyi/bluefin-server-on-akamai).

## Ignition from the Metadata service

`bluefin-ignition-credentials` stages the instance's user data when no
`ignition.config` / `ignition.config.url` credential is set and
`/sys/class/dmi/id/sys_vendor` is `Linode`:

1. `PUT http://169.254.169.254/v1/token` (`Metadata-Token-Expiry-Seconds`).
2. `GET /v1/user-data` with `Metadata-Token`. The body is the base64 the
   deployer supplied (`metadata.user_data`); it is decoded and staged as
   `/run/ignition/user.ign`.

The Metadata service is a per-instance link-local channel, so the config is
trusted unsigned, like an `ignition.config` credential. HTTP 404 (no user
data) falls through to the `bluefin-node.ign` lookup. A failing token request,
any other status, or user data that is not base64 fails the boot instead of
bringing the node up unconfigured. The instance's image must carry the
`cloud-init` capability and the region must offer Metadata. Ignition accepts
Ignition JSON or Butane YAML, not `#cloud-config`.

Covered by `tests/unit/test_ignition_credentials.py` against a fake Metadata
service; the tests never read the host's DMI, since a CI runner can itself be
a Linode.
