# show-me-the-future Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `just show-me-the-future` build the installer, boot it in QEMU on a second disk, install Bluefin Server, reboot, and land on the installed server console.

**Architecture:** Keep the command raw-image based and systemd-native. The installer image is booted read-only as the live medium, a second writable raw disk is attached as the target, and the VM is relaunched on the installed disk after install completes. No ISO wrapper, no extra installer format, and no new orchestration layer.

**Tech Stack:** Just, Bash, QEMU, OVMF/edk2, BuildStream artifacts, systemd-repart/systemd-sysupdate.

## Global Constraints

- Use the documented raw GPT disk image installer path, not a true ISO output.
- Keep the live media thin and systemd-native; do not reintroduce bootc or dracut.
- Prefer the simplest working QEMU flow; do not add a new VM framework.
- Preserve the current BuildStream artifact contracts for `bluefin-server-ddi` and `bluefin-server-installer`.

---

### Task 1: Adding a two-phase QEMU install runner

**Files:**
- Modify: `Justfile:215-248`

**Interfaces:**
- Consumes: `just build-ddi`, `just export-ddi`, `just build-installer`, `just export-installer`
- Produces: `just show-me-the-future`

- [ ] **Step 1: Add a `show-me-the-future` recipe that builds and exports the installer artifacts, creates a temporary workdir, and prepares two raw disks**

```bash
set -euo pipefail
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/bluefin-show-future.XXXXXX")"
trap 'rm -rf "$WORKDIR"' EXIT

just build-ddi
just export-ddi
just build-installer
just export-installer

cp dist/bluefin-server-installer-*.raw.zst "$WORKDIR/installer.raw.zst"
zstd -d "$WORKDIR/installer.raw.zst" -o "$WORKDIR/installer.raw"
fallocate -l 32G "$WORKDIR/target.raw"
```

- [ ] **Step 2: Add a native-QEMU boot helper that finds OVMF, boots the installer disk read-only, and attaches the blank target disk writable**

```bash
OVMF_CODE=""
for candidate in \
  /usr/share/edk2/ovmf/OVMF_CODE.fd \
  /usr/share/OVMF/OVMF_CODE.fd \
  /usr/share/OVMF/OVMF_CODE_4M.fd \
  /usr/share/edk2/x64/OVMF_CODE.4m.fd \
  /usr/share/qemu/OVMF_CODE.fd; do
  if [ -f "$candidate" ]; then
    OVMF_CODE="$candidate"
    break
  fi
done
[ -n "$OVMF_CODE" ] || { echo "ERROR: OVMF_CODE not found"; exit 1; }
```

```bash
OVMF_VARS=""
for candidate in \
  /usr/share/edk2/ovmf/OVMF_VARS.fd \
  /usr/share/OVMF/OVMF_VARS.fd \
  /usr/share/OVMF/OVMF_VARS_4M.fd \
  /usr/share/edk2/x64/OVMF_VARS.4m.fd \
  /usr/share/qemu/OVMF_VARS.fd; do
  if [ -f "$candidate" ]; then
    OVMF_VARS="$candidate"
    break
  fi
done
[ -n "$OVMF_VARS" ] || { echo "ERROR: OVMF_VARS not found"; exit 1; }
cp "$OVMF_VARS" "$WORKDIR/ovmf-vars.fd"
```

```bash
qemu-system-x86_64 \
  -enable-kvm \
  -m 4096 \
  -cpu host \
  -smp 2 \
  -drive file="$WORKDIR/installer.raw",format=raw,if=virtio,readonly=on \
  -drive file="$WORKDIR/target.raw",format=raw,if=virtio \
  -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
  -drive if=pflash,format=raw,file="$WORKDIR/ovmf-vars.fd" \
  -nographic \
  -serial mon:stdio
```

- [ ] **Step 3: Relaunch the VM on the installed target disk after the installer powers off**

```bash
qemu-system-x86_64 \
  -enable-kvm \
  -m 4096 \
  -cpu host \
  -smp 2 \
  -drive file="$WORKDIR/target.raw",format=raw,if=virtio \
  -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
  -drive if=pflash,format=raw,file="$WORKDIR/ovmf-vars.fd" \
  -nographic \
  -serial mon:stdio
```

- [ ] **Step 4: Run the smallest meaningful verification**

Run: `just validate`

Run: `just show-me-the-future`

Expected: installer boots from the read-only media, installs to the writable target disk, powers off, then the second QEMU boot lands on the installed Bluefin Server console.

- [ ] **Step 5: Commit**

```bash
git add Justfile docs/superpowers/plans/2026-06-30-show-me-the-future.md
git commit -m "feat: add show-me-the-future vm flow"
```

### Task 2: Documenting the VM install flow

**Files:**
- Modify: `README.md:23-33`
- Modify: `docs/skills/ddi-installer.md:26-58`

**Interfaces:**
- Consumes: `just show-me-the-future`
- Produces: repo docs that tell contributors how the boot/install/reboot flow works

- [ ] **Step 1: Update the README command list so `show-me-the-future` is the documented end-to-end install test**

```markdown
just validate
just build
just export
just build-installer
just export-installer
just show-me-the-future
```

- [ ] **Step 2: Update the DDI installer skill so it explains the two-disk QEMU test path**

```markdown
- The live installer boots read-only in QEMU.
- A second writable raw disk is attached as the target.
- `show-me-the-future` installs to the target, reboots, and lands on the installed server console.
```

- [ ] **Step 3: Re-run the doc-facing check**

Run: `just validate-installer`

Expected: the BuildStream graph still resolves after the doc updates.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/skills/ddi-installer.md
git commit -m "docs: describe the full installer vm flow"
```
