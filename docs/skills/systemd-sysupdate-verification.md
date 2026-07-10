---
name: systemd-sysupdate-verification
description: "Configure and operate GPG signature verification for Bluefin Server's systemd-sysupdate OTA updates from GitHub Releases."
metadata:
  context7-sources:
    - /systemd/systemd
---

# systemd-sysupdate Signature Verification

Use this skill when working on Bluefin Server's over-the-air update mechanism,
specifically the transfer files, release signing, or public keyring shipped in
the OS image.

## When to Use

- Modifying `files/os/sysupdate.d/*.transfer` update definitions.
- Rotating or replacing the release signing key.
- Debugging `systemd-sysupdate` failures related to `SHA256SUMS.gpg` verification.

## When NOT to Use

- General BuildStream element or dependency questions (use `avoid-over-engineering` or `ddi-installer`).
- SBOM or container-image signing questions (use `signing-and-sbom`).

## How It Works

`systemd-sysupdate` downloads `SHA256SUMS` manifests from the URL configured in
each transfer's `[Source]` section. By default it also downloads the detached
signature `SHA256SUMS.gpg` and verifies it against the public keyring before
using the manifest.

Key facts from `sysupdate.d(5)`:

- `Verify=` in `[Transfer]` is a boolean and defaults to `yes`.
- When enabled, `systemd-sysupdate` validates the GPG signature of each
  downloaded `SHA256SUMS` manifest.
- The public keyring is read from `/usr/lib/systemd/import-pubring.pgp` or
  `/etc/systemd/import-pubring.pgp`.

## Repository Layout

- `files/os/sysupdate-keys/import-pubring.pgp` — public OpenPGP keyring (binary
  format). Shipped to `/usr/lib/systemd/import-pubring.pgp` by
  `elements/bluefin-server/os-sysupdate-keys.bst`.
- `.github/workflows/build.yml` — signs both `dist/SHA256SUMS` and
  `dist/ddi/SHA256SUMS` during release using the `SYSUPDATE_SIGNING_KEY`
  repository secret and uploads the `.gpg` detached signatures.

## Rotating the Signing Key

1. Generate a new RSA sign-only key:
   ```bash
   export GNUPGHOME=$(mktemp -d)
   cat > "$GNUPGHOME/keygen" <<'EOF'
   %echo Generating new sysupdate signing key
   Key-Type: RSA
   Key-Length: 4096
   Key-Usage: sign
   Name-Real: Bluefin Server Release Signing
   Name-Email: releases@projectbluefin.io
   Expire-Date: 0
   %no-protection
   %commit
   %echo done
   EOF
   gpg --batch --gen-key "$GNUPGHOME/keygen"
   KEYID=$(gpg --list-keys --with-colons 'releases@projectbluefin.io' | awk -F: '/^pub:/ {print $5; exit}')
   gpg --export --output files/os/sysupdate-keys/import-pubring.pgp "$KEYID"
   gpg --export-secret-keys --armor "$KEYID" > /secure/offline/backup.asc
   rm -rf "$GNUPGHOME"
   ```
2. Update the GitHub Actions repository secret `SYSUPDATE_SIGNING_KEY` with the
   new ASCII-armored private key.
3. Rebuild and publish a release. Existing hosts will only trust updates signed
   by the new key, so plan the rotation around a release boundary.

## Verification

- [ ] `files/os/sysupdate.d/*.transfer` does not contain `Verify=no`.
- [ ] `elements/bluefin-server/os-stack.bst` includes
      `bluefin-server/os-sysupdate-keys.bst`.
- [ ] `files/os/sysupdate-keys/import-pubring.pgp` exists and contains the
      public half of the key used to sign releases.
- [ ] CI signs `dist/SHA256SUMS` and `dist/ddi/SHA256SUMS` and uploads the
      matching `.gpg` files.
