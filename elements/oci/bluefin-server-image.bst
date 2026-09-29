kind: script
description: |
  Release artifacts for one Bluefin Server image version.

    bluefin-server_<ver>.raw               UAPI.3 DDI: usr, usr-verity, ESP (disk UKI).
                                           Diskless nodes pull it into RAM; booted
                                           diskless it is also the installer
                                           (systemd-sysinstall --definitions=
                                           /run/bluefin/boot/bluefin/repart.d copies
                                           usr and links the disk UKI).
    bluefin-server_<ver>_<uuid>.usr.raw         sysupdate source for the usr slot
    bluefin-server_<ver>_<uuid>.usr-verity.raw  sysupdate source for the verity slot
                                           (<uuid>: partition UUID derived from usrhash)
    bluefin-server-<ver>.efi               disk UKI (sysupdate source for $BOOT); the
                                           hyphen matches bootctl's "default bluefin-server-*"
    bluefin-server-netboot_<ver>.efi       diskless UKI (UEFI HTTP boot target)
    bluefin-server-netboot_<ver>.esp.raw   ESP image: signed systemd-boot + diskless
                                           UKI + key enrollment; write it to a USB
                                           stick to boot diskless without HTTP boot
    bluefin-server-installer_<ver>.raw     offline USB installer: usr + usr-verity
                                           (bluefin-installer-* labels) and an ESP with
                                           signed systemd-boot, the installer UKI, key
                                           enrollment, and the disk UKI + repart.d that
                                           systemd-sysinstall lays onto the target disk
    efi-keys/                              Secure Boot enrollment payloads
    zfs_<ver>.raw.zst, kubestellar_<ver>.raw.zst, kubeadm_<ver>.raw.zst
                                           opt-in sysexts locked to this image version
    k0s-<k0s-ver>.raw.zst                  opt-in k0s sysext (own version axis)
    bluefin-server_<ver>.spdx.json         SPDX 2.3 SBOM (oci/bluefin-server-sbom.bst)
    SHA256SUMS, SHA256SUMS.gpg             manifest of all of the above, signed with
                                           files/boot-keys/sysupdate-signing.asc; the
                                           image trusts the matching import-pubring.pgp
    sysupdate-keys/import-pubring.pgp      that keyring, for the release dry-run to
                                           check SHA256SUMS.gpg against a pull request's
                                           throwaway key; like efi-keys/ it is not
                                           published (releases carry top-level files only)

(@):
- include/image.yml

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- freedesktop-sdk.bst:components/dosfstools.bst
- freedesktop-sdk.bst:components/findutils.bst
- freedesktop-sdk.bst:components/mtools.bst
- freedesktop-sdk.bst:components/systemd.bst
- filename: oci/bluefin-server-usr.bst
  config:
    location: /usr-image
- filename: oci/bluefin-server-boot.bst
  config:
    location: /boot-out
- filename: bluefin-server/os-sd-boot-signed.bst
  config:
    location: /sd-boot
- freedesktop-sdk.bst:components/gnupg.bst
- freedesktop-sdk.bst:components/jq.bst
- bluefin-server/keys/boot-keys.bst
- filename: oci/k0s-sysext.bst
  config:
    location: /sysext/k0s
- filename: oci/kubestellar-sysext.bst
  config:
    location: /sysext/kubestellar
- filename: oci/zfs-sysext.bst
  config:
    location: /sysext/zfs
- filename: oci/kubeadm-sysext.bst
  config:
    location: /sysext/kubeadm
- filename: oci/bluefin-server-sbom.bst
  config:
    location: /sbom

variables:
  image-name: bluefin-server_%{image-version}
  netboot-name: bluefin-server-netboot_%{image-version}
  disk-uki: bluefin-server-%{image-version}.efi
  installer-uki: bluefin-server-installer_%{image-version}.efi
  efi-arch: x64
  (?):
  - arch == "aarch64":
      efi-arch: aa64

environment:
  # dosfstools 4.2 ignores SOURCE_DATE_EPOCH and stamps each ESP's volume
  # label with the current time; --invariant fixes the label time and the
  # volume ID.
  SYSTEMD_REPART_MKFS_OPTIONS_VFAT: --invariant

config:
  commands:
  - mkdir -p /tmp /var/tmp

  - |
    set -eu
    h="$(cat /usr-image/%{image-name}.usrhash)"
    uuid() { printf '%s-%s-%s-%s-%s' "${1:0:8}" "${1:8:4}" "${1:12:4}" "${1:16:4}" "${1:20:12}"; }
    uuid "${h:0:32}" > /tmp/usr.uuid
    uuid "${h:32:32}" > /tmp/usr-verity.uuid
    out="%{install-root}"
    cp /usr-image/%{image-name}.usr.raw "${out}/bluefin-server_%{image-version}_$(cat /tmp/usr.uuid).usr.raw"
    cp /usr-image/%{image-name}.usr-verity.raw "${out}/bluefin-server_%{image-version}_$(cat /tmp/usr-verity.uuid).usr-verity.raw"
    cp /boot-out/%{disk-uki} /boot-out/%{netboot-name}.efi "${out}/"
    cp -r /boot-out/efi-keys "${out}/"

  - |
    set -eu
    esp=/tmp/ddi-esp
    install -Dm644 /boot-out/%{disk-uki} "${esp}/EFI/Linux/%{disk-uki}"
    install -Dm644 -t "${esp}/bluefin/repart.d" /boot-out/repart.d/*.conf
    d=/tmp/ddi.repart.d
    mkdir -p "${d}"
    printf '[Partition]\nType=usr\nLabel=bluefin_usr_%{image-version}\nUUID=%s\nCopyBlocks=/usr-image/%{image-name}.usr.raw\n' "$(cat /tmp/usr.uuid)" > "${d}/10-usr.conf"
    printf '[Partition]\nType=usr-verity\nLabel=bluefin_usr_verity_%{image-version}\nUUID=%s\nCopyBlocks=/usr-image/%{image-name}.usr-verity.raw\n' "$(cat /tmp/usr-verity.uuid)" > "${d}/20-usr-verity.conf"
    printf '[Partition]\nType=esp\nFormat=vfat\nCopyFiles=%s:/\nSizeMinBytes=128M\nSizeMaxBytes=128M\n' "${esp}" > "${d}/30-esp.conf"
    # mcopy keeps mtimes; the staged ESP tree carries the build time.
    find "${esp}" -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} +
    systemd-repart --empty=create --size=auto --offline=yes --dry-run=no \
      --seed=6f1b0fe2-3c2a-4f2e-9f0a-b1e5e7a5e003 \
      --definitions="${d}" "%{install-root}/%{image-name}.raw"

  - |
    set -eu
    esp=/tmp/netboot-esp
    sdboot=/sd-boot/usr/lib/systemd/boot/efi/systemd-boot%{efi-arch}.efi.signed
    arch_upper="$(echo '%{efi-arch}' | tr a-z A-Z)"
    install -Dm644 "${sdboot}" "${esp}/EFI/BOOT/BOOT${arch_upper}.EFI"
    install -Dm644 "${sdboot}" "${esp}/EFI/systemd/systemd-boot%{efi-arch}.efi"
    install -Dm644 /boot-out/%{netboot-name}.efi "${esp}/EFI/Linux/%{netboot-name}.efi"
    install -Dm644 -t "${esp}/loader/keys/auto" /boot-out/efi-keys/*.auth
    mkdir -p "${esp}/loader/credentials"
    printf 'timeout 3\nconsole-mode keep\nsecure-boot-enroll if-safe\n' > "${esp}/loader/loader.conf"
    d=/tmp/netboot.repart.d
    mkdir -p "${d}"
    printf '[Partition]\nType=esp\nFormat=vfat\nCopyFiles=%s:/\nSizeMinBytes=160M\n' "${esp}" > "${d}/10-esp.conf"
    find "${esp}" -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} +
    systemd-repart --empty=create --size=auto --offline=yes --dry-run=no \
      --seed=6f1b0fe2-3c2a-4f2e-9f0a-b1e5e7a5e002 \
      --definitions="${d}" "%{install-root}/%{netboot-name}.esp.raw"

  - |
    set -eu
    esp=/tmp/installer-esp
    sdboot=/sd-boot/usr/lib/systemd/boot/efi/systemd-boot%{efi-arch}.efi.signed
    arch_upper="$(echo '%{efi-arch}' | tr a-z A-Z)"
    install -Dm644 "${sdboot}" "${esp}/EFI/BOOT/BOOT${arch_upper}.EFI"
    install -Dm644 "${sdboot}" "${esp}/EFI/systemd/systemd-boot%{efi-arch}.efi"
    install -Dm644 /boot-out/%{installer-uki} "${esp}/EFI/Linux/%{installer-uki}"
    # Outside EFI/Linux so systemd-boot never offers the disk UKI on the
    # stick; systemd-sysinstall --kernel= installs it onto the target disk.
    install -Dm644 /boot-out/%{disk-uki} "${esp}/bluefin/%{disk-uki}"
    install -Dm644 -t "${esp}/bluefin/repart.d" /boot-out/repart.d/*.conf
    install -Dm644 -t "${esp}/loader/keys/auto" /boot-out/efi-keys/*.auth
    printf 'timeout 3\nconsole-mode keep\nsecure-boot-enroll if-safe\n' > "${esp}/loader/loader.conf"
    d=/tmp/installer.repart.d
    mkdir -p "${d}"
    printf '[Partition]\nType=usr\nLabel=bluefin-installer-usr\nCopyBlocks=/usr-image/%{image-name}.usr.raw\n' > "${d}/10-usr.conf"
    printf '[Partition]\nType=usr-verity\nLabel=bluefin-installer-usr-verity\nCopyBlocks=/usr-image/%{image-name}.usr-verity.raw\n' > "${d}/20-usr-verity.conf"
    printf '[Partition]\nType=esp\nLabel=bluefin-installer\nFormat=vfat\nCopyFiles=%s:/\nSizeMinBytes=256M\n' "${esp}" > "${d}/30-esp.conf"
    find "${esp}" -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} +
    systemd-repart --empty=create --size=auto --offline=yes --dry-run=no \
      --seed=6f1b0fe2-3c2a-4f2e-9f0a-b1e5e7a5e004 \
      --definitions="${d}" "%{install-root}/bluefin-server-installer_%{image-version}.raw"

  - |
    set -eu
    cp /sysext/k0s/k0s-*.raw.zst /sysext/kubestellar/kubestellar_%{image-version}.raw.zst \
       /sysext/zfs/zfs_%{image-version}.raw.zst \
       /sysext/kubeadm/kubeadm_%{image-version}.raw.zst "%{install-root}/"

  - |
    set -eu
    # SPDX requires a creation time, which the plugin leaves to the build,
    # and unique SPDXIDs: FSDK bootstrap elements reached through two
    # junction paths are collected twice, as identical packages.
    # SOURCE_DATE_EPOCH is BuildStream's fixed sandbox default (1321009871),
    # so created is always 2011-11-11T11:11:11Z. That keeps the SBOM bit
    # identical across rebuilds; the real build time lives in the SLSA
    # provenance attestation, not here.
    jq --arg created "$(date -u -d "@${SOURCE_DATE_EPOCH}" +%Y-%m-%dT%H:%M:%SZ)" \
      '.creationInfo.created = $created
       | .packages |= unique_by(.SPDXID)
       | .relationships |= unique_by(.relatedSpdxElement)' \
      /sbom/bluefin-server.spdx.json > "%{install-root}/%{image-name}.spdx.json"

  - |
    set -eu
    cd "%{install-root}"
    sha256sum --binary *.raw *.efi *.raw.zst *.spdx.json > SHA256SUMS
    cat SHA256SUMS
    export GNUPGHOME=/tmp/gnupg
    mkdir -m 0700 -p "${GNUPGHOME}"
    gpg --batch --quiet --import /boot-keys/sysupdate-signing.asc
    gpg --batch --yes --pinentry-mode loopback --passphrase '' \
      --detach-sign --output SHA256SUMS.gpg SHA256SUMS
    # The keyring the image ships must accept this signature.
    gpgv --keyring /boot-keys/import-pubring.pgp SHA256SUMS.gpg SHA256SUMS
    install -Dm644 /boot-keys/import-pubring.pgp sysupdate-keys/import-pubring.pgp
