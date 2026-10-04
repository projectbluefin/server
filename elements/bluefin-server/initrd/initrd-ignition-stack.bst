kind: stack
description: |
  Ignition in the initrd: the binary, its units, and the tools it executes.
  Helper names are the defaults in Ignition v2.27.0 internal/distro/distro.go,
  resolved through $PATH.

    fetch*  (no helpers; HTTPS trust from ca-certificates in initrd-stack.bst)
    disks   sgdisk, partx, wipefs, udevadm, mkfs.xfs, mkfs.ext4, mkfs.fat,
            mkswap; cryptsetup for LUKS (clevis, mdadm, mkfs.btrfs absent)
    mount   mount, umount
    files   useradd, usermod, userdel, groupadd, groupmod, groupdel
            (--root=/sysroot), systemctl --root (unit disable; list-unit-files
            and preset in bluefin-ignition-presets)
    all     modprobe (platform providers), bash (credential helper)

depends:
- ignition/ignition.bst
- ignition/gptfdisk.bst
- bluefin-server/initrd/initrd-ignition.bst
# bluefin-boot-origin: the HTTP boot origin, for bluefin-node.ign next to the UKI
- bluefin-server/boot-origin.bst

# bash, coreutils
- freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
# udevadm, systemctl, systemd-udevd
- freedesktop-sdk.bst:components/systemd.bst
# modprobe
- freedesktop-sdk.bst:components/kmod.bst
# mount, umount, partx, wipefs, mkswap
- freedesktop-sdk.bst:components/util-linux-full.bst
# blkid, lsblk (debugging disks-stage failures from the emergency shell)
- freedesktop-sdk.bst:components/util-linux.bst
# useradd, usermod, userdel, groupadd, groupmod, groupdel
- freedesktop-sdk.bst:components/shadow.bst
# mkfs.xfs
- freedesktop-sdk.bst:components/xfsprogs.bst
# mkfs.ext4
- freedesktop-sdk.bst:components/e2fsprogs.bst
# mkfs.fat
- freedesktop-sdk.bst:components/dosfstools.bst
# cryptsetup (luks)
- freedesktop-sdk.bst:components/cryptsetup.bst
