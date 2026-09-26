kind: manual
description: |
  Import the Flatcar LTS /usr as the Bluefin Server OS payload base.
  Extracts ./usr from upstream Flatcar container rootfs, strips Flatcar's
  update and provisioning stack in favor of native Bluefin equivalents
  (systemd-sysupdate, systemd-creds, Kured), and removes /usr/lib/modules
  to leave kernel module management exclusively to flatcar-kernel.bst.

  BuildStream artifacts record a single executable bit per file (REAPI
  FileNode.is_executable), so the setuid/setgid bits Flatcar ships on sudo,
  su, passwd, mount and friends are dropped when this install root is
  captured. The element records them in usr/lib/bluefin-server/setuid-modes
  while the archive modes are still intact (after its own removals, so the
  list only names files that ship); oci/bluefin-server-ddi.bst restores
  them before mkfs.xfs and verifies the written image with xfs_db.

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
    ref: "%{flatcar-kernel-container-sha256}"

config:
  install-commands:
    - |
      set -euo pipefail

      mkdir -p "%{install-root}"

      # Extract the complete Flatcar /usr into the element install root.
      tar --no-same-owner -xzf flatcar-container.tar.gz -C "%{install-root}" ./usr

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

      # oem.mount: replaced by Bluefin's standard GPT partition layout (no OEM partition)
      rm "%{install-root}/usr/lib/systemd/system/oem.mount"
      rm "%{install-root}/usr/lib/systemd/system/local-fs.target.wants/oem.mount"
      rm "%{install-root}/usr/lib/systemd/system/dev-disk-by\\x2dlabel-OEM.device"
      rm -r "%{install-root}/usr/lib/systemd/system/systemd-fsck@dev-disk-by\\x2dlabel-OEM.service.d"

      # Record every setuid/setgid file (octal mode, path relative to the
      # install root) before the artifact capture flattens the modes to 0755.
      # This runs after the removals above so the list never names a file this
      # element deletes (a stale entry would fail the DDI restore). Paths must
      # not contain leading/trailing whitespace or newlines (`read` would
      # mangle them); Flatcar ships none such. Fail loudly if the list is
      # empty or misses sudo: that means the archive was extracted without its
      # special bits and the image would ship an unusable sudo/su/passwd.
      mkdir -p "%{install-root}/usr/lib/bluefin-server"
      find "%{install-root}/usr" -type f -perm /6000 -printf '%m usr/%P\n' \
        | LC_ALL=C sort > "%{install-root}/usr/lib/bluefin-server/setuid-modes"
      SETUID_SUDO_SEEN=0
      while read -r mode path; do
        case "${mode}" in [2-7][0-7][0-7][0-7]) ;; *) echo "ERROR: unexpected mode '${mode}' for ${path} in setuid-modes" >&2; exit 1 ;; esac
        if [ "${path}" = usr/bin/sudo ]; then
          SETUID_SUDO_SEEN=1
        fi
      done < "%{install-root}/usr/lib/bluefin-server/setuid-modes"
      if [ "${SETUID_SUDO_SEEN}" -ne 1 ]; then
        echo "ERROR: usr/bin/sudo is not setuid in the extracted Flatcar /usr; refusing to record an empty setuid-modes list" >&2
        exit 1
      fi
