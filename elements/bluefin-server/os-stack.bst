kind: stack
description: Everything that goes into the Bluefin Server /usr image.

depends:
  # freedesktop-sdk userspace + signed FSDK kernel
  - bluefin-server/os-base.bst
  - bluefin-server/os-sd-boot-signed.bst
  - bluefin-server/os-repart.bst
  - bluefin-server/os-release.bst

  # SSH enablement drop-ins (OS policy, shipped by the installed OS)
  - bluefin-server/os-sshd-preset.bst
  - bluefin-server/os-sshd-config.bst

  # Image identity and weekly first-party countme reporting
  - bluefin-server/os-image-info.bst
  - bluefin-server/os-countme.bst

  # A/B System Update Configurations
  - bluefin-server/os-sysupdate.bst

  # Diskless update signal (bluefin-diskless-update-check) and the shared
  # boot-origin helper it uses
  - bluefin-server/os-update-check.bst
  - bluefin-server/boot-origin.bst

  # k0s component system update configuration
  - bluefin-server/os-k0s-sysupdate.bst

  # NVIDIA Container Toolkit component system update configuration
  - bluefin-server/os-nvidia-container-toolkit-sysupdate.bst



  # Wired DHCP configuration for the installed OS, with mDNS on
  - bluefin-server/os-networkd.bst
  - bluefin-server/os-resolved.bst

  # /etc/resolv.conf symlink to systemd-resolved (tmpfiles.d)
  - bluefin-server/os-resolv-conf.bst

  # k0s and NVIDIA Container Toolkit sysext activation units (opt-in) and
  # SSH host key generation
  - bluefin-server/os-k0s-first-boot.bst

  # Public keyring for verifying SHA256SUMS manifests from GitHub Releases
  - bluefin-server/os-sysupdate-keys.bst

  # First-Boot Credentials Provisioning
  - bluefin-server/os-creds-prov.bst

  # System Management Justfile
  - bluefin-server/os-justfile.bst

  # system-container helper (machinectl wrapper)
  - bluefin-server/os-system-container.bst

  # Console issue banner (the KubeStellar sysext adds its dashboard URL)
  - bluefin-server/os-issue.bst

  # udev rules (USB installer: other disks' stale partition devices, #359)
  - bluefin-server/os-udev-rules.bst
