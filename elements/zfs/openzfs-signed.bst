kind: manual
description: |
  zfs/openzfs.bst with spl.ko and zfs.ko signed by our module key
  (files/boot-keys/linux-module-cert.key) and zstd-compressed, so the
  lockdown=integrity FSDK kernel accepts them. Same signing steps as
  bluefin-server/kernel-modules.bst.

  Like zfs/openzfs.bst, this element has no runtime `depends:` so
  oci/zfs-sysext.bst can stage exactly the ZFS files at a private location.

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- freedesktop-sdk.bst:components/findutils.bst
- freedesktop-sdk.bst:components/kmod.bst
- freedesktop-sdk.bst:components/openssl.bst
- freedesktop-sdk.bst:components/sign-file.bst
- freedesktop-sdk.bst:components/zstd.bst
- bluefin-server/keys/module-signing-key.bst
- filename: zfs/openzfs.bst
  config:
    location: /openzfs

variables:
  strip-binaries: ''

config:
  install-commands:
  - |
    set -eu
    cp -a /openzfs/. "%{install-root}/"

  - |
    set -eu
    openssl x509 -inform PEM -outform DER \
      -in /boot-keys/modules/linux-module-cert.crt -out module-cert.der
    find "%{install-root}%{indep-libdir}/modules" -type f -name '*.ko.zst' -exec zstd -d --rm -q {} ';'
    find "%{install-root}%{indep-libdir}/modules" -type f -name '*.ko' \
      -exec sign-file sha512 /boot-keys/linux-module-cert.key module-cert.der {} ';' \
      -exec zstd -19 --rm -q {} ';'

  - |
    set -eu
    for kdir in "%{install-root}%{indep-libdir}"/modules/*/; do
      for m in spl zfs; do
        ko="${kdir}extra/${m}.ko.zst"
        if [ "$(modinfo -F sig_hashalgo "${ko}")" != sha512 ]; then
          echo "ERROR: ${ko#%{install-root}} is not signed with sha512" >&2
          exit 1
        fi
      done
    done
