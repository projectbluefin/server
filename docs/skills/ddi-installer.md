---
name: ddi-installer
description: "Use when building or debugging the Bluefin Server DDI live installer, updating the knuckle installer binary, sysupdate release assets, or the lab GitOps build hook."
metadata:
  context7-sources:
    - /systemd/systemd
    - /apache/buildstream
---

# DDI Installer

## When to Use

- Building or debugging the Bluefin Server live installer media
- Bumping the knuckle installer binary version
- Wiring `systemd-sysupdate`, `systemd-repart`, `bootctl`, or `ukify`
- Packaging or publishing DDI assets to GitHub Releases
- Updating the Argo/GitOps build hook in the lab

## When NOT to Use

- OCI-only image work (no installer involvement)
- Bootc-specific changes
- Desktop or nspawn machine image work
- Adding a network-pull installer — the current design is local-DDI via knuckle

## Architecture

The installer is **knuckle** — a Go TUI interactive installer
(`projectbluefin/knuckle`) that replaced the non-interactive `bluefin-install`
bash script. knuckle prompts the user for:

- Target disk (detected via `lsblk`)
- Username, password (bcrypt-hashed), SSH key
- Confirmation before writing

Then it runs `systemd-repart`, provisions the user, writes a stable
`PARTUUID`-based boot entry via `bootctl`, and reboots.

**Why knuckle and not systemd-sysinstall?**
`systemd-sysinstall` requires systemd ≥261 (released June 2026) and does NOT
prompt for username/password — it defers to `systemd-firstboot` on first boot.
knuckle is already used for Flatcar/FCOS installs in this org, is tested, and
provides full user provisioning during install. Parity with the Flatcar variant
was the requirement.

## Core Process

1. Keep the live media thin: orchestrate install-time flow via knuckle, not a second distro.
2. knuckle binary lives at `/opt/knuckle` in the installer rootfs — staged by `installer/installer-knuckle.bst`.
3. `installer.service` runs `ExecStart=/opt/knuckle --os bluefin-ddi` on `tty1`.
4. knuckle uses `PARTLABEL=bluefin-server-root-a` to find its root partition — never hardcode `/dev/vda2`.
5. Publish installer media and OS DDI payload as versioned release assets with matching checksums.
6. The lab GitOps pipeline clones the server repo and builds the installer element.
7. Use `just show-me-the-future` as the end-to-end VM test: boot installer, install to a second disk, reboot into installed system.

## Bumping the knuckle version

When a new knuckle release is cut:

```bash
# 1. Get the SHA256 of the new binary
SHA=$(curl -sL https://github.com/projectbluefin/knuckle/releases/download/vX.Y.Z/knuckle_linux_amd64 | sha256sum | awk '{print $1}')

# 2. Update elements/installer/installer-knuckle.bst
#    Change both `url:` (version in path) and `ref:` (sha256)
```

`installer-knuckle.bst` uses `kind: script` with a `kind: remote` source
(BST verifies the sha256 on fetch). The script stages the binary at
`/opt/knuckle` with mode 755.

**Current version:** knuckle v0.9.0
**SHA256:** `0019dfc4b32d63c1392aa264aed2253c1e0c2fb09216f8e2cc269bbfb8bb49b5`

## Installer boot flow

```
UEFI reads ESP → systemd-boot → installer.efi (UKI)
     │
     ▼
systemd PID 1 starts, reaches installer.target
     │
     ▼
installer.service → /opt/knuckle --os bluefin-ddi
     │
     ├─ TUI: disk selection (lsblk detects candidates)
     ├─ TUI: username / password / SSH key
     ├─ systemd-repart --dry-run=no /dev/TARGET
     │      reads /usr/lib/repart.d/ (10-esp, 20-root-a, 30-var)
     ├─ User provisioning (useradd + authorized_keys + sudoers)
     ├─ bootctl install (PARTUUID boot entry)
     └─ Reboot into installed Bluefin Server
```

## Initrd assembly (cpio-native)

The `bluefin-server-installer.bst` script element builds the UKI inline:

```bash
# 1. /init symlink (Linux initrd protocol)
ln -sf usr/lib/systemd/systemd /layer/init

# 2. Link default.target -> installer.target
ln -sf installer.target /layer/usr/lib/systemd/system/default.target

# 3. Pack rootfs as newc cpio + zstd
( cd /layer && find . -print0 | cpio --null --create --format=newc ) \
  | zstd -T0 -19 -q -o /installer.cpio.zst

# 4. Build UKI
KVER=$(ls /layer/usr/lib/modules | head -1)
ukify build \
  --linux="/layer/usr/lib/modules/${KVER}/vmlinuz" \
  --initrd=/installer.cpio.zst \
  --cmdline="systemd.unit=installer.target console=ttyS0,115200 rw" \
  --output=/layer/boot/efi/EFI/Linux/installer.efi

# 5. Assemble single-partition GPT disk (ESP only)
systemd-repart --empty=create --size=auto --dry-run=no \
  --root=/layer --definitions=/installer-media-repart.d \
  bluefin-server-installer-<ver>.raw
```

## OS DDI payload

`oci/bluefin-server-ddi.bst` builds the OS DDI payload:
1. Depends on `bluefin-server/os-stack.bst`
2. Runs `mkfs.ext4` on the rootfs `/layer` directory
3. Compresses with `zstd` → `bluefin-server-ddi-@v.raw.zst` + `SHA256SUMS`

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
runs `just validate-installer`, then publishes an `installer-build/<tag>`
GitOps signal tag. The lab consumes that tag, builds, and uploads artifacts.

```bash
git tag installer-v0.1.0 && git push origin installer-v0.1.0
```

> No BST build compute runs on GitHub-hosted runners.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "A bash script is simpler." | A bash script cannot prompt for username/password/SSH key. That's why we had a broken installer all day. |
| "Use systemd-sysinstall instead." | Requires systemd ≥261 AND doesn't set username/password — defers to systemd-firstboot. knuckle is already prod-tested for Flatcar. |
| "Hardcode root=/dev/vda2 for QEMU." | Bare metal has different device names. Always use PARTUUID. |
| "SuccessAction=poweroff in installer.service." | knuckle drives shutdown. Having both races. Remove from service, let knuckle decide. |

## Red Flags

- `installer.service` has `SuccessAction=poweroff` (knuckle handles this)
- `installer.service` `ExecStart` points at a bash script instead of `/opt/knuckle`
- `installer-knuckle.bst` `ref:` is a placeholder (`PLACEHOLDER_*`)
- Boot cmdline has `root=/dev/vda2` (hardcoded device path)
- knuckle binary is vendored in the repo instead of fetched from releases
- `installer-stack.bst` missing `installer/installer-knuckle.bst` dependency

## Verification

- [ ] `just validate-installer` resolves the BuildStream graph without errors
- [ ] `installer-knuckle.bst` `ref:` matches `sha256sum` of the release binary
- [ ] `installer.service` `ExecStart=/opt/knuckle --os bluefin-ddi`
- [ ] `installer.service` has NO `SuccessAction=poweroff`
- [ ] `installer-stack.bst` includes `installer/installer-knuckle.bst`
- [ ] Lab build template points at correct repo and installer element
- [ ] Repo URLs in sysupdate configs match current GitHub location (`projectbluefin/server`)

## Related

- `projectbluefin/knuckle` — TUI installer source; `internal/install/ddi.go`
- `docs/skills/nspawn-machine-image.md` — tarball artifact pattern
- FSDK `elements/vm/minimal-secure/` — repart + ukify toolchain reference

