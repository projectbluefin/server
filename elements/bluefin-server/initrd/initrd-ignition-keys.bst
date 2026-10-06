kind: import
description: |
  OpenPGP keyring that bluefin-ignition-credentials verifies a network-booted
  node's bluefin-node.ign.gpg against, installed in the initrd (inside the
  signed UKI) as /usr/lib/bluefin/ignition-pubring.pgp. It is the only trust
  root for per-node configs: the release keyring (import-pubring.pgp, which
  authenticates SHA256SUMS) is never consulted, and this one never verifies a
  release. Not in the OS /usr, and no /etc override.

  It comes from files/boot-keys/ignition-pubring.pgp: a dev key from
  `just gen-dev-keys`, or on release builds the committed
  files/release-keys/ignition-pubring.pgp (CI copies it in;
  scripts/check-ignition-keys.sh refuses a release set without it).

sources:
  - kind: local
    path: files/boot-keys/ignition-pubring.pgp

config:
  target: /usr/lib/bluefin
