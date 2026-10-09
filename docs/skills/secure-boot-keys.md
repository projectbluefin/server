---
name: secure-boot-keys
description: Secure Boot and image signing key management for Bluefin Server. Load when rotating keys, setting up CI secrets, or debugging signature verification.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-08"
---
# Secure Boot Key Management

Bluefin Server signs the boot chain, kernel modules, and the release manifest.
This skill covers what each key signs, where it lives, and how CI gets it.

## Key inventory

| Key | Signs | Private location | Public location |
|---|---|---|---|
| PK (Platform Key) | KEK updates | `files/boot-keys/PK.key` | `files/boot-keys/PK.crt` |
| KEK (Key Exchange Key) | db updates | `files/boot-keys/KEK.key` | `files/boot-keys/KEK.crt` |
| DB (Signature Database) | systemd-boot, UKIs, shim and MokManager (`-o shim True`) | `files/boot-keys/DB.key` | `files/boot-keys/DB.crt`; also shim's vendor certificate |
| linux-module-cert | kernel modules | `files/boot-keys/linux-module-cert.key` | `files/boot-keys/modules/linux-module-cert.crt` |
| sysupdate-signing | `SHA256SUMS` | `files/boot-keys/sysupdate-signing.asc` | `files/boot-keys/import-pubring.pgp` |
| ignition-signing | `bluefin-node.ign` | dev: `files/boot-keys/ignition-signing.asc`; release: off CI | `files/boot-keys/ignition-pubring.pgp` (release: `files/release-keys/ignition-pubring.pgp`); see "The Ignition config key" in [booty-integration.md](booty-integration.md) |

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

## Shim

Today a machine boots Bluefin Server with Secure Boot only once the Bluefin
PK/KEK/db are enrolled (Setup Mode, systemd-boot's `secure-boot-enroll`).
The enrollment-free path is shim signed by Microsoft's UEFI CA, which most
firmware already trusts. `bluefin-server/shim.bst` builds shim from the
upstream release tarball (`shim-16.1.tar.bz2`, sha256-pinned; it bundles
gnu-efi) with the FSDK toolchain, no distro binary involved:

- **Vendor certificate = DB certificate.** `VENDOR_CERT_FILE` is
  `DB.crt` in DER, so shim trusts exactly what DB already signs:
  systemd-boot (its `DEFAULT_LOADER`, `\EFI\systemd\systemd-bootx64.efi`),
  the UKIs, and MokManager. No new key. A Microsoft-signed shim makes DB
  as powerful as Microsoft's own CA on every machine that trusts it, so
  that key needs stronger custody than the `BOOT_KEYS_TARBALL` CI secret
  before a submission (shim-review asks how it is protected).
- **SBAT.** `data/sbat.bluefin-server.csv` adds
  `shim.bluefin-server,1,Bluefin Server,shim,<ver>,https://github.com/projectbluefin/server`
  to shim's and MokManager's `.sbat`. Raise the generation (the `1`) to
  revoke every earlier Bluefin Server shim.
- **Checks.** The build fails unless `.vendor_cert` holds the DB
  certificate, `.sbat` holds the entry above, and `DEFAULT_LOADER` is
  systemd-boot. With `SOURCE_DATE_EPOCH` set the binary is bit-for-bit
  reproducible.
- **Outputs.** `shimx64.efi` unsigned (what Microsoft signs) plus
  DB-signed `shimx64.efi.signed` and `mmx64.efi.signed`, so a shim build
  still boots where the Bluefin keys are enrolled. Only the image's
  `shim` option uses them; where they land on the ESPs and what is not
  wired yet: "Shim path" in [ddi-installer.md](ddi-installer.md).

### shim-review submission

Microsoft signs shim only after review in
[rhboot/shim-review](https://github.com/rhboot/shim-review) (and only with
the UEFI CA 2023). The submission is a tagged repository with the filled-in
template, the unsigned `shimx64.efi` from a **release-key** build (dev builds
embed throwaway DB certificates), build logs and its SHA-256. Reviewers
expect:

- **A reproducible recipe in a separate repository.** Reviewers run
  `docker build .` and compare the hash. That Containerfile lives in a
  `projectbluefin/shim-review` fork, not here (this repository stays
  Containerfile-free); it reproduces this element's `make` invocation from
  the same tarball.
- **Two security contacts** (primary and secondary), each with a PGP key on
  a public keyserver. A reviewer mails each a PGP-encrypted challenge whose
  contents go back into the review issue.
- **Organization proof**: a legal entity, and the EV certificate used with
  Microsoft's Hardware Dev Center for the `.cab` submission.
- **SBAT for everything shim starts**: the entries above, plus a
  vendor-specific entry in systemd-boot's and systemd-stub's `.sbat` (both
  from FSDK's systemd build).
- **Answers on the rest of the chain**: lockdown (`lockdown=integrity`
  always on), the module signing key (persistent, not ephemeral, see "Key
  inventory"), the NX-compatibility flag (shim's default, off), whether the
  embedded certificate is a CA, and reviews of other applicants, which
  speed up one's own.

## Verification

- [ ] `just validate` passes after key generation.
- [ ] `sbverify --cert files/boot-keys/DB.crt <uki>` passes on built UKIs.
- [ ] `gpgv --keyring files/boot-keys/import-pubring.pgp SHA256SUMS.gpg SHA256SUMS` passes.
- [ ] No private keys are committed outside the gitignored `files/boot-keys/`,
      except the public INSECURE dev module key in `files/dev-keys/`.
- [ ] `bash scripts/check-release-keys.sh` passes on a release key set.
- [ ] `just bst build bluefin-server/shim.bst` passes (its vendor certificate,
      SBAT and signature checks run in the element).

## See also

- [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md) —
  manifest signing and sysupdate trust model.
- [ddi-installer-build.md](ddi-installer-build.md) — local build and dogfood
  workflow.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary.
