kind: manual
description: |
  FSDK kernel image plus its modules, signed with our module key
  (files/boot-keys/linux-module-cert.key) and zstd-compressed. The kernel
  trusts the matching certificate through the linux-module-cert override,
  so lockdown accepts exactly these modules and ones we sign later (ZFS).
  Mirrors freedesktop-sdk's vm/boot/efi-secure/signed-modules.bst.

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- freedesktop-sdk.bst:components/findutils.bst
- freedesktop-sdk.bst:components/kmod.bst
- freedesktop-sdk.bst:components/linux.bst
- freedesktop-sdk.bst:components/openssl.bst
- freedesktop-sdk.bst:components/sign-file.bst
- freedesktop-sdk.bst:components/zstd.bst
- bluefin-server/keys/boot-keys.bst

variables:
  strip-binaries: ''

config:
  install-commands:
  - |
    set -eu
    mkdir -p "%{install-root}%{indep-libdir}"
    cp -rT %{indep-libdir}/modules "%{install-root}%{indep-libdir}/modules"
    for kdir in "%{install-root}%{indep-libdir}"/modules/*/; do
      rm -f "${kdir}vmlinux" "${kdir}System.map" "${kdir}build"
    done

  # One module per worker, all cores at once. The output matches a serial
  # run: sign-file adds no signing time and zstd compresses each file alone.
  # Any failing worker makes xargs, and so the build, fail.
  - |
    set -euo pipefail
    openssl x509 -inform PEM -outform DER \
      -in /boot-keys/modules/linux-module-cert.crt -out module-cert.der
    find "%{install-root}%{indep-libdir}/modules" -type f \( -name '*.ko' -o -name '*.ko.zst' \) -print0 |
      xargs -0 -r -n1 -P"$(nproc)" sh -euc '
        ko="${1%.zst}"
        if [ "${ko}" != "$1" ]; then zstd -d --rm -q "$1"; fi
        sign-file sha512 /boot-keys/linux-module-cert.key module-cert.der "${ko}"
        if [ "$(modinfo -F sig_hashalgo "${ko}")" != sha512 ]; then
          echo "ERROR: ${ko} is not signed with sha512" >&2
          exit 1
        fi
        zstd -19 --rm -q "${ko}"
      ' sh

  - |
    set -eu
    for kver in $(ls "%{install-root}%{indep-libdir}/modules"); do
      depmod -b "%{install-root}%{prefix}" "${kver}"
    done
