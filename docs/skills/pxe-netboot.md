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
set base https://mirror.example/bluefin
kernel ${base}/bluefin-server-pxe-vmlinuz-<version> systemd.unit=system-install.target console=tty0 console=ttyS0,115200 rw unattended inst.ddi_url=${base}/bluefin-server-ddi-<version>.raw.zst inst.ddi_sha256=<sha256> inst.target_disk=/dev/sda
initrd ${base}/bluefin-server-pxe-initrd-<version>.cpio.gz
boot
```

`inst.ddi_url` must use HTTP(S) and requires `inst.ddi_sha256`, the
64-character SHA-256 digest of the compressed DDI. The initrd verifies the
download before unpacking or invoking the installer. `inst.target_disk` selects
a writable whole-disk block device; without it, unattended mode selects the
first suitable disk not containing embedded installer media.

Fetch, checksum, decompression, and target-disk validation failures stop
installation before the target disk is modified. Mirror release assets and
verify them against the signed `SHA256SUMS` manifest. DHCP is enabled on
Ethernet interfaces; provide serial console arguments above for diagnostics.

Without `inst.ddi_url`, behavior is unchanged: the installer reads the embedded
DDI from `bluefin-installer-data` and needs no network.
