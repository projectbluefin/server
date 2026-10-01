---
name: booty-integration
description: How Booty serves Bluefin Server releases to nodes. Load when working on HTTP boot, iPXE chainloading, per-node Ignition, or kubeadm worker provisioning.
metadata:
  type: reference
  status: stable
  last_updated: "2026-09-30"
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
  with `gpgv` against the import keyring (the `/etc/systemd/import-pubring.pgp`
  override, else the image's `/usr/lib/systemd/import-pubring.pgp`: the same
  root as the image pull), then stages the verified bytes inline at
  `/run/ignition/user.ign`, so Ignition applies exactly what was signed. The
  signature is the gate, not the transport: plain `http://` works, as it does
  for the `/usr` pull. A keyring that cannot be read (say, a dangling `/etc`
  symlink) fails the boot; the other one is never tried instead.
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

### Transitional: unsigned configs on netboot

Booty does not sign `bluefin-node.ign` yet; it answers 404 for the `.gpg`. A
UEFI HTTP Boot node with Secure Boot has no other way to receive the opt-out
credential: the signed UKI's own command line wins, there is no ESP for
`/loader/credentials`, and real firmware sets no SMBIOS type 11 strings. So
the netboot UKI carries it on its command line,
`systemd.set_credential=bluefin.ignition.allow-unsigned:1` (`netboot-cmdline`
in `elements/oci/bluefin-server-boot.bst`); the disk and installer UKIs do
not. Booty's iPXE chainload and BIOS paths boot with the UKI's own `.cmdline`,
rewriting only the `rd.systemd.pull` URL, so they carry it too.

Booty-provisioned nodes keep applying their per-node config, and a bad
signature or a `.gpg` failure other than 404 still fails closed. This is not
yet protection against an on-path attacker, who can answer 404 for the `.gpg`
to force the unsigned path. The default goes away once Booty signs each
node's config with a dedicated config key, trusted in the initrd separately
from the release key that signs `SHA256SUMS`
([#327](https://github.com/projectbluefin/server/issues/327), following #284).

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

## Complete profile boundary

The existing Booty netboot/DDI and external kubeadm-worker paths retain their
current behavior. Syncing a newer release is not permission to initialize a
Complete controller or switch an established node's profile/role. Do not
activate the old `kubeadm` or k0s provider alongside Complete's selected Flatcar
runtime images.

Authenticated provisioning that selects Complete must deliver the same
signed profile and coherent module inventory as the native installer, with
persistent `/etc` and `/var`. Worker enrollment is private and one-use; never
put its join token in public HTTP Ignition, generic media or discovery output.
The appliance path is [the USB installer](usb-installer.md) with privately
delivered worker provisioning, not the removed fork's Add Node UI. This repository does not add or promise a
new upstream Booty profile flag; verify a provisioner's authenticated delivery
support before using it for Complete. Identity/role rules are canonical in
[server-profile.md](server-profile.md).


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
