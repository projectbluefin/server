kind: import
description: |
  The key that signs SHA256SUMS (sysupdate-signing.asc, private) and the
  keyring that verifies it (import-pubring.pgp), staged at /boot-keys for
  bluefin-server-image only. Never add this element to a runtime stack: its
  artifact holds a private key. Generate local dogfood keys with
  `just gen-dev-keys`.

config:
  target: /boot-keys

sources:
- kind: local
  path: files/boot-keys/sysupdate-signing.asc
- kind: local
  path: files/boot-keys/import-pubring.pgp
