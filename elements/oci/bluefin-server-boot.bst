kind: script
description: |
  Signed UKIs for Bluefin Server (FSDK kernel + systemd-native initrd).

  Outputs:
    bluefin-server-netboot_<ver>.efi  diskless: pulls bluefin-server_<ver>.raw into RAM
                                      (UEFI HTTP boot origin, or the import.pull
                                      credential), dm-verity /usr, tmpfs root
    bluefin-server-<ver>.efi          installed: A/B usr slot found by partition label,
                                      persistent root found by gpt-auto
    bluefin-server-installer_<ver>.efi
                                      USB installer: usr from the installer medium's
                                      bluefin-installer-* partitions, tmpfs root,
                                      boots into system-install.target (systemd-sysinstall)
    efi-keys/{PK,KEK,db}.auth         Secure Boot enrollment payloads
    repart.d/                         disk layout: ESP, usr A/B + verity, root.
                                      Slot A is copied from the running image
                                      (CopyBlocks=auto) with the UUIDs dm-verity
                                      derives from usrhash, for
                                      systemd-sysinstall --definitions=

  All three pin usrhash= of the same /usr image and are signed with DB, so
  Secure Boot locks their command lines.

(@):
- include/arch.yml
- include/image.yml

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- freedesktop-sdk.bst:components/cpio.bst
- freedesktop-sdk.bst:components/findutils.bst
- freedesktop-sdk.bst:components/kmod.bst
- freedesktop-sdk.bst:components/sed.bst
- freedesktop-sdk.bst:components/systemd.bst
- freedesktop-sdk.bst:components/systemd-ukify.bst
- freedesktop-sdk.bst:components/zstd.bst
- freedesktop-sdk.bst:components/_private/sbsigntools.bst
- bluefin-server/keys/boot-keys.bst
- filename: bluefin-server/keys/efi-keys.bst
  config:
    location: /efi-keys
- filename: bluefin-server/initrd/initrd-filesystem.bst
  config:
    location: /initrd
- filename: bluefin-server/kernel-modules.bst
  config:
    location: /kmods
- filename: bluefin-server/os-release.bst
  config:
    location: /osrel
- filename: oci/bluefin-server-usr.bst
  config:
    location: /usr-image
- filename: bluefin-server/os-repart.bst
  config:
    location: /repart

variables:
  image-name: bluefin-server_%{image-version}
  initrd-modules: >-
    virtio_net virtio_blk virtio_pci virtio_scsi virtio_rng
    e1000 e1000e igb igc ixgbe i40e ice r8169 tg3 bnxt_en atlantic
    mlx4_en mlx5_core r8152 cdc_ether ax88179_178a usbnet
    xhci_pci ehci_pci nvme ahci sd_mod
    loop dm_mod dm_verity erofs overlay xfs
    tpm_crb tpm_tis efivarfs vfat nls_cp437 nls_iso8859_1
  common-cmdline: >-
    mount.usr=/dev/mapper/usr mount.usrfstype=erofs mount.usrflags=ro
    lockdown=integrity
  netboot-cmdline: >-
    root=tmpfs
    rd.systemd.pull=raw,machine,verify=signature,blockdev,bootorigin:rootdisk:%{image-name}.raw
    systemd.verity_usr_data=/dev/disk/by-loop-ref/rootdisk.raw-part1
    systemd.verity_usr_hash=/dev/disk/by-loop-ref/rootdisk.raw-part2
    systemd.default_device_timeout_sec=300
    rd.systemd.mask=systemd-repart.service systemd.mask=systemd-repart.service
    systemd.mask=boot.automount systemd.mask=boot.mount
    console=tty0 console=ttyS0,115200
  disk-cmdline: >-
    rw
    rd.systemd.mask=systemd-networkd-wait-online.service
    console=tty0 console=ttyS0,115200
  # The installer medium opens its own usr/verity by partition label, not by
  # the usrhash-derived UUIDs: those belong to installed usr slots, so an
  # existing install (or the disk being installed) is never picked up as the
  # installer's /usr. The installer is offline: the initrd must not wait for
  # network-online (no limit; netboot needs it, the installer never does).
  # tty0 comes last so /dev/console, where systemd-sysinstall.service draws
  # its interface, is the monitor. firstboot.keymap is a well-known
  # systemd-firstboot credential: with it set, firstboot does not ask for a
  # keymap (a list of 100+ layouts), and sysinstall copies it to the target.
  installer-cmdline: >-
    root=tmpfs
    systemd.verity_usr_data=/dev/disk/by-partlabel/bluefin-installer-usr
    systemd.verity_usr_hash=/dev/disk/by-partlabel/bluefin-installer-usr-verity
    rd.systemd.mask=systemd-repart.service systemd.mask=systemd-repart.service
    rd.systemd.mask=systemd-networkd-wait-online.service
    systemd.mask=boot.automount systemd.mask=boot.mount
    systemd.unit=system-install.target
    systemd.setenv=BLUEFIN_INSTALL_KERNEL=/run/bluefin/installer/bluefin/bluefin-server-%{image-version}.efi
    systemd.set_credential=firstboot.keymap:us
    console=ttyS0,115200 console=tty0

config:
  commands:
  - mkdir -p /tmp /var/tmp

  - |
    set -eu
    h="$(cat /usr-image/%{image-name}.usrhash)"
    uuid() { printf '%s-%s-%s-%s-%s' "${1:0:8}" "${1:8:4}" "${1:12:4}" "${1:16:4}" "${1:20:12}"; }
    d="%{install-root}/repart.d"
    mkdir -p "${d}"
    cp /repart/usr/lib/repart.d/*.conf "${d}/"
    printf 'UUID=%s\n' "$(uuid "${h:0:32}")" >> "${d}/20-usr-a.conf"
    printf 'UUID=%s\n' "$(uuid "${h:32:32}")" >> "${d}/21-usr-verity-a.conf"
    head -n 20 "${d}"/*.conf

  - |
    set -eu
    kver="$(ls /kmods/usr/lib/modules)"
    [ "$(echo "${kver}" | wc -w)" = 1 ]
    src="/kmods/usr/lib/modules/${kver}"
    dst="/initrd/usr/lib/modules/${kver}"
    rm -rf /initrd/usr/lib/modules
    mkdir -p "${dst}"
    for m in %{initrd-modules}; do
      modprobe -d /kmods/usr -S "${kver}" --show-depends "${m}" 2>/dev/null || true
    done | sed -n 's/^insmod \([^ ]*\).*/\1/p' | sort -u > /tmp/initrd-modules.txt
    while read -r path; do
      rel="${path#/kmods/usr/lib/modules/${kver}/}"
      install -Dm644 "${src}/${rel}" "${dst}/${rel}"
    done < /tmp/initrd-modules.txt
    cp "${src}"/modules.order "${src}"/modules.builtin* "${dst}/"
    depmod -b /initrd/usr "${kver}"
    echo "initrd modules: $(wc -l < /tmp/initrd-modules.txt)"
    for need in loop dm-verity erofs virtio_net; do
      grep -q "/${need}\.ko" /tmp/initrd-modules.txt || grep -q "/${need}.ko" "${src}/modules.builtin" || {
        echo "ERROR: initrd lacks ${need}" >&2; exit 1; }
    done
    install -Dm644 "${src}/vmlinuz" /tmp/vmlinuz

  - |
    set -eu
    cd /initrd
    ls -la /initrd
    for d in bin lib; do
      [ -e "${d}" ] || ln -s "usr/${d}" "${d}"
    done
    ln -sfn usr/lib/systemd/systemd init
    mkdir -p etc run sys proc dev tmp var sysroot
    ln -sfn ../usr/lib/os-release etc/initrd-release
    rm -f etc/machine-id
    systemd-sysusers --root=/initrd
    wants=usr/lib/systemd/system
    mkdir -p "${wants}/initrd.target.wants" "${wants}/network-online.target.wants"
    ln -sf ../systemd-networkd.service "${wants}/initrd.target.wants/systemd-networkd.service"
    ln -sf ../systemd-resolved.service "${wants}/initrd.target.wants/systemd-resolved.service"
    ln -sf ../imports.target "${wants}/initrd.target.wants/imports.target"
    ln -sf ../bluefin-populate-etc.service "${wants}/initrd.target.wants/bluefin-populate-etc.service"
    ln -sf ../bluefin-ignition-kargs.service "${wants}/initrd.target.wants/bluefin-ignition-kargs.service"
    ln -sf ../systemd-networkd-wait-online.service "${wants}/network-online.target.wants/systemd-networkd-wait-online.service"
    for tool in systemd-importd systemd-pull; do
      [ -x "usr/lib/systemd/${tool}" ] || { echo "ERROR: initrd lacks ${tool}" >&2; exit 1; }
    done
    for tool in systemd-dissect varlinkctl systemd-tmpfiles; do
      [ -x "usr/bin/${tool}" ] || { echo "ERROR: initrd lacks ${tool}" >&2; exit 1; }
    done
    [ -x usr/lib/systemd/systemd-veritysetup ] || { echo "ERROR: initrd lacks systemd-veritysetup" >&2; exit 1; }
    # bluefin-boot-diagnostics (failure summary, RAM check) and what it runs.
    for tool in libexec/bluefin-boot-diagnostics bin/bash bin/curl bin/stat bin/timeout bin/tee; do
      [ -x "usr/${tool}" ] || { echo "ERROR: initrd lacks ${tool}" >&2; exit 1; }
    done
    rm -rf usr/share/man usr/share/doc usr/share/info usr/include usr/lib/*/pkgconfig
    find . -name '*.a' -delete
    du -sh /initrd
    # cpio records mtimes; everything created above carries the build time.
    find . -mindepth 1 -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} +
    find . -mindepth 1 -printf '%P\n' | LC_ALL=C sort | cpio -o -H newc --reproducible --quiet | zstd -19 -T0 -q > /tmp/initrd.cpio.zst
    ls -lh /tmp/initrd.cpio.zst

  - |
    set -eu
    mkdir -p "%{install-root}/efi-keys"
    usrhash="$(cat /usr-image/%{image-name}.usrhash)"
    uki() {
      printf 'usrhash=%s %s %s' "${usrhash}" "$2" "%{common-cmdline}" > "/tmp/$1.cmdline"
      echo "$1: $(cat "/tmp/$1.cmdline")"
      ukify build \
        --linux=/tmp/vmlinuz \
        --initrd=/tmp/initrd.cpio.zst \
        --cmdline=@"/tmp/$1.cmdline" \
        --os-release=@/osrel/usr/lib/os-release \
        --uname="$(ls /kmods/usr/lib/modules)" \
        --signtool=systemd-sbsign \
        --no-sign-kernel \
        --secureboot-private-key=/boot-keys/DB.key \
        --secureboot-certificate=/boot-keys/DB.crt \
        --output="%{install-root}/$1.efi"
      sbverify --cert /boot-keys/DB.crt "%{install-root}/$1.efi"
    }
    uki bluefin-server-netboot_%{image-version} "%{netboot-cmdline}"
    uki bluefin-server-%{image-version} "%{disk-cmdline}"
    uki bluefin-server-installer_%{image-version} "%{installer-cmdline}"
    cp /efi-keys/usr/share/bluefin-server/efi-keys/*.auth "%{install-root}/efi-keys/"
    ls -l "%{install-root}"
