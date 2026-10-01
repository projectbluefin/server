kind: manual
description: |
  systemd-boot signed with our DB key, installed as
  /usr/lib/systemd/boot/efi/systemd-boot<arch>.efi.signed. `bootctl install`
  (and so systemd-sysinstall) prefers the .signed variant when present, so
  disk installs get a boot loader that Secure Boot accepts.

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:components/systemd.bst
- freedesktop-sdk.bst:components/_private/sbsigntools.bst
- bluefin-server/keys/boot-keys.bst

variables:
  strip-binaries: ''
  efi-arch: x64
  (?):
  - arch == "aarch64":
      efi-arch: aa64

config:
  install-commands:
  - |
    set -eu
    src=%{indep-libdir}/systemd/boot/efi/systemd-boot%{efi-arch}.efi
    install -d "%{install-root}%{indep-libdir}/systemd/boot/efi"
    # systemd-sbsign, unlike sbsign, takes the signing time from
    # SOURCE_DATE_EPOCH, so the signature is reproducible.
    %{indep-libdir}/systemd/systemd-sbsign sign \
      --private-key=/boot-keys/DB.key --certificate=/boot-keys/DB.crt \
      --output="%{install-root}${src}.signed" "${src}"
    sbverify --cert /boot-keys/DB.crt "%{install-root}${src}.signed"
