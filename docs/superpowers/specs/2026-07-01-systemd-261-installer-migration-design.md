# Design: Migrating to systemd-sysinstall (v261) Native Installer

This design document outlines the migration from **knuckle** (Go-based TUI installer) to the native **systemd-sysinstall** (introduced in systemd 261) as the default interactive operating system installer.

---

## 1. Overview & Goals

- **Reduce Complexity:** Get rid of the custom interactive installer code (knuckle) and custom installer services/targets.
- **Native Alignment:** Leverage systemd's built-in, declarative partitioning (`systemd-repart`), boot management (`bootctl`), and credentials propagation (`systemd-creds`) via the new `systemd-sysinstall` interactive terminal tool.
- **Robustness:** Resolve longstanding issues with partition resizing (missing `xfsprogs` in target OS) and drive formatting alignment.

---

## 2. Upgrading to systemd v261

We will patch the `gnome-build-meta` junction to upgrade the systemd suite (`systemd`, `systemd-libs`, `systemd-ukify`) from version 260.2 to **261**.

- **Junction Patch:** `patches/gnome-build-meta/upgrade-systemd-v261.patch`
- **Target File:** `elements/core-deps/systemd-base.bst`
- **Changes:**
  - Update `ref` to systemd tag `v261` (commit `de9dbc30cbea730329870bf6be2aab91dac98d38`).
  - Add `-Dsysinstall=true` to `meson-local` to build and package `systemd-sysinstall` and its systemd units.

---

## 3. Purging Knuckle and Custom Installer Units

Since `systemd-sysinstall` is a native, self-contained solution, we will delete all knuckle-related elements and custom installer services:

- **Delete Files:**
  - `elements/installer/installer-knuckle.bst`
  - `files/installer/units/installer.service`
  - `files/installer/units/installer.target`
- **Modify `elements/installer/installer-stack.bst`:**
  - Remove dependencies on `installer/installer-knuckle.bst` and `installer/installer-units.bst`.
  - Maintain dependencies on `installer/installer-repart.bst`, base filesystem tools (`dosfstools`, `xfsprogs`), and kernel.

---

## 4. UKI & Boot Configuration

We will adapt the installer disk's Unified Kernel Image (UKI) to boot directly into systemd's native `system-install.target` instead of our custom `installer.target`.

- **Modify `elements/oci/bluefin-server-installer.bst`:**
  - Update UKI kernel command line:
    `--cmdline="systemd.unit=system-install.target console=ttyS0,115200 console=tty0 rw"`
  - `systemd-sysinstall.service` is symlinked by default inside systemd v261 to `system-install.target.wants/systemd-sysinstall.service`.
  - When booting into `system-install.target`, systemd will automatically spawn `systemd-sysinstall` on the physical console (`/dev/console` / `tty0`).
  - Our partition recipes (`10-esp.conf`, `20-root-a.conf`, and `30-var.conf`) are staged at `/usr/lib/repart.d/` in the live environment. Since `/usr/lib/repart.sysinstall.d/` is empty, `systemd-sysinstall` automatically falls back to `/usr/lib/repart.d/`.

---

## 5. Inline Bug Fixes

As part of this codebase migration, we will address two critical issues identified during code review:

### A. Missing `xfsprogs` in Target OS (`elements/bluefin-server/os-stack.bst`)
The target OS image is formatted as XFS. To support automated partition expansion (`GrowFileSystem=yes` in `20-root-a.conf` and `30-var.conf`), `systemd-growfs` needs `xfs_growfs` at boot.
- **Fix:** Add `freedesktop-sdk.bst:components/xfsprogs.bst` as a dependency of `elements/bluefin-server/os-stack.bst`.

### B. Sector-Misalignment in Direct Piping Flashing Commands (`docs/skills/ddi-installer.md`)
Piping `zstd -dc` directly to `dd oflag=direct` without ensuring block boundaries causes `EINVAL` write failures due to short block pipe reads.
- **Fix:** Update the recommended flash command in documentation to include `iflag=fullblock`:
  ```bash
  sudo sh -c 'zstd -dc dist/bluefin-server-installer-*.raw.zst | dd of=/dev/sda bs=4M iflag=fullblock oflag=direct status=progress'
  ```
