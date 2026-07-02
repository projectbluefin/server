kind: stack
description: Stack containing all elements required to build a pure DDI Bluefin Server rootfs.

depends:
  # Base runtime & core libraries
  - freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
  - freedesktop-sdk.bst:components/ca-certificates.bst
  - freedesktop-sdk.bst:components/tzdata.bst
  - freedesktop-sdk.bst:integration/extra-fs.bst
  - freedesktop-sdk.bst:integration/ldconfig.bst

  # System Initialization, Core, and Device Management
  - freedesktop-sdk.bst:components/systemd.bst
  - freedesktop-sdk.bst:components/kmod.bst
  - freedesktop-sdk.bst:components/shadow.bst

  # Stock FSDK Kernel & Server-Chiseled Firmware
  - freedesktop-sdk.bst:components/linux.bst
  - bluefin-server/linux-firmware-split.bst

  # Filesystem resizing support for growing root/var on first boot
  - freedesktop-sdk.bst:components/xfsprogs.bst

  # Sysext Compatibility Identity
  - bluefin-server/os-release-flatcar.bst
