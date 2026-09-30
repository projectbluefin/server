---
name: systemd-sysupdate-verification
description: Configure and operate GPG signature verification for Bluefin Server's systemd-sysupdate OTA updates from GitHub Releases.
metadata:
  type: reference
  status: stable
  last_updated: "2026-09-28"
  context7-sources:
    - /systemd/systemd
---
# systemd-sysupdate Signature Verification

Use this skill when working on Bluefin Server's over-the-air update mechanism,
specifically the transfer files, release signing, or public keyring shipped in
the OS image.

## When to Use

- Modifying `files/os/sysupdate.d/*.transfer` (including the `zfs` and
  `kubestellar` feature transfers) or the k0s component directory
  (`files/os/sysupdate.k0s.d/`).
- Rotating or replacing the image signing key.
- Debugging `systemd-sysupdate` or diskless `rd.systemd.pull` failures related
  to `SHA256SUMS.gpg` verification.
- Verifying a published release: provenance attestations and the SBOM.

## When NOT to Use

- General BuildStream element or dependency questions (use `avoid-over-engineering` or `ddi-installer`).
- CI job wiring, permissions and action pins (use `ci-tooling`).

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
- The public keyring is `/etc/systemd/import-pubring.pgp` when it exists, and
  the vendor keyring `/usr/lib/systemd/import-pubring.pgp` otherwise. The old
  `.gpg` paths were never read by systemd; nothing in the tree installs them.

## Current implementation status

Installed nodes carry A/B usr and usr-verity slots plus matching UKIs. The usr
and usr-verity transfers live in `sysupdate.d` and fill the inactive slot; the
UKI transfer installs the new disk UKI into `/EFI/Linux` with boot counting
(`TriesLeft=3`), so a failed image rolls back to the previous slot on its own.
The optional OpenZFS and KubeStellar sysexts are version-locked to the image
and follow OS updates through the optional `zfs` and `kubestellar` sysupdate
**features** (`files/os/sysupdate.d/zfs.feature`, `kubestellar.feature`,
`30-zfs.transfer`, `31-kubestellar.transfer`), enabled per node with
`updatectl enable zfs` or a drop-in such as
`/etc/sysupdate.d/zfs.feature.d/enable.conf` containing `[Feature] Enabled=true`.
The automatic update service runs `bluefin-sysupdate-feature-guard` before staging
an OS update: if both `zfs` and `nvidia-open-595` are enabled, it refuses the
update, because both sysexts supply kernel `modules.*` indexes. Disable one
with `updatectl disable` before retrying. `updatectl enable` only writes a
feature drop-in; it does not validate conflicts. Direct invocations of
`systemd-sysupdate update` bypass the service preflight, so operators must not
stage both features manually. The boot-time NVIDIA guard remains a last-resort
check for images staged outside the service.
Only the k0s sysext stays a separate component
(`files/os/sysupdate.k0s.d/`, `systemd-sysupdate --component=k0s update`) with
its own version axis. Diskless nodes update by rebooting into a newer
image; `systemd-sysupdate.service` is disabled when booted diskless.
Update scheduling, the kured flag, and the boot health gate are covered in
[ddi-installer.md](ddi-installer.md) under "Updates".

The diskless update check (`bluefin-diskless-update-check`) uses the same trust
root: it trusts a newer release only after `gpgv` verifies the boot server's
`SHA256SUMS.gpg` against the keyring systemd reads
(`/etc/systemd/import-pubring.pgp`, else the vendor keyring). An unsigned or
foreign-signed manifest never sets `/run/reboot-required`.

## Signing happens inside the image build

`oci/bluefin-server-image.bst` assembles the whole release set (OS images,
UKIs, netboot ESP, and the k0s/KubeStellar/OpenZFS sysext assets), writes one
combined `SHA256SUMS` over all of it, and signs it in-element with
`files/boot-keys/sysupdate-signing.asc` (gpg `--detach-sign`). It then proves
the shipped keyring accepts the signature with
`gpgv --keyring /boot-keys/import-pubring.pgp SHA256SUMS.gpg SHA256SUMS`, so a
key mismatch fails the build instead of breaking nodes in the field. There is
no separate CI signing step: a release publishes `dist/diskless/` as-is.

`elements/bluefin-server/os-sysupdate-keys.bst` installs the matching public
keyring from `files/boot-keys/import-pubring.pgp` to
`/etc/systemd/import-pubring.pgp`. systemd reads that path before the vendor
`/usr/lib/systemd/import-pubring.pgp` that FSDK ships, so the image trusts
exactly the key that signed the build.

The diskless pull verifies the same signature: the initrd ships gnupg and the
keyring (`bluefin-server/initrd/initrd-stack.bst` depends on
`os-sysupdate-keys.bst`), and the netboot UKI pulls the OS DDI with
`verify=signature`. `systemd-importd` fetches `SHA256SUMS` and
`SHA256SUMS.gpg` from the same directory as the image and refuses a tampered
DDI and a re-hashed, unsigned manifest alike (`DOGFOOD_TAMPER=raw|sums`
proves both).

## Provenance, SBOM and publishing

The GPG signature is what nodes check. On top of it, every release carries
GitHub artifact attestations (SLSA build provenance, signed keylessly through
Sigstore with the `build.yml` workflow identity on `refs/heads/main`) that
tell a human or a policy engine which commit and workflow run produced it.

- **SBOM.** `oci/bluefin-server-sbom.bst` runs FSDK's `collect_manifest`
  plugin (`output-type: spdx`) over the payload of the release set: the /usr
  and initrd stacks, the kernel, and the k0s, KubeStellar, kubeadm and
  OpenZFS sysext payloads. It lists one SPDX package per source (name,
  version, download URL, source kind). Build-only elements such as the
  signing keys are not runtime dependencies of that payload and never
  appear. SPDX requires a `creationInfo.created`, which the plugin leaves to
  the build, so the image element stamps it from `SOURCE_DATE_EPOCH`. The
  build runs in a BuildStream sandbox that fixes `SOURCE_DATE_EPOCH` to
  BuildStream's own default (1321009871), so the field always reads
  `2011-11-11T11:11:11Z`: it is a reproducibility placeholder, not a build
  time. Use the SLSA provenance attestation (or the release tag) for when a
  set was built. The SBOM ships as `bluefin-server_<ver>.spdx.json`, listed
  in `SHA256SUMS`, so the GPG signature covers it too. No transfer matches
  it, so nodes never download it.
- **Publishing.** In CI, `scripts/publish-release.sh` is the only publish
  path (`just publish-oci` pushes to a local or personal registry for
  rehearsal and runs none of the script's checks).
  `verify` checks what nodes will check (`gpgv` against the keyring, every
  `SHA256SUMS` entry present and matching), plus: every published file is
  listed, every file name carries the release version, and the SBOM is valid
  SPDX 2.3. `release` creates the GitHub Release at the built commit. `oci`
  pushes the ORAS artifact, then checks the registry manifest layer by layer
  against the local files. On main the `release` job verifies against the
  committed `files/os/sysupdate-keys/import-pubring.gpg`. On pull requests
  `release-dry-run` verifies against the throwaway keyring the build
  exported in `sysupdate-keys/`, prints the `gh release create` command, and
  pushes to a local registry and pulls the artifact back.
- **Attestations.** The `release` job runs `actions/attest` four times:
  provenance and SBOM for every published file (subjects are the verified
  checksums), and provenance and SBOM for the OCI artifact digest with
  `push-to-registry: true`, which stores the Sigstore bundles next to the
  artifact as OCI referrers. That bundle is the registry signature. A
  separate `cosign sign` would only repeat the same workflow identity, so
  there is none.

Verify a downloaded file, or the OCI artifact, with the GitHub CLI:

```bash
gh attestation verify bluefin-server_<ver>.raw --repo projectbluefin/server \
  --signer-workflow projectbluefin/server/.github/workflows/build.yml --source-ref refs/heads/main
gh attestation verify bluefin-server_<ver>.raw --repo projectbluefin/server \
  --predicate-type https://spdx.dev/Document/v2.3
gh attestation verify oci://ghcr.io/projectbluefin/bluefin-server:<ver> \
  --repo projectbluefin/server --bundle-from-oci
```

Or with cosign, against the referrers stored in the registry:

```bash
cosign verify-attestation --new-bundle-format --type slsaprovenance1 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity 'https://github.com/projectbluefin/server/.github/workflows/build.yml@refs/heads/main' \
  ghcr.io/projectbluefin/bluefin-server@sha256:<digest>
```

Use `--type spdxjson` to get the SBOM attestation instead.

## Repository Layout

- `files/os/sysupdate-keys/import-pubring.gpg` — the release public keyring,
  committed. On release builds CI copies it to
  `files/boot-keys/import-pubring.pgp`.
- `files/boot-keys/sysupdate-signing.asc` / `import-pubring.pgp` — the signing
  key and public keyring for a build (gitignored). Where they come from
  locally and in CI: [secure-boot-keys.md](secure-boot-keys.md).
- `elements/bluefin-server/os-sysupdate-keys.bst` — installs
  `files/boot-keys/import-pubring.pgp` as `/etc/systemd/import-pubring.pgp`.
- `files/os/sysupdate.d/*.transfer` and the k0s component directory
  (`files/os/sysupdate.k0s.d/`) — each transfer points its static `Path=` at
  `https://github.com/projectbluefin/server/releases/latest/download/` so all
  transfers share the same signed manifest.

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
   gpg --export --output files/os/sysupdate-keys/import-pubring.gpg "$KEYID"
   gpg --export-secret-keys --armor "$KEYID" > /secure/offline/backup.asc
   rm -rf "$GNUPGHOME"
   ```
2. Update the GitHub Actions repository secret `SYSUPDATE_SIGNING_KEY` with the
   new ASCII-armored private key.
3. Rebuild and publish a release under a new `image-version` (a key rotation
   is never a rebuild of an existing version; see
   "Keys" in [ddi-installer-build.md](ddi-installer-build.md)). Existing hosts only
   trust updates signed by the key in their keyring, so plan the rotation
   around a release boundary.

For a throwaway local signing key, `just gen-dev-keys` writes the pair on its
own; see [secure-boot-keys.md](secure-boot-keys.md).

## Common Gotchas

- **Do not put `@v` in `[Source] Path=`.** `Path=` must be a static base URL.
  `systemd-sysupdate` fetches `<Path>/SHA256SUMS` (+ `.gpg`) as the version
  manifest, then matches filenames containing `@v` through `MatchPattern=`.
  A path like `.../releases/download/@v/` will produce a 404 and break version
  discovery for every transfer.
- **One combined manifest per release set.** All transfers share the same
  `Path=` and therefore the same `SHA256SUMS` file. The manifest is written
  and signed inside `oci/bluefin-server-image.bst`, covers every file in
  `dist/diskless/` (OS images, UKIs, and the sysext `.raw.zst` assets), and
  the release publishes that directory as-is. There is no second manifest.
- **`Verify=` belongs to `[Transfer]`, not `[Source]`.** It defaults to `yes`;
  no transfer in the tree overrides it.
- **Testing the trust chain locally.** `scripts/dogfood-diskless.sh` already
  exercises it: the netboot UKI pulls with `verify=signature`, and
  `DOGFOOD_TAMPER=raw` / `DOGFOOD_TAMPER=sums` prove a tampered DDI and a
  re-hashed, unsigned manifest are both refused. For an installed-node run,
  `scripts/dogfood-install.sh` updates with the default `Verify=yes` against a
  locally served image set signed by the dev key.

## Verification

- [ ] `files/os/sysupdate.d/*.transfer` and `files/os/sysupdate.k0s.d/` do not
      contain `Verify=no`.
- [ ] `elements/bluefin-server/os-stack.bst` and
      `elements/bluefin-server/initrd/initrd-stack.bst` include
      `bluefin-server/os-sysupdate-keys.bst`.
- [ ] `files/os/sysupdate-keys/import-pubring.gpg` (release) or
      `files/boot-keys/import-pubring.pgp` (dev) contains the public half of
      the key that signs the build.
- [ ] `oci/bluefin-server-image.bst` signs the combined `SHA256SUMS` and
      proves it with `gpgv` against the keyring the image ships.
- [ ] CI publishes `dist/diskless/` as-is to the GitHub Release and to the
      OCI artifact; there is no separate signing step.
- [ ] Every publish command in `build.yml` goes through
      `scripts/publish-release.sh`, and `release-dry-run` runs the same
      `verify`, `release --dry-run` and `oci` commands on pull requests.
- [ ] `bluefin-server_<ver>.spdx.json` is listed in `SHA256SUMS`.
- [ ] Every transfer in `files/os/sysupdate.d/*.transfer` and the k0s
      component directory uses a static `Path=` with no `@v` placeholder.
- [ ] Every transfer uses `@v` only inside `MatchPattern=`.

## See also

- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary (Transfer definition).
- `systemd-sysupdate(8)`, `sysupdate.d(5)`
