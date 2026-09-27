---
name: secure-boot-signing
description: How Bluefin Server release artifacts are Authenticode-signed for UEFI Secure Boot, which key signs what, how to enrol the project certificate, and how to rotate the key.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-09-26"
---
# Secure Boot signing

## When to load this skill

- A Secure Boot machine refuses the installer, the PXE kernel, or the installed
  system (`/EFI/Linux/bluefin-server.efi`, `systemd-boot`).
- Changing `scripts/sign-secureboot-artifacts.sh` or the `Sign Secure Boot
  artifacts` step in `.github/workflows/build.yml`.
- Generating, rotating, or publishing the project Secure Boot certificate.
- Do **not** load for GPG signing of `SHA256SUMS` (that is
  [`systemd-sysupdate-verification.md`](systemd-sysupdate-verification.md)).

## Trust model

Bluefin Server has no Microsoft-signed shim (shim-review with the project
certificate as vendor cert is the long-term path; Fedora CoreOS has it, Flatcar
is still blocked on it). Every PE binary a Secure Boot firmware executes is therefore
signed with **one project db key**, and operators enrol its certificate in the
firmware `db` (or a PXE server serves it for enrolment). Without the
certificate enrolled, Secure Boot must be **disabled** — the failure mode is
otherwise a machine that installs successfully and then will not boot.

| Artifact | Where it boots | Signature |
|---|---|---|
| `bluefin-server-<flatcar-version>.efi` (target UKI) | installed ESP `/EFI/Linux/`, also the `systemd-sysupdate` transfer | project key |
| `systemd-bootx64.efi` inside the installer initrd | copied to the installed ESP by `bootctl install` | project key |
| `bluefin-server.efi` inside the installer initrd | `systemd-sysinstall --kernel=`, copied to the installed ESP | project key (same file as the target UKI) |
| `EFI/BOOT/BOOTX64.EFI` on the installer media | boots the installer from USB | project key |
| `bluefin-server-pxe-vmlinuz-<installer-version>` | PXE/HTTP boot | project key (Flatcar development signature stripped) |
| `bluefin-server-pxe-initrd-<installer-version>.cpio.gz` | PXE/HTTP boot | not a PE; carries the signed UKI and `systemd-boot` |

The certificate is published with every release as
`bluefin-server-secureboot.der` (for firmware and PXE enrolment) and
`bluefin-server-secureboot.pem`, and is also placed at the root of the
installer media ESP so a firmware "enrol from file" dialog can find it.

## How signing works

BuildStream builds are hermetic, so the key never enters the element graph.
`elements/oci/bluefin-server-installer.bst` produces **unsigned** binaries;
`scripts/sign-secureboot-artifacts.sh` signs them afterwards in the CI `build`
job, right after `just export-pxe` and before the installer boot test, so the
boot-tested artifacts are the signed ones.

The script, in order:

1. `sbsign`s the exported target UKI in place.
2. Signs `usr/lib/systemd/boot/efi/systemd-bootx64.efi` (extracted from the
   PXE initrd) and packs it plus the signed target UKI into a small root-owned
   overlay cpio that is **appended** to the initrd. The kernel unpacks
   concatenated (individually compressed) cpio archives in order and later
   members overwrite earlier ones, so the initrd is never repacked and no root
   privileges are needed.
3. Rebuilds the installer UKI on the installer media ESP with `ukify`, reusing
   the built UKI's own `.linux`, `.cmdline` and `.osrel` sections and the
   initrd from step 2, signs it, and writes it back into the raw image with
   `mcopy`; the ESP is located by GPT partition type, never by index.
4. Strips the Flatcar development signature from the PXE kernel with
   `sbattach --remove` and re-signs it.

Every output is checked with `sbverify --cert` before the script exits.

## CI configuration

Two repository secrets, both PEM:

| Secret | Content |
|---|---|
| `SECUREBOOT_SIGNING_KEY` | RSA private key |
| `SECUREBOOT_SIGNING_CERT` | self-signed X.509 certificate for that key |

The step runs only on pushes to `main` (the `build` job executes PR-controlled
code, so the key must never be present in a `pull_request` run) and exits with
a workflow warning when the secrets are unset — the release is then published
unsigned, exactly as before this step existed.

Runner packages installed by the step: `sbsigntool systemd-ukify mtools cpio`.

## Generating or rotating the key

```sh
openssl req -new -x509 -newkey rsa:4096 -nodes -sha256 -days 3650 \
  -subj "/CN=Bluefin Server Secure Boot Signing/" \
  -keyout secureboot-db.key -out secureboot-db.pem
gh secret set SECUREBOOT_SIGNING_KEY  < secureboot-db.key
gh secret set SECUREBOOT_SIGNING_CERT < secureboot-db.pem
```

Store the private key offline; only the certificate is public. Rotating the key
means machines with only the old certificate enrolled will refuse the next
UKI delivered by `systemd-sysupdate`, so publish the new `.der` one release
ahead and tell operators to enrol both.

## Enrolling the certificate

- **Firmware:** boot the installer media, open the firmware Secure Boot key
  management, and enrol `bluefin-server-secureboot.der` from the ESP root into
  `db` (or add it to a custom-mode key set alongside your PK/KEK).
- **PXE / HTTP boot servers:** serve the `.der` from the release so clients can
  enrol it the same way they enrol Flatcar's CA.
- **Verify locally:** `sbverify --cert bluefin-server-secureboot.pem <file>`.

## Local dry run

```sh
export SECUREBOOT_SIGNING_KEY="$(cat secureboot-db.key)"
export SECUREBOOT_SIGNING_CERT="$(cat secureboot-db.pem)"
just build-installer && just export-pxe
scripts/sign-secureboot-artifacts.sh          # DIST=dist by default
```

## Checklist

- [ ] `scripts/sign-secureboot-artifacts.sh` passes `shellcheck`.
- [ ] The initrd member paths in the script match where
      `elements/oci/bluefin-server-installer.bst` stages the target UKI and
      where the installer stack ships `systemd-boot`.
- [ ] `python3 -m pytest tests/unit/test_secureboot_signing.py -q` passes.
- [ ] Release assets include `bluefin-server-secureboot.der` and `.pem` when
      the secrets are configured.
