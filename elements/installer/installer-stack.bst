kind: stack
description: |
  Live installer environment stack. Provides systemd (with systemd-repart,
  systemd-firstboot, bootctl), cryptsetup, erofs-utils, dracut, and the
  server kernel. NOT distroless — the installer needs tools and a shell.

  NOTE: This is the build-time staging stack. The UKI (installer.efi) is
  generated separately from this; see elements/oci/bluefin-server-installer.bst
  for the TODO on UKI/initrd generation.

depends:
  # Base runtime
  - freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
  - freedesktop-sdk.bst:components/ca-certificates.bst
  - freedesktop-sdk.bst:components/tzdata.bst
  - freedesktop-sdk.bst:integration/extra-fs.bst
  - freedesktop-sdk.bst:integration/ldconfig.bst

  # systemd full (includes systemd-repart, systemd-firstboot, bootctl)
  # gnome-build-meta's systemd is used via the junction override in
  # elements/freedesktop-sdk.bst — no special reference needed here.
  - freedesktop-sdk.bst:components/systemd.bst
  - freedesktop-sdk.bst:components/kmod.bst
  - freedesktop-sdk.bst:components/shadow.bst

  # Disk setup tools
  - freedesktop-sdk.bst:components/cryptsetup.bst  # LUKS partition support
  - freedesktop-sdk.bst:components/erofs-utils.bst  # mkfs.erofs for DDI payload

  # initrd generator — dracut wires repart + firstboot into the live initrd
  - freedesktop-sdk.bst:components/dracut.bst

  # Kernel (installer boots from this)
  - bluefin-server/kernel-server.bst

  # repart.d configs describing the TARGET disk layout
  - installer/installer-repart.bst
