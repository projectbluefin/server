kind: import
description: |
  Install the public OpenPGP keyring used by systemd-sysupdate to verify
  SHA256SUMS manifests downloaded from GitHub Releases.

  The matching private key is stored as the GitHub Actions repository secret
  SYSUPDATE_SIGNING_KEY. Release assets are signed in CI before upload.

sources:
  - kind: local
    path: files/os/sysupdate-keys

config:
  target: /usr/lib/systemd
