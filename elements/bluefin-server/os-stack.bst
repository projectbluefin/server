kind: stack
description: Stack containing all elements required to build a pure DDI Bluefin Server rootfs.

depends:
  # Flatcar LTS userspace base.
  #
  # The OS payload now lands on a single-ABI Flatcar `/usr` (flatcar-usr.bst)
  # that shares the vermagic, glibc, and systemd of the Flatcar LTS kernel
  # below. This is the cutover from FSDK 26.08 base userspace (projectbluefin/
  # server#131, design phase 5). Every FSDK base-runtime component that used to
  # live here (systemd, dbus, bash, coreutils, shadow, kmod, openssh-systemd,
  # podman, xfsprogs, gnupg, ca-certificates, tzdata, runtime-minimal, and the
  # uutils-coreutils overlay) is gone — Flatcar's `/usr` provides them. The
  # installer keeps its own FSDK userspace; see installer/installer-stack.bst.
  - flatcar/flatcar-usr.bst

  # FSDK junction is still pulled in for OS-level integration helpers only
  # (fstab entries, ldconfig cache); the base runtime it used to provide is
  # now Flatcar's.
  - freedesktop-sdk.bst:integration/extra-fs.bst
  - freedesktop-sdk.bst:integration/ldconfig.bst

  # SSH enablement drop-ins (OS policy, shipped by the installed OS)
  - bluefin-server/os-sshd-preset.bst
  - bluefin-server/os-sshd-config.bst

  # Image identity and weekly first-party countme reporting
  - bluefin-server/os-image-info.bst
  - bluefin-server/os-countme.bst

  # Flatcar LTS Kernel & Matching ZFS
  - flatcar/flatcar-kernel.bst
  - flatcar/flatcar-zfs.bst

  # Sysext Compatibility Identity
  - bluefin-server/os-release-flatcar.bst

  # A/B System Update Configurations
  - bluefin-server/os-sysupdate.bst

  # k0s component system update configuration
  - bluefin-server/os-k0s-sysupdate.bst

  # Wired DHCP configuration for the installed OS
  - bluefin-server/os-networkd.bst

  # /etc/resolv.conf symlink to systemd-resolved (tmpfiles.d)
  - bluefin-server/os-resolv-conf.bst

  # Activate the optional k0s sysext after installation
  - bluefin-server/os-k0s-first-boot.bst

  # Public keyring for verifying SHA256SUMS manifests from GitHub Releases
  - bluefin-server/os-sysupdate-keys.bst

  # First-Boot Credentials Provisioning
  - bluefin-server/os-creds-prov.bst

  # Reboot Coordination for Kured
  - bluefin-server/os-kured-hook.bst

  # System Management Justfile
  - bluefin-server/os-justfile.bst

  # Console issue banner with KubeStellar dashboard URL
  - bluefin-server/os-issue.bst
