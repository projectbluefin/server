---
name: ddi-installer
description: "Use when building or debugging the Bluefin Server DDI live installer, sysupdate release assets, or the lab GitOps build hook."
metadata:
  context7-sources:
    - /systemd/systemd
    - /apache/buildstream
---

# DDI Installer

## When to Use

- Adding or changing the Bluefin Server live installer
- Wiring `systemd-sysinstall`, `systemd-sysupdate`, `systemd-repart`, or `bootctl`
- Packaging or publishing DDI assets to GitHub Releases
- Updating the Argo/GitOps build hook in the lab

## When NOT to Use

- OCI-only image work
- Bootc-specific changes
- Desktop or nspawn machine image work
- Dracut-based installer design unless the repo explicitly reintroduces it

> [!NOTE]
> **Fully wired.** Both the live installer media and the OS DDI payload image pipelines are now fully implemented.
> - ✅ Dracut-free cpio initrd assembled inline by the BST script element
> - ✅ UKI built with `ukify` (unsigned; Secure Boot signing is opt-in)
> - ✅ sysupdate.d transfer config pulls OS DDI from GitHub Releases
> - ✅ repart.d target disk layout defined
> - ✅ `bluefin-install` orchestration script (sysupdate → repart → bootctl)
> - ✅ Release signal-tag workflow (`.github/workflows/release-installer.yml`) publishes installer build signal tags
> - ✅ OS DDI artifact (`bluefin-server-ddi-@v.raw.zst`) integrated as a first-class payload

## Core Process

1. Keep the live media thin: it should orchestrate install-time flow, not define a second distro.
2. Prefer systemd-native pieces first: `systemd-sysinstall`, `systemd-sysupdate`, `systemd-repart`, `bootctl`, `ukify`.
3. Use a cpio-based initrd when the installer rootfs is already known at build time; avoid dracut unless you truly need hardware autodetection.
4. Publish installer media and OS DDI payload as versioned release assets with matching checksums.
5. Make the lab GitOps pipeline clone the moved repo and build the installer element from the server repo.
6. Keep repo URLs, release URLs, and labels aligned after any rename or transfer.
7. Use `just show-me-the-future` as the end-to-end VM test: boot the installer read-only, install to a second raw disk, then reboot into the installed server.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "Dracut is the safe default." | It is heavier than a known rootfs + cpio path when the installer contents are already reproducible. |
| "The installer should carry the whole OS payload." | The live media should install a DDI payload, not become a second OS lineage. |
| "GitHub Releases is just a download bucket." | `systemd-sysupdate` needs stable versioned assets and checksums, so the release contract matters. |

## Red Flags

- The installer depends on bootc or OCI pulls instead of DDI assets
- The live image is carrying unrelated desktop or runtime bloat
- `systemd-sysupdate` URLs still point at the old repo name after a move
- A lab build template clones the wrong repository or builds the wrong element
- Dracut is added without a specific, documented need

## Initrd assembly (cpio-native)

Packing the entire rootfs as a cpio with `find . | cpio --null --create --format=newc` and pointing `ukify` at it is the approach the systemd project uses for its own test images (`mkosi`-built images use the same mechanism without a generator). It requires only `cpio` + `find` + `zstd` — all in FSDK `components/`.

The initrd is larger than a hand-tuned dracut output (because it includes all kernel modules), but size is not a concern for USB installer media, and the approach is simpler to maintain and debug.

The `bluefin-server-installer.bst` script element:

```bash
# 1. Add /init symlink (Linux initrd protocol: kernel executes /init as PID 1)
ln -sf usr/lib/systemd/systemd /layer/init

# 2. Link default.target -> installer.target
ln -sf installer.target /layer/usr/lib/systemd/system/default.target

# 3. Pack the entire rootfs as a newc cpio archive + zstd-compress
( cd /layer && find . -print0 | cpio --null --create --format=newc ) \
  | zstd -T0 -19 -q -o /installer.cpio.zst

# 4. Build the UKI (unsigned for dev; add --secureboot-* for release signing)
KVER=$(ls /layer/usr/lib/modules | head -1)
ukify build \
  --linux="/layer/usr/lib/modules/${KVER}/vmlinuz" \
  --initrd=/installer.cpio.zst \
  --cmdline="systemd.unit=installer.target console=ttyS0,115200 rw" \
  --output=/layer/boot/efi/EFI/Linux/installer.efi

# 5. Assemble a single-partition GPT disk (ESP only) for the installer media
#    (separate from the target-disk repart.d in /usr/lib/repart.d/)
systemd-repart --empty=create --size=auto --dry-run=no \
  --root=/layer --definitions=/installer-media-repart.d \
  bluefin-server-installer-<ver>.raw
```

## Network-pull install flow

```
Installer boot (UEFI reads ESP → systemd-boot → installer.efi)
     │
     ▼
installer.efi (UKI: kernel + cpio initrd)
     │
     ▼
systemd PID 1 starts, reaches installer.target
     │
     ▼
installer.service → bluefin-install script:
     │
     ├─ systemd-sysupdate --definitions=/usr/lib/sysupdate.d update
     │      fetches bluefin-server-ddi-@v.raw.zst from GitHub Releases
     │      deposits /run/installer/bluefin-server-ddi.raw
     │
     ├─ systemd-repart --dry-run=no --empty=force /dev/TARGET
     │      reads /usr/lib/repart.d/ (10-esp, 20-root-a, 30-var)
     │      20-root-a: CopyBlocks=/run/installer/bluefin-server-ddi.raw
     │
     ├─ bootctl install --esp-path=/mnt/esp --root=/mnt/root
     │      installs systemd-boot + OS UKI into the new ESP
     │
     └─ systemctl poweroff
          │
          ▼
     Reboot into installed Bluefin Server
```

## Target disk detection

The `bluefin-install` script auto-detects the first writable non-removable
block device (`/dev/vda`, `/dev/sda`, `/dev/nvme0n1`, `/dev/mmcblk0`).
To override, pass `installer.disk=/dev/TARGET` on the kernel cmdline.

## Secure Boot signing (opt-in)

The installer UKI is produced unsigned by default. To produce a signed UKI:

```bash
# Add to ukify build invocation in bluefin-server-installer.bst:
--secureboot-private-key=/path/to/vendor.key \
--secureboot-certificate=/path/to/vendor.crt
```

Inject the key files as BST secrets or CI secrets. The FSDK pattern for this
is in `elements/vm/minimal-secure/signed-boot.bst` (uses `kind: local` sources
for the key files — keep those out of the repo).

## sysupdate.d transfer config

```ini
[Source]
Type=url-file
Path=https://github.com/projectbluefin/server/releases/download/
MatchPattern=bluefin-server-ddi-@v.raw.zst
SHA256Sum=SHA256SUMS

[Target]
Type=regular-file
Path=/run/installer/
MatchPattern=bluefin-server-ddi-@v.raw
CurrentSymlink=/run/installer/bluefin-server-ddi.raw
```

## OS DDI payload image

The DDI payload `bluefin-server-ddi-@v.raw.zst` is the raw ext4 filesystem image
that `systemd-sysupdate` pulls. It is built by `elements/oci/bluefin-server-ddi.bst`
which:
1. Depends on `bluefin-server/os-stack.bst` (stripped of bootc/ostree bloat).
2. Runs `mkfs.ext4` to format the rootfs directory `/layer` into an ext4 image.
3. Compresses the raw image via `zstd` and generates `SHA256SUMS`.

> [!NOTE]
> **Lab OCI Packaging:** In-cluster build pipelines push artifacts to the local Zot registry. Because the DDI payload and installer disk image are raw script outputs (not native OCI layouts), the `bluefin-server-build-pipeline` automatically detects this and wraps them in a minimal `scratch` OCI image (using `FROM scratch; COPY . /`) before pushing.

## Justfile commands

```
just validate-installer    # resolve element graph
just build-installer       # full build: cpio + ukify + systemd-repart
just export-installer      # export .raw.zst + SHA256SUMS to dist/
just build-ddi             # build OS DDI filesystem payload
just export-ddi            # export DDI + SHA256SUMS to dist/ddi/
```

## Release

`.github/workflows/release-installer.yml` fires on `installer-v*` tags.
**GitHub is the control plane only** — the workflow resolves the tag ref,
runs `just validate-installer` (element graph resolution, no build), then
publishes `installer-build/<installer-tag>` as a GitOps signal tag.
The lab consumes that tag, builds the installer, and uploads artifacts to the GitHub Release.

```
git tag installer-v0.1.0 && git push origin installer-v0.1.0
```

Signal tag format:
- `installer-build/<installer-tag>` (e.g. `installer-build/installer-v0.1.0`)
- tag object points at the pinned commit SHA being released

The lab is responsible for:
1. `just build-installer` + `just export-installer`
2. `just build-ddi` + `just export-ddi`
3. Creating/updating the GitHub Release
4. Uploading `bluefin-server-installer-<ver>.raw.zst`, `bluefin-server-ddi-<ver>.raw.zst`, and checksums.

> No BST build compute runs on GitHub-hosted runners.

## Related

- `docs/skills/nspawn-machine-image.md` — tarball artifact pattern
- `elements/oci/brew-nspawn.bst` — reference for non-OCI script elements
- FSDK `elements/vm/minimal-secure/` — repart + ukify toolchain reference

## Verification

- `just validate-installer` resolves the BuildStream graph
- The installer image builds a bootable live media artifact
- The release workflow publishes DDI assets and `SHA256SUMS`
- The release workflow publishes installer + DDI assets in the same `installer-v*` release stream
- The lab GitOps build template points at the moved repo and the installer element
- Repo URLs in README, workflows, and sysupdate configs match the current GitHub location
