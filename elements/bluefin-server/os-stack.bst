kind: stack
description: Stack containing all elements required to build a pure DDI Bluefin Server rootfs.

depends:
  # Base runtime & core libraries (minimal non-GNU base + uutils modern userspace)
  - freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
  - bluefin-server/uutils-coreutils.bst
  - freedesktop-sdk.bst:bootstrap/bash.bst
  - freedesktop-sdk.bst:components/ca-certificates.bst
  - freedesktop-sdk.bst:components/tzdata.bst
  - freedesktop-sdk.bst:integration/extra-fs.bst
  - freedesktop-sdk.bst:integration/ldconfig.bst

  # System Initialization, Core, and Device Management
  - freedesktop-sdk.bst:components/systemd.bst
  - freedesktop-sdk.bst:components/dbus.bst
  - freedesktop-sdk.bst:components/dbus-broker.bst
  - freedesktop-sdk.bst:components/kmod.bst
  - freedesktop-sdk.bst:components/shadow.bst

  # Remote access during bring-up (temporary — see docs/skills/factory-integration.md)
  - freedesktop-sdk.bst:components/openssh-systemd.bst

  # SSH enablement drop-ins
  - bluefin-server/os-sshd-preset.bst
  - bluefin-server/os-sshd-config.bst

  # Image identity and weekly first-party countme reporting
  - bluefin-server/os-image-info.bst
  - bluefin-server/os-countme.bst

  # Flatcar LTS Kernel & Matching ZFS
  - flatcar/flatcar-kernel.bst
  - flatcar/flatcar-zfs.bst
  - bluefin-server/linux-firmware-split.bst

  # Filesystem resizing support for growing root/var on first boot
  - freedesktop-sdk.bst:components/xfsprogs.bst

  # Sysext Compatibility Identity
  - bluefin-server/os-release-flatcar.bst

  # A/B System Update Configurations
  - bluefin-server/os-sysupdate.bst

  # k0s component system update configuration
  - bluefin-server/os-k0s-sysupdate.bst

  # Wired DHCP configuration for the installed OS
  - bluefin-server/os-networkd.bst

  # Activate the optional k0s sysext after installation
  - bluefin-server/os-k0s-first-boot.bst

  # Public keyring for verifying SHA256SUMS manifests from GitHub Releases
  - bluefin-server/os-sysupdate-keys.bst

  # gpg binary required by systemd-sysupdate to verify SHA256SUMS.gpg
  - freedesktop-sdk.bst:components/gnupg.bst

  # First-Boot Credentials Provisioning
  - bluefin-server/os-creds-prov.bst

  # Reboot Coordination for Kured
  - bluefin-server/os-kured-hook.bst

  # Container Runtime support
  - freedesktop-sdk.bst:components/podman.bst

  # System Management Justfile
  - bluefin-server/os-justfile.bst

  # Console issue banner with KubeStellar dashboard URL
  - bluefin-server/os-issue.bst
