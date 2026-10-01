---
name: systemd-sysupdate-verification
description: Configure and operate GPG signature verification for Bluefin Server's systemd-sysupdate OTA updates from GitHub Releases.
metadata:
  type: reference
  status: stable
  last_updated: "2026-09-30"
  context7-sources:
    - /systemd/systemd
---
# systemd-sysupdate Signature Verification

Use this skill when working on Bluefin Server's over-the-air update mechanism,
specifically the transfer files, release signing, or public keyring shipped in
the OS image.

## When to Use

- Modifying `files/os/sysupdate.d/*.transfer` (including the `zfs`,
  `kubestellar`, `kubeadm` and `nvidia-open-595` feature transfers) or a
  component directory (`files/os/sysupdate.k0s.d/`,
  `files/os/sysupdate.nvidia-container-toolkit.d/`).
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
The optional OpenZFS, KubeStellar, kubeadm and NVIDIA driver sysexts are
version-locked to the image and follow OS updates through the optional `zfs`,
`kubestellar`, `kubeadm` and `nvidia-open-595` sysupdate **features**
(`files/os/sysupdate.d/<name>.feature` and `3N-<name>.transfer`), enabled per
node with `updatectl enable zfs` or a drop-in such as
`/etc/sysupdate.d/zfs.feature.d/enable.conf` containing `[Feature] Enabled=true`.
The k0s and NVIDIA Container Toolkit sysexts stay separate components
(`files/os/sysupdate.k0s.d/`, `files/os/sysupdate.nvidia-container-toolkit.d/`;
`systemd-sysupdate --component=<name> update`) with their own version axes.
Diskless nodes update by rebooting into a newer
image; `systemd-sysupdate.service` is disabled when booted diskless.
Update scheduling, the kured flag, and the boot health gate are covered in
[ddi-installer.md](ddi-installer.md) under "Updates".

The diskless update check (`bluefin-diskless-update-check`) uses the same trust
root: it trusts a newer release only after `gpgv` verifies the boot server's
`SHA256SUMS.gpg` against the keyring systemd reads
(`/etc/systemd/import-pubring.pgp`, else the vendor keyring). An unsigned or
foreign-signed manifest never sets `/run/reboot-required`.

## Complete runtime generations

Complete opts into the `server` feature. `34-server-bundle.transfer` downloads
`server-bundle_<ver>.tar.zst` as one verified directory under
`/var/lib/bluefin/server/runtime/incoming/<ver>`. Downloading an OS or bundle
never switches active Kubernetes/containerd binaries.

The bundle contains an inner signed `SHA256SUMS` for `profile.json`, the Server
support extension and unchanged pinned Flatcar runtime images. The profile
launcher/root lifecycle verifies its signature and exact member hashes before
staging a protected generation. Application images are upstream registry pulls.
The embedded bundle signature uses a fixed signing epoch: the maximum of
`SOURCE_DATE_EPOCH` and the imported signing key/subkey creation timestamps.
The `--faked-system-time` value ends in `!` to freeze, rather than offset, its
clock while signing. Slow input must not advance the embedded timestamp.
For the RSA release key this keeps bundle/installer signature bytes repeatable
without creating a signature earlier than its key. This is not an upstream
container publisher attestation or a wall-clock build timestamp.
Only selected stable links enter `/var/lib/extensions`; retained payloads stay
outside extension merge-search paths. Active, previous and in-flight versions
are protected explicitly with one `ProtectVersion=` line per version; spaces
inside a single value are not a version list. Five transfer slots include the
booted OS and next candidate.
The pinned systemd `261.2` parser appends each value with `strv_extend`; vacuum
tests every retained value with `strv_contains`, not just the last line.
Its transfer loader merges `34-server-bundle.transfer.d/*.conf` drop-ins.
Retention validation must exercise that layout: `%A` in the main transfer,
active/previous/in-flight values in `protect.conf`, and a real vacuum that
preserves every protected instance. A main-file-only fixture is insufficient.
Source: [pinned transfer parser](https://github.com/systemd/systemd/blob/4925d9f07fc697efccd98a93046ff535b8832445/src/sysupdate/sysupdate-transfer.c).

A root-authorized native lifecycle request selects a signed image-version transition. The
root helper checks supported actual worker skew, snapshots etcd before a
controller version transition, performs native kubeadm migration, restarts
containerd before kubelet and checks actual readiness plus a fresh pod sandbox.
An OS rollback is not an etcd restore or permission to downgrade a migrated
runtime. Durable stages resume with the generation appropriate to that stage.

A healthy controller commits its own transition independently of registered
workers. Other nodes require manual per-node signed runtime updates; status
records that requirement without pretending they were updated. It does not
permanently block the next controller transition on a removed browser updater.
Stock Console has no custom upgrade/pairing UI. Native role and actual Kubernetes
skew preflight remain authoritative; no worker is silently deleted or adopted.

## Signing happens inside the image build

`oci/bluefin-server-image.bst` assembles the whole release set (OS images,
UKIs, netboot ESP, Complete runtime/optional stock Console/coherent bundle,
and the k0s, KubeStellar, kubeadm, OpenZFS, NVIDIA driver and NVIDIA Container
Toolkit sysext assets), writes one combined `SHA256SUMS` over all of it, and
signs it in-element with
`files/boot-keys/sysupdate-signing.asc` (gpg `--detach-sign`). It then proves
the shipped keyring accepts the signature with
`gpgv --keyring /boot-keys/import-pubring.pgp SHA256SUMS.gpg SHA256SUMS`, so a
key mismatch fails the build instead of breaking nodes in the field. There is
no separate CI signing step: a release publishes `dist/diskless/` as-is.

`elements/bluefin-server/os-sysupdate-keys.bst` installs the matching public
keyring from `files/boot-keys/import-pubring.pgp` to
`/usr/lib/systemd/import-pubring.pgp`, replacing FSDK's vendor keyring. A
runtime dependency on FSDK's systemd orders the replacement, and a narrow
BuildStream overlap whitelist permits that file alone. Both the OS and initrd
therefore trust the build keyring. The OS keyring lives on the immutable `/usr`
image, so A/B updates and rollbacks change it with the image. It is not copied
into persistent `/etc` by factory tmpfiles rules.

`/etc/systemd/import-pubring.pgp` remains an operator override and takes
precedence over the image keyring. Nodes installed before this change retain
the old factory copy there. After booting an image containing this fix, inspect
that file and the vendor keyring; if it is only the old factory copy, back it up
outside systemd's keyring paths and remove it to follow the image keyring.
Preserve intentional operator overrides. There is no automatic deletion,
since an old factory copy cannot reliably be distinguished from an override.

A dev-installed node still cannot authenticate its first official update with
a dev key. Provision the authenticated release public keyring as an `/etc`
override through a trusted administrative channel for that transition; after
booting the official image with this fix, remove the temporary override to
follow its vendor keyring. Do not disable signature verification.

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

  Complete merges the stock platform's SPDX fragment for actual upstream
  source/resources/image pins with the BuildStream SBOM by SPDX identity.
  There is no custom Console/Argo source or npm/toolchain provenance to claim.
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
  `files/boot-keys/import-pubring.pgp` as `/usr/lib/systemd/import-pubring.pgp`.
- `files/os/sysupdate.d/*.transfer` and the component directories
  (`files/os/sysupdate.k0s.d/`, `files/os/sysupdate.nvidia-container-toolkit.d/`)
  — each transfer points its static `Path=` at
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
   gpg --export --output /secure/offline/new-public.pgp "$KEYID"
   gpg --export-secret-keys --armor "$KEYID" > /secure/offline/backup.asc
   rm -rf "$GNUPGHOME"
   ```
2. Combine the existing release public keys with `/secure/offline/new-public.pgp`
   in `files/os/sysupdate-keys/import-pubring.gpg`. Before switching signers,
   ship a bridge release carrying this combined vendor keyring, signed by the
   **old** private key. Keep `SYSUPDATE_SIGNING_KEY` unchanged for that release. Ensure nodes
   have booted it and any legacy `/etc` factory copies have been migrated as
   described above before proceeding. Nodes that skip the bridge need their
   trust provisioned through a trusted administrative channel.
3. Update the GitHub Actions repository secret `SYSUPDATE_SIGNING_KEY` with the
   new ASCII-armored private key.
4. Rebuild and publish a release under a new `image-version` (a key rotation
   is never a rebuild of an existing version; see
   "Keys" in [ddi-installer-build.md](ddi-installer-build.md)). Existing hosts only
   trust updates signed by the key in their keyring, so plan the rotation
   around a release boundary. Retire the old public key in a later image
   only after the transition is complete.

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

- [ ] `files/os/sysupdate.d/*.transfer` and the `files/os/sysupdate.*.d/`
      component directories do not contain `Verify=no`.
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
