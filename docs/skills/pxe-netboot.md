---
name: pxe-netboot
description: PXE/netboot installation using standalone Bluefin Server boot artifacts
---
# PXE/netboot installation

PXE installation is an opt-in variant of the normal offline installer. Releases
publish a kernel (`bluefin-server-pxe-vmlinuz-<version>`) and cpio initrd
(`bluefin-server-pxe-initrd-<version>.cpio.gz`) alongside the installer, DDI,
and signed `SHA256SUMS` manifest.

The PXE loader supplies `inst.ddi_url=https://.../bluefin-server-ddi-<version>.raw.zst`.
Use `inst.ddi_sha256=<sha256-of-compressed-ddi>` to verify the download before
the target disk is touched. `inst.target_disk=/dev/...` can select a specific
disk; without it, unattended mode selects the first writable disk that is not
installer media.

Example iPXE stanza:

```text
#!ipxe
set base https://mirror.example/bluefin
kernel ${base}/bluefin-server-pxe-vmlinuz-<version> systemd.unit=system-install.target console=tty0 console=ttyS0,115200 rw unattended inst.ddi_url=${base}/bluefin-server-ddi-<version>.raw.zst inst.ddi_sha256=<sha256>
initrd ${base}/bluefin-server-pxe-initrd-<version>.cpio.gz
boot
```

The initrd downloads and decompresses the DDI into `/run/installer`, so allow
RAM or writable runtime storage for the expanded DDI. HTTPS requires the
installer CA bundle. DHCP is enabled on Ethernet interfaces; provide a serial
console with `console=ttyS0,115200` when diagnosing DHCP or fetch failures.

Without `inst.ddi_url`, behavior is unchanged: the installer reads the embedded
DDI from `bluefin-installer-data` and needs no network.
