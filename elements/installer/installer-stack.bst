kind: stack
description: |
  Live installer environment stack. Provides systemd (with systemd-repart,
  systemd-firstboot, bootctl), cryptsetup, and the server kernel.
  NOT distroless — the installer needs tools and a shell.

  No dracut: the initrd is assembled directly from this rootfs via cpio in
  bluefin-server-installer.bst. This keeps the toolchain minimal and removes
  the dracut dependency chain.

  The DDI payload is embedded in the installer media (offline install).
  No network access required at install time.

depends:
  # Base runtime
  - freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
  - freedesktop-sdk.bst:components/gawk.bst
  - freedesktop-sdk.bst:components/sed.bst
  - freedesktop-sdk.bst:components/grep.bst
  - freedesktop-sdk.bst:components/ca-certificates.bst
  - freedesktop-sdk.bst:components/tzdata.bst
  - freedesktop-sdk.bst:integration/extra-fs.bst
  - freedesktop-sdk.bst:integration/ldconfig.bst

  # systemd full (includes systemd-repart, systemd-firstboot, bootctl)
  - freedesktop-sdk.bst:components/systemd.bst
  - freedesktop-sdk.bst:components/kmod.bst
  - freedesktop-sdk.bst:components/shadow.bst

  # SSH access to live installer environment
  - freedesktop-sdk.bst:components/openssh.bst

  # Disk setup: LUKS partition support during install
  - freedesktop-sdk.bst:components/cryptsetup.bst
  - freedesktop-sdk.bst:components/xfsprogs.bst
  - freedesktop-sdk.bst:components/dosfstools.bst

  # Kernel (installer boots from this; vmlinuz used as the UKI --linux= arg)
  - freedesktop-sdk.bst:components/linux.bst

  # repart.d configs describing the TARGET disk layout
  - installer/installer-repart.bst

  # Installer systemd units (installer.target + installer.service)
  - installer/installer-units.bst

  # knuckle interactive TUI installer binary staged at /opt/knuckle
  - installer/installer-knuckle.bst
