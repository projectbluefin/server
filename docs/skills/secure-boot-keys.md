---
name: secure-boot-keys
description: Secure Boot and image signing key management for Bluefin Server. Load when rotating keys, setting up CI secrets, or debugging signature verification.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-04"
---
# Secure Boot Key Management

Bluefin Server signs the boot chain, kernel modules, and the release manifest.
This skill covers what each key signs, where it lives, and how CI gets it.

## Key inventory

| Key | Signs | Private location | Public location |
|---|---|---|---|
| PK (Platform Key) | KEK updates | `files/boot-keys/PK.key` | `files/boot-keys/PK.crt` |
| KEK (Key Exchange Key) | db updates | `files/boot-keys/KEK.key` | `files/boot-keys/KEK.crt` |
| DB (Signature Database) | systemd-boot, UKIs | `files/boot-keys/DB.key` | `files/boot-keys/DB.crt` |
| linux-module-cert | kernel modules | `files/boot-keys/linux-module-cert.key` | `files/boot-keys/modules/linux-module-cert.crt` |
| sysupdate-signing | `SHA256SUMS` | `files/boot-keys/sysupdate-signing.asc` | `files/boot-keys/import-pubring.pgp` |

The module certificate is baked into the kernel's trusted keyring via
`SYSTEM_TRUSTED_KEYS`; changing it forces a kernel rebuild. The release
certificate is also committed as `files/release-keys/linux-module-cert.crt`:
the key-free kernel cache (`scripts/kernel-cache.sh`, see `ci-tooling.md`) is
built against it, and release builds stop if it differs from the one in
`BOOT_KEYS_TARBALL`.

## Local development

```bash
just gen-dev-keys          # throwaway keys in files/boot-keys/ (gitignored)
just gen-dev-keys --force  # rotate the Secure Boot and image signing keys
just gen-dev-keys --force --private-module-key  # also a fresh module key
```

`just validate` and `just build-image` depend on `gen-dev-keys`, so a fresh
clone builds out of the box.

### The INSECURE dev module key

The module signing pair of a `gen-dev-keys` key set is not generated: it is
the committed, public pair in `files/dev-keys/`
(`INSECURE-dev-module-key.{pem,crt}`; see its `README.md`). The module
certificate is part of the kernel's cache key, so with one fixed dev
certificate every non-release build (pull requests, the nightly build, local
builds) pulls the kernel that `scripts/kernel-cache.sh seed dev` pushed on
the last release instead of compiling it (see "Build time and caches" in
[ci-tooling.md](ci-tooling.md)).

A key set generated before the dev key existed keeps its own module
certificate, so the kernel still compiles; `just gen-dev-keys` says so, and
`just gen-dev-keys --force` switches it to the dev key.

- **Public on purpose.** Anyone can sign a module that a dev kernel loads
  under lockdown. Dev images are also signed with throwaway Secure Boot keys
  and never published. For an image you boot on hardware you care about,
  use `--private-module-key` (the kernel then builds locally).
- **Never in a release.** Release builds install `BOOT_KEYS_TARBALL` and run
  `scripts/check-release-keys.sh`, which fails when the module certificate or
  key is the dev pair (compared by public key); `kernel-cache.sh seed
  release` runs it too. The release kernel trusts only
  `files/release-keys/linux-module-cert.crt`, so dev-signed modules do not
  load on it.
- **Never in an artifact.** FSDK's kernel reads only
  `/keys/linux-module-cert.crt` (`SYSTEM_TRUSTED_KEYS`, `MODULE_SIG_KEY ""`,
  no `MODULE_SIG_ALL`): the private key is used only by
  `bluefin-server/kernel-modules.bst` and the other signing elements through
  `bluefin-server/keys/boot-keys.bst`, which is never pushed. No element
  stages `files/dev-keys/` (`tests/unit/test_dev_module_key.py`).

## CI secrets

On `main`, the workflow unpacks two secrets from the `release` environment,
which only `main` may use (see "Environments and secrets" in
[ci-tooling.md](ci-tooling.md)):

- `BOOT_KEYS_TARBALL` — gzipped tar of `files/boot-keys/` with the real
  PK/KEK/DB, module key, and sysupdate signing key.
- `SYSUPDATE_SIGNING_KEY` — the ASCII-armored secret key written to
  `files/boot-keys/sysupdate-signing.asc`.

Pull requests get throwaway keys from `just gen-dev-keys` (with the public
dev module pair); they never see the real secrets.

## Key rotation

1. Generate new keys (`just gen-dev-keys --force --private-module-key`
   locally, or the equivalent in a secure environment for production). Plain
   `--force` installs the public INSECURE dev module key, which
   `scripts/check-release-keys.sh` rejects for release builds.
2. Update the CI secrets (`BOOT_KEYS_TARBALL`, `SYSUPDATE_SIGNING_KEY`), and
   commit the new public module certificate as
   `files/release-keys/linux-module-cert.crt` in the same change.
3. Bump `image-version` in `include/image.yml` (a new build is required; the
   old image still trusts the old keys).
4. Nodes re-enroll Secure Boot keys on next boot if the firmware is in Setup
   Mode, or the operator enrolls manually via the systemd-boot menu.

The module key is the hardest to rotate: it is baked into the kernel, so a
new kernel build is mandatory. Plan kernel rebuilds into the rotation window.

## Verification

- [ ] `just validate` passes after key generation.
- [ ] `sbverify --cert files/boot-keys/DB.crt <uki>` passes on built UKIs.
- [ ] `gpgv --keyring files/boot-keys/import-pubring.pgp SHA256SUMS.gpg SHA256SUMS` passes.
- [ ] No private keys are committed outside the gitignored `files/boot-keys/`,
      except the public INSECURE dev module key in `files/dev-keys/`.
- [ ] `bash scripts/check-release-keys.sh` passes on a release key set.

## See also

- [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md) —
  manifest signing and sysupdate trust model.
- [ddi-installer-build.md](ddi-installer-build.md) — local build and dogfood
  workflow.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary.
