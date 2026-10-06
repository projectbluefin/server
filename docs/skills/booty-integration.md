---
name: booty-integration
description: How Booty serves Bluefin Server releases to nodes. Load when working on HTTP boot, iPXE chainloading, per-node Ignition, or kubeadm worker provisioning.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-05"
---
# Booty Integration

[Booty](https://github.com/jeefy/booty) is the network boot server for Bluefin
Server at scale. It syncs a release and answers boot requests with the right
artifacts per node.

## What Booty serves

From a release `v<ver>` (GitHub Releases or the ORAS OCI artifact at
`ghcr.io/projectbluefin/bluefin-server:<ver>,latest`) Booty syncs the netboot
UKI `bluefin-server-netboot_<ver>.efi`, the OS DDI `bluefin-server_<ver>.raw`,
`SHA256SUMS` and `SHA256SUMS.gpg`, and any listed sysext assets
(`zfs_<ver>.raw.zst`, `kubestellar_<ver>.raw.zst`, `kubeadm_<ver>.raw.zst`,
`nvidia-open-<branch>_<ver>.raw.zst`, `k0s-<k0s-ver>.raw.zst`,
`nvidia-container-toolkit-<ctk-ver>.raw.zst`), verifies them against
`SHA256SUMS` (and, with `--bluefinKeyring`, against the GPG signature), and
serves them over plain HTTP. The netboot ESP image, the disk UKI and the USB
installer are not synced; they are for booting without Booty.

## Boot paths

| Firmware | Path |
|---|---|
| UEFI HTTP Boot | Firmware fetches `http://<booty>/bluefin/<mac>/bluefin-server-netboot.efi`; Secure Boot on. |
| iPXE chainload | UEFI firmware without HTTP Boot PXE-boots iPXE, which chainloads the netboot UKI with an explicit `rd.systemd.pull` URL; Secure Boot off. |
| Legacy BIOS | BIOS iPXE boots the UKI's kernel and initrd sections directly, diskless only; no install, no sysupdate, no boot counting (those need UEFI). |

## Per-node configuration

Booty renders a `bluefin-node.ign` (Ignition spec 3.6.0) per MAC address and
serves it next to the UKI. Fields include hostname, SSH keys (which also
enable `sshd.service`, disabled by preset in the image), state disk,
extensions (any of `zfs`, `kubestellar`, `k0s`, `nvidia-container-toolkit`,
and at most one NVIDIA driver flavour `nvidia-open-<branch>`, which combines
with `zfs`), and a k0s token. The image-locked extensions land in
`/etc/extensions/<name>_<ver>.raw` and the toolkit in
`/etc/extensions/nvidia-container-toolkit.raw`, so they merge at boot. Booty's
NVIDIA rules are in the Booty README's
[NVIDIA GPU hosts](https://github.com/jeefy/booty#nvidia-gpu-hosts).

A node with no `ignition.config` / `ignition.config.url` credential HEADs
`bluefin-node.ign` next to its boot origin. Nothing there means nothing to
apply. If it is there, `bluefin-ignition-credentials` in the initrd applies it
only if it is signed:

- It fetches `bluefin-node.ign.gpg` from the same directory and verifies it
  with `gpgv` against the Ignition config keyring
  `/usr/lib/bluefin/ignition-pubring.pgp`, which lives only in the initrd,
  inside the signed UKI. That keyring is the only trust root for node configs:
  the release keyring (`import-pubring.pgp`, which authenticates
  `SHA256SUMS`) is never consulted, so a release signature does not verify as
  a node config, and whoever signs node configs cannot sign releases. There is
  no `/etc` override. The node then stages the verified bytes inline at
  `/run/ignition/user.ign`, so Ignition applies exactly what was signed. The
  signature is the gate, not the transport: plain `http://` works, as it does
  for the `/usr` pull. A keyring that cannot be read fails the boot.
- Only an HTTP 404 on the `.gpg` counts as "unsigned". An unsigned config is
  applied only with the system credential `bluefin.ignition.allow-unsigned`
  (any non-empty value), and is logged as `UNAUTHENTICATED`. Any other failure
  fetching the `.gpg` (5xx, timeout, dropped connection), or a signature that
  does not verify, fails the boot into emergency mode with or without the
  credential (`bluefin-ignition-credentials.service` has
  `OnFailure=emergency.target`); the unit's journal carries `gpgv`'s reason.
- A signed config must be self-contained. Ignition fetches
  `ignition.config.merge` / `replace` targets and remote
  `storage.files[].contents.source` URLs without checking them against any
  signature, so each such source needs a `verification.hash`.

### The Ignition config key

| Build | `ignition-pubring.pgp` in the initrd | Secret key |
|---|---|---|
| Release | `files/release-keys/ignition-pubring.pgp` (committed; CI copies it in) | held by whoever signs node configs for the project's images; never in CI or a build |
| Pull request, nightly, local | a dev key from `just gen-dev-keys` | `files/boot-keys/ignition-signing.asc` (gitignored) |

`scripts/check-ignition-keys.sh` runs on every CI key set: the keyring must
be there and share no key with `import-pubring.pgp`; on releases it must be
the committed one, with no Ignition secret key in the build. A release build
without `files/release-keys/ignition-pubring.pgp` fails.

A site that signs its own node configs (Booty included) needs its public key
in the image's keyring: there is no other way to deliver a trust root to a
UEFI HTTP Boot node with Secure Boot. Either sign with the project's config
key, or build the image with your key set (`files/boot-keys/` with your own
`ignition-pubring.pgp`, the same way as the Secure Boot keys).

**Signing.** Sign exactly the bytes served as `bluefin-node.ign`, after any
templating, as a binary detached signature, and serve it as
`bluefin-node.ign.gpg` in the same directory:

```bash
scripts/sign-node-config.sh ignition-signing.asc bluefin-node.ign   # writes bluefin-node.ign.gpg
# equivalently, with the key in a keyring: gpg --local-user <fpr> --detach-sign bluefin-node.ign
```

Re-sign whenever the config changes; a stale `.gpg` over new bytes is a bad
signature and stops the node. Mark a node provisioned only once it has booted
past the initrd, not when it fetched the UKI: a refused config fails that boot.

**Rotation.** `gpgv` accepts a signature from any key in the keyring, so
rotate by overlap: add the new public key to `ignition-pubring.pgp` (export
both keys into one keyring), ship an image, move the signer to the new key,
and drop the old key from the keyring in a later image. Removing a key
revokes it for every node that boots an image without it. Each change needs a
new image version, as for the other keys
([secure-boot-keys.md](secure-boot-keys.md)).

### Transitional: unsigned configs on netboot

Booty does not sign `bluefin-node.ign` yet; it answers 404 for the `.gpg`. A
UEFI HTTP Boot node with Secure Boot has no other way to receive the opt-out
credential: the signed UKI's own command line wins, there is no ESP for
`/loader/credentials`, and real firmware sets no SMBIOS type 11 strings. So
while the build option `ignition_allow_unsigned` (`project.conf`, default
`True`) is on, the netboot UKI carries
`systemd.set_credential=bluefin.ignition.allow-unsigned:1` on its command line
(`netboot-ignition-cmdline` in `elements/oci/bluefin-server-boot.bst`); the
disk and installer UKIs never do. Booty's iPXE chainload and BIOS paths boot
with the UKI's own `.cmdline`, rewriting only the `rd.systemd.pull` URL, so
they carry it too.

Booty-provisioned nodes keep applying their per-node config, and a bad
signature or a `.gpg` failure other than 404 still fails closed. This is not
yet protection against an on-path attacker, who can answer 404 for the `.gpg`
to force the unsigned path.

**Cut-over** ([#327](https://github.com/projectbluefin/server/issues/327)):
set `default: False` on `ignition_allow_unsigned` once all of these hold:

1. Booty signs every `bluefin-node.ign` it serves, byte for byte, with a key
   in the release image's `ignition-pubring.pgp`, and serves the `.gpg` next
   to it.
2. A Booty release that does so is out, and deployments that serve configs
   to project images run it (an older Booty's nodes stop at emergency mode).
3. The `full-build` boot test's signed-config steps pass, and the plain
   "UEFI HTTP boot with bluefin-node.ign" step serves a signed config instead
   of an unsigned one.

Then drop this section and the default's unit test. CI already builds the
next update-test image set with the option off
(`BST_FLAGS="-o ignition_allow_unsigned False"`) and proves its netboot UKI
refuses an unsigned config; a local build can do the same.

## Install to disk

Setting `doInstall` in the node's Booty config boots it into
`booty-install.service`, which runs `systemd-sysinstall` against the local
disk. Without Booty, write `bluefin-server-netboot_<ver>.esp.raw` to a USB
stick and place an `import.pull.cred` credential in `/loader/credentials/`
specifying the URL to pull.

## kubeadm workers

A Bluefin host joins a kubeadm cluster when Booty is run with
`--profile=kubeadm-worker` against an external cluster: its `bluefin-node.ign`
then carries the release's `kubeadm` sysext (version-locked, see
[kubeadm-sysext.md](kubeadm-sysext.md)), enables `containerd.service` and
`kubelet.service`, and runs `kubeadm join` on every diskless boot. `kubeadm`
is not one of the host's selectable `extensions`; Booty adds it for the
profile. How Booty renders and serves this lives in the Booty README; the
sysext's contents and runtime contract live in
[kubeadm-sysext.md](kubeadm-sysext.md).

## Read more

- [Booty README](https://github.com/jeefy/booty) — flags, config file layout,
  and the operator-side boot and provisioning story.
- [ddi-installer.md](ddi-installer.md) — boot flow, DDI layout, and sysinstall
  contract.
- [kubeadm-sysext.md](kubeadm-sysext.md) — worker sysext build and runtime
  contract.

## See also

- [index.md](index.md) — lazy-load routing manifest.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary.
