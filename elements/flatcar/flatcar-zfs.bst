kind: manual
description: |
  Import and extract the Flatcar ZFS system extension (sysext).
  Provides spl.ko and zfs.ko modules matching the Flatcar LTS kernel,
  along with upstream zpool, zfs userspace tools, systemd services, and udev rules.

(@):
  - include/arch.yml
  - include/flatcar.yml

build-depends:
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/squashfs-tools.bst

variables:
  strip-binaries: ""

sources:
  - kind: remote
    url: flatcar:stable/%{flatcar-board}/%{flatcar-version}/flatcar-zfs.raw
    ref: bed24d0a31b6c9ff0f1d59ec2b50d25585bf9bbcb8e9e96f5706f1a17948d971

config:
  install-commands:
    - |
      set -euo pipefail

      # Extract the SquashFS sysext directly into the element install root
      unsquashfs -no-xattrs -f -d "%{install-root}" flatcar-zfs.raw

      # Also preserve the raw sysext image under /usr/lib/sysexts for runtime sysext usage
      mkdir -p "%{install-root}/usr/lib/sysexts"
      install -D -m 0644 flatcar-zfs.raw "%{install-root}/usr/lib/sysexts/zfs.raw"
