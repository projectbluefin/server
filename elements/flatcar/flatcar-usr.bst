kind: manual
description: |
  Import the Flatcar LTS /usr as the Bluefin Server OS payload base.
  Extracts ./usr from upstream Flatcar container rootfs, strips Flatcar's
  update and provisioning stack in favor of native Bluefin equivalents
  (systemd-sysupdate, systemd-creds, Kured), and removes /usr/lib/modules
  to leave kernel module management exclusively to flatcar-kernel.bst.

(@):
  - include/arch.yml
  - include/flatcar.yml

build-depends:
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/tar.bst
  - freedesktop-sdk.bst:components/gzip.bst
  - freedesktop-sdk.bst:components/findutils.bst

variables:
  strip-binaries: ""

sources:
  - kind: remote
    url: flatcar:stable/%{flatcar-board}/%{flatcar-version}/flatcar-container.tar.gz
    ref: c533ff576e128d11ce240e01f818c358d75b9ff118b2dd9199fbf4684547a32c

config:
  install-commands:
    - |
      set -euo pipefail

      mkdir -p "%{install-root}"

      # Extract the complete Flatcar /usr into the element install root.
      tar -xzf flatcar-container.tar.gz -C "%{install-root}" ./usr

      # Remove kernel modules; elements/flatcar/flatcar-kernel.bst extracts and owns
      # /usr/lib/modules/%{flatcar-kver} (uncompressing .ko.xz modules and running depmod)
      # to prevent filesystem overlap collisions when composed together in os-stack.bst.
      rm -rf "%{install-root}/usr/lib/modules"

      # Remove Flatcar's update and provisioning stack with explicit rm lines.
      # Each removal names its Bluefin replacement. No wildcard sweeps are used
      # so that an upstream unit rename fails loudly instead of silently regressing.
      # Note: /usr/lib/flatcar/bootengine.img is deliberately preserved here;
      # stage 1 initramfs loop-mounts it from /usr as the stage 2 initramfs.

      # update_engine: replaced by Bluefin's systemd-sysupdate (os-sysupdate.bst) for A/B image updates
      rm "%{install-root}/usr/bin/update_engine"
      rm "%{install-root}/usr/lib/systemd/system/update-engine.service"
      rm "%{install-root}/usr/lib/systemd/system/multi-user.target.wants/update-engine.service"
      rm "%{install-root}/usr/lib/tmpfiles.d/update-engine.conf"

      # update_engine_client: replaced by Bluefin's systemd-sysupdate CLI and systemctl
      rm "%{install-root}/usr/bin/update_engine_client"

      # update_engine_stub: replaced by Bluefin's native systemd-sysupdate mechanism
      rm "%{install-root}/usr/bin/update_engine_stub"
      rm "%{install-root}/usr/lib/systemd/system/update-engine-stub.service"
      rm "%{install-root}/usr/lib/systemd/system/update-engine-stub.timer"
      rm "%{install-root}/usr/lib/systemd/system/multi-user.target.wants/update-engine-stub.timer"

      # locksmithd: replaced by Bluefin's Kured reboot coordination (os-kured-hook.bst) via /run/reboot-required
      rm "%{install-root}/usr/lib/locksmith/locksmithd"
      rm "%{install-root}/usr/bin/locksmithctl"

      # locksmithd.service: replaced by Bluefin's Kured reboot coordination (os-kured-hook.bst)
      rm "%{install-root}/usr/lib/systemd/system/locksmithd.service"
      rm "%{install-root}/usr/lib/systemd/system/multi-user.target.wants/locksmithd.service"

      # ignition: replaced by Bluefin's systemd-creds first-boot credential provisioning (os-creds-prov.bst)
      rm "%{install-root}/usr/bin/ignition"
      rm "%{install-root}/usr/libexec/ignition-rmcfg"

      # ignition-delete-config.service: replaced by Bluefin's systemd-creds credential provisioning
      rm "%{install-root}/usr/lib/systemd/system/ignition-delete-config.service"
      rm "%{install-root}/usr/lib/systemd/system/sysinit.target.wants/ignition-delete-config.service"

      # coreos-cloudinit: replaced by Bluefin's systemd-creds first-boot credential provisioning (os-creds-prov.bst)
      rm "%{install-root}/usr/bin/coreos-cloudinit"
      rm "%{install-root}/usr/lib/systemd/system/enable-oem-cloudinit.service"
      rm "%{install-root}/usr/lib/systemd/system/multi-user.target.wants/enable-oem-cloudinit.service"
      rm "%{install-root}/usr/lib/systemd/system/oem-cloudinit.service"

      # flatcar-update: replaced by Bluefin's systemd-sysupdate (os-sysupdate.bst) and os-justfile
      rm "%{install-root}/usr/bin/flatcar-update"
      rm "%{install-root}/usr/lib/tmpfiles.d/flatcar-update.conf"

      # download_sysext: replaced by Bluefin's declarative sysext delivery via systemd-sysext
      rm "%{install-root}/usr/bin/download_sysext"

      # ensure-sysext.service: replaced by Bluefin's systemd-sysext.service and sysupdate integration
      rm "%{install-root}/usr/lib/systemd/system/ensure-sysext.service"
      rm "%{install-root}/usr/lib/systemd/system/sysinit.target.wants/ensure-sysext.service"
