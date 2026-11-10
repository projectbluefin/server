kind: manual
description: |
  Signed EFI variable updates (PK.auth, KEK.auth, db.auth) that
  systemd-boot's `secure-boot-enroll` writes into firmware in setup mode.
  Mirrors freedesktop-sdk's components/_private/efi-keys.bst with our keys.

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- freedesktop-sdk.bst:components/openssl.bst
- freedesktop-sdk.bst:components/_private/sbsigntools.bst
- bluefin-server/keys/boot-keys.bst

variables:
  efi-keys-owner: 6f1b0fe2-3c2a-4f2e-9f0a-b1e5e7a5e000
  strip-binaries: ''

config:
  build-commands:
  - |
    set -eu
    for k in PK KEK DB; do
      openssl x509 -inform pem -outform der -in /boot-keys/${k}.crt -out ${k}.der
      sbsiglist --owner '%{efi-keys-owner}' --type x509 --output ${k}.esl ${k}.der
    done
    # 0x27 = NON_VOLATILE|BOOTSERVICE_ACCESS|RUNTIME_ACCESS, no APPEND_WRITE:
    # systemd-boot writes these with 0x27, so an append-flagged 0x67 makes the
    # firmware hash mismatch the signed digest and refuse the enroll (#612).
    sbvarsign --attributes 0x27 --key /boot-keys/PK.key --cert /boot-keys/PK.crt PK PK.esl --output PK.auth
    sbvarsign --attributes 0x27 --key /boot-keys/PK.key --cert /boot-keys/PK.crt KEK KEK.esl --output KEK.auth
    sbvarsign --attributes 0x27 --key /boot-keys/KEK.key --cert /boot-keys/KEK.crt db DB.esl --output db.auth

  install-commands:
  - install -Dm644 -t '%{install-root}%{datadir}/bluefin-server/efi-keys' PK.auth KEK.auth db.auth
  - install -Dm644 /boot-keys/DB.crt '%{install-root}%{datadir}/bluefin-server/efi-keys/db.crt'
