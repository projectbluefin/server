---
name: systemd-sysupdate-verification
description: Configure and operate GPG signature verification for Bluefin Server's systemd-sysupdate OTA updates from GitHub Releases.
metadata:
  type: reference
  status: stable
  last_updated: 2026-09-04
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

`systemd-sysupdate` discovers available versions by fetching a `SHA256SUMS`
manifest from the static `Path=` configured in each transfer's `[Source]`
section. By default it also downloads the detached signature `SHA256SUMS.gpg`
and verifies it against the public keyring before using the manifest.

Key facts from `sysupdate.d(5)`:

- `Path=` in `[Source]` is static. It is **not** expanded with `@v` or any
  other placeholder.
- `@v` belongs only in `MatchPattern=`. `systemd-sysupdate` parses versions
  out of filenames that match the pattern after reading the flat manifest at
  `<Path>/SHA256SUMS`.
- `Verify=` in `[Transfer]` is a boolean and defaults to `yes`.
- When enabled, `systemd-sysupdate` validates the GPG signature of the
  downloaded `SHA256SUMS` manifest.
- The public keyring is read from `/usr/lib/systemd/import-pubring.pgp` or
  `/etc/systemd/import-pubring.pgp`.

## Current implementation status

The current tree uses a single root/ESP slot and a single signed manifest flow for OTA delivery. Future work on dual-slot root partitions, dual UKIs, and broader rollback strategies is tracked in [architecture-roadmap.md](architecture-roadmap.md).

## Repository Layout

- `files/os/sysupdate-keys/import-pubring.pgp` — public OpenPGP keyring (binary
  format). Shipped to `/usr/lib/systemd/import-pubring.pgp` by
  `elements/bluefin-server/os-sysupdate-keys.bst`.
- `.github/workflows/build.yml` — assembles all release assets under
  `dist/release/`, verifies the exact versioned artifact set with
  `.github/scripts/verify-release.py`, generates a single combined
  `dist/release/SHA256SUMS`, signs it with the `SYSUPDATE_SIGNING_KEY`
  repository secret, verifies the detached signature with the shipped public
  keyring, and uploads `dist/release/*` to the GitHub Release.
- `files/os/sysupdate.d/*.transfer` — each transfer points its static `Path=`
  at `https://github.com/projectbluefin/server/releases/latest/download/` so
  all transfers share the same signed manifest.

## Core Process

1. Edit or add a transfer in `files/os/sysupdate.d/` — static `Path=` in
   `[Source]`, `@v` only in `MatchPattern=`.
2. Test the trust chain locally in a Fedora container (see "Common Gotchas").
3. On merge, CI assembles `dist/release/`, verifies the artifact set with
   `verify-release.py`, signs the single combined `SHA256SUMS`, verifies the
   detached signature, and uploads to the GitHub Release.
4. Hosts verify `SHA256SUMS.gpg` against the shipped
   `/usr/lib/systemd/import-pubring.pgp` before applying any update.
5. Rotate the signing key only around a release boundary (procedure below).

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

## Common Gotchas

- **Do not put `@v` in `[Source] Path=`.** `Path=` must be a static base URL.
  `systemd-sysupdate` fetches `<Path>/SHA256SUMS` (+ `.gpg`) as the version
  manifest, then matches filenames containing `@v` through `MatchPattern=`.
  A path like `.../releases/download/@v/` will produce a 404 and break version
  discovery for every transfer.
- **One combined manifest per release.** All transfers share the same `Path=`
  and therefore the same `SHA256SUMS` file. Signing separate manifests per
  asset type and uploading them all as `SHA256SUMS` causes collisions on the
  release page and breaks sysupdate.
- **Local export manifests are not release manifests.** `just export-installer`,
  `just export-ddi`, and `just export-sysext` each write a `SHA256SUMS` in
  `dist/`, `dist/ddi/`, and `dist/sysext/` for local verification. Only the
  combined `dist/release/SHA256SUMS` is uploaded and used by `systemd-sysupdate`.
- **`Verify=` belongs to `[Transfer]`, not `[Source]`.** Use it only in local
  scratch copies for structural testing.
- **Testing the trust chain locally.** In a Fedora container
  (`dnf install systemd-udev systemd-container` — the `systemd-pull` helper
  lives in `systemd-container`), copy
  `files/os/sysupdate-keys/import-pubring.pgp` to
  `/usr/lib/systemd/import-pubring.pgp`, point `--definitions=` at a scratch
  copy of a transfer with only `[Target] Path=` rewritten, and run `list` and
  `update`. The live release must yield "Signature verification succeeded";
  gpg's "WARNING: Using untrusted key!" is expected ownertrust noise.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "`Verify=no` just for local testing." | Never ship it; `Verify=` defaults to `yes` and must stay that way in every shipped transfer. |
| "Put `@v` in `Path=` for cleaner URLs." | `Path=` is static and never expanded; `@v` there 404s version discovery for every transfer. |
| "Sign a separate manifest per asset type." | All transfers share one `Path=`; multiple `SHA256SUMS` uploads collide and break sysupdate. |

## Red Flags

- `Verify=no` in any shipped transfer.
- `@v` anywhere in a `[Source] Path=`.
- More than one `SHA256SUMS` manifest uploaded to a single release.
- The private signing key stored anywhere except the `SYSUPDATE_SIGNING_KEY`
  repository secret.

## Verification

- [ ] `files/os/sysupdate.d/*.transfer` does not contain `Verify=no`.
- [ ] `elements/bluefin-server/os-stack.bst` includes
      `bluefin-server/os-sysupdate-keys.bst`.
- [ ] `files/os/sysupdate-keys/import-pubring.pgp` exists and contains the
      public half of the key used to sign releases.
- [ ] CI assembles all release assets under `dist/release/`.
- [ ] CI generates and signs exactly one combined `dist/release/SHA256SUMS`
      manifest, producing `dist/release/SHA256SUMS.gpg`.
- [ ] CI uploads `dist/release/*` to the GitHub Release.
- [ ] Every transfer in `files/os/sysupdate.d/*.transfer` uses a static `Path=`
      with no `@v` placeholder.
- [ ] Every transfer uses `@v` only inside `MatchPattern=`.
