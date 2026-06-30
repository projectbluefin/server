kind: stack
description: |
  Live installer environment stack. Provides systemd (with systemd-repart,
  systemd-firstboot, bootctl, systemd-sysupdate), cryptsetup, dracut, and the
  server kernel. NOT distroless — the installer needs tools and a shell.

  The installer uses systemd-sysupdate to pull the OS DDI from GitHub Releases
  over the network, then systemd-repart applies it to the target disk.

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

  # systemd full (includes systemd-repart, systemd-firstboot, bootctl,
  # and systemd-sysupdate for network DDI pull)
  - freedesktop-sdk.bst:components/systemd.bst
  - freedesktop-sdk.bst:components/kmod.bst
  - freedesktop-sdk.bst:components/shadow.bst

  # Disk setup: LUKS partition support during install
  - freedesktop-sdk.bst:components/cryptsetup.bst

  # initrd generator — dracut wires repart + sysupdate into the live initrd
  - freedesktop-sdk.bst:components/dracut.bst

  # Kernel (installer boots from this)
  - bluefin-server/kernel-server.bst

  # repart.d configs describing the TARGET disk layout
  - installer/installer-repart.bst

  # sysupdate.d transfer config for pulling the OS DDI from GitHub Releases
  - installer/installer-sysupdate.bst

