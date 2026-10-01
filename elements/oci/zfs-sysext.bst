kind: manual
description: |
  Produce the opt-in OpenZFS systemd-sysext.

  Output: zfs_<image-version>.raw, its .raw.zst release asset, and
  SHA256SUMS. The spl/zfs modules only load on the kernel they were built
  against, so the sysext is locked to one image: its extension-release file
  is extension-release.zfs_<image-version> (matching the installed file
  name) with ID=bluefin-server and VERSION_ID=<image-version>. Several
  versions can sit side by side in /var/lib/extensions; systemd-sysext
  merges only the one matching the booted image, so an A/B rollback keeps
  ZFS. Installed nodes get it in lock-step with OS updates through the
  `zfs` sysupdate feature (`updatectl enable zfs`).

  Contents: OpenZFS tools, libraries, udev rules and systemd units from
  zfs/openzfs-signed.bst; libtirpc (not in the base image); and the signed
  modules under /usr/lib/modules/<kver>/extra/zfs/. No modules.* index:
  zfs-load-module.service loads them through the base image's
  /usr/libexec/bluefin-sysext-modules (see systemd-sysext-extensions.md).

(@):
- include/arch.yml
- include/image.yml
- include/zfs.yml
- include/sysext.yml

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:components/erofs-utils.bst
- freedesktop-sdk.bst:components/findutils.bst
- freedesktop-sdk.bst:components/libtirpc.bst
- freedesktop-sdk.bst:components/zstd.bst
- filename: bluefin-server/kernel-modules.bst
  config:
    location: /kernel-modules
- filename: zfs/openzfs-signed.bst
  config:
    location: /openzfs

sources:
- kind: local
  path: files/zfs/sysext
  directory: sysext-src

variables:
  strip-binaries: ""
  sysext-name: "zfs"
  sysext-image: "zfs_%{image-version}"
  sysext-release: "zfs_%{image-version}"
  sysext-version: "%{image-version}"
  sysext-architecture: "%{systemd-arch}"

config:
  install-commands:
  - |
    set -euo pipefail
    moddir="%{indep-libdir}/modules"

    kver="$(ls "/kernel-modules${moddir}")"
    if [ "$(echo "${kver}" | wc -w)" -ne 1 ]; then
      echo "ERROR: expected exactly one kernel in bluefin-server/kernel-modules.bst, found: ${kver}" >&2
      exit 1
    fi
    zfs_kver="$(ls "/openzfs${moddir}")"
    if [ "${zfs_kver}" != "${kver}" ]; then
      echo "ERROR: ZFS modules were built for '${zfs_kver}', the image kernel is '${kver}'" >&2
      exit 1
    fi

    # Everything OpenZFS installs under /usr, minus development, debug and
    # documentation files (the base image excludes those domains too).
    mkdir -p sysext
    cp -a /openzfs%{prefix} sysext%{prefix}
    rm -rf \
      "sysext%{includedir}" \
      "sysext%{libdir}/pkgconfig" \
      "sysext%{debugdir}" \
      "sysext%{mandir}"
    find "sysext%{libdir}" -maxdepth 1 -type l -name '*.so' -delete

    # libnvpair links libtirpc, which no base image component pulls in.
    cp -a "%{libdir}"/libtirpc.so.3* "sysext%{libdir}/"

  - |
    set -euo pipefail
    moddir="sysext%{indep-libdir}/modules"
    kver="$(ls "${moddir}")"

    # Only the modules, in a directory of their own; the base image's
    # bluefin-sysext-modules indexes them at runtime. A modules.* index here
    # would hide the base image's and every other module sysext's.
    mkdir "${moddir}/${kver}/extra/zfs"
    for m in spl zfs; do
      mv "${moddir}/${kver}/extra/${m}.ko.zst" "${moddir}/${kver}/extra/zfs/"
    done
    if [ -n "$(find "${moddir}" -name 'modules.*' -print -quit)" ]; then
      echo "ERROR: the sysext would ship a modules.* index" >&2
      exit 1
    fi
    if [ "$(find "${moddir}/${kver}" -mindepth 1 -maxdepth 2 ! -path '*/extra/zfs' ! -path '*/extra')" ]; then
      echo "ERROR: unexpected files next to extra/zfs in ${moddir#sysext}/${kver}" >&2
      exit 1
    fi
    # zfs-load-module.service loads the modules; systemd-modules-load runs
    # before the sysext merges and cannot find them.
    rm -rf "sysext%{indep-libdir}/modules-load.d"

  - |
    set -euo pipefail
    unitdir="sysext%{indep-libdir}/systemd/system"

    install -m 0644 sysext-src/zfs-load-module.service "${unitdir}/"
    install -D -m 0644 sysext-src/50-zfs.preset \
      "sysext%{indep-libdir}/systemd/system-preset/50-zfs.preset"

    # Presets are inert inside a sysext. These links let `systemd-sysext
    # merge` (which reloads the manager because of EXTENSION_RELOAD_MANAGER=1)
    # followed by `systemctl start zfs.target` bring up ZFS.
    mkdir -p "${unitdir}/multi-user.target.wants" "${unitdir}/zfs.target.wants"
    ln -s ../zfs.target "${unitdir}/multi-user.target.wants/zfs.target"
    for u in zfs-load-module.service zfs-import-scan.service zfs-mount.service; do
      ln -s "../${u}" "${unitdir}/zfs.target.wants/${u}"
    done

  - "%{sysext-pack}"
