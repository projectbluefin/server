---
name: pxe-netboot
description: Use when provisioning Bluefin Server over PXE or iPXE.
metadata:
  type: reference
  status: stable
---
# PXE/netboot installer

Releases include standalone `bluefin-server-pxe-vmlinuz-<version>` and
`bluefin-server-pxe-initrd-<version>.cpio.gz` assets. The matching DDI
(`bluefin-server-ddi-<version>.raw.zst`) is fetched only when `inst.ddi_url`
is supplied; normal installer media remains offline and uses its embedded DDI.

Example iPXE configuration:

```ipxe
#!ipxe
set base http://pxe.example/data
kernel ${base}/bluefin-server-pxe-vmlinuz-<version> systemd.unit=system-install.target console=tty0 console=ttyS0,115200 rw unattended inst.ddi_url=${base}/bluefin-server-ddi-<version>.raw.zst inst.ddi_sha256=<sha256> inst.target_disk=/dev/sda
initrd ${base}/bluefin-server-pxe-initrd-<version>.cpio.gz
boot
```

`inst.ddi_url` must use HTTP(S). The compressed DDI is unpacked into the
installer runtime; `inst.ddi_sha256` is recommended and is checked before
installation. `inst.target_disk` selects a whole-disk block device. Without
it, unattended mode selects the first writable disk, as with USB media.

Fetch or checksum failures stop installation before the target disk is
modified. Mirror release assets and verify them against the signed
`SHA256SUMS` manifest. Provide DHCP and DNS (or a reachable IP URL), and use
the serial console arguments above for headless systems.
