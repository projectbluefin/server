# systemd-sysinstall Native Installer Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the Bluefin Server installation process from the knuckle interactive Go TUI to the native systemd-sysinstall interactive tool introduced in systemd v261.

**Architecture:** Upgrading the systemd suite inside `gnome-build-meta` to v261 via a junction patch, completely purging knuckle-specific build elements and services, and configuring the installer UKI command-line to boot directly into `system-install.target` (which spawns `systemd-sysinstall` interactively on the physical console).

**Tech Stack:** BuildStream 2, systemd-sysinstall, systemd-repart, bootctl, systemd-ukify, XFS.

## Global Constraints

- **Conventional Commits:** All commits must follow Conventional Commits format: `<type>(<scope>): <desc>`
- **Co-authored-by:** Every commit must end with the trailer:
  `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`
- **No Knuckle:** No knuckle binaries, remote resources, or custom service units are allowed in the final codebase.
- **XFS Defaults:** The OS DDI payload filesystem and writable user partition (/var) must be formatted and managed as pure XFS.

---

### Task 1: Upgrade Junction `gnome-build-meta` systemd suite to v261

**Files:**
- Create: `patches/gnome-build-meta/upgrade-systemd-v261.patch`

**Interfaces:**
- Consumes: `gnome-build-meta` junction.
- Produces: systemd v261 packages (libs, systemd, systemd-ukify) with `systemd-sysinstall` enabled.

- [ ] **Step 1: Create the git patch for systemd-base upgrade**

Create `patches/gnome-build-meta/upgrade-systemd-v261.patch` with the following content:

```diff
diff --git a/elements/core-deps/systemd-base.bst b/elements/core-deps/systemd-base.bst
--- a/elements/core-deps/systemd-base.bst
+++ b/elements/core-deps/systemd-base.bst
@@ -10,7 +10,7 @@ sources:
   track: v*
   exclude:
   - '*-rc*'
-  ref: v260.2-0-gf1d0952a125b96b7ab2f1ff29a87448ade8ac29b
+  ref: v261-0-gde9dbc30cbea730329870bf6be2aab91dac98d38
 
 build-depends:
 - freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
@@ -95,6 +95,7 @@ variables:
     -Ddns-servers="%{fallback-dns-servers}"
     -Ddefault-dnssec=no
     -Didn=true
+    -Dsysinstall=true
     -Dman=enabled
     -Dhtml=enabled
     -Dtpm=true
```

- [ ] **Step 2: Run validate-installer to verify junction resolves and applies patch**

Run: `just validate-installer`
Expected: Element graph resolves successfully with no merge/patch errors.

- [ ] **Step 3: Commit junction patch**

Run:
```bash
git add patches/gnome-build-meta/upgrade-systemd-v261.patch
git commit -m "build(junction): patch gnome-build-meta to upgrade systemd to v261

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Target OS xfsprogs dependency update

**Files:**
- Modify: `elements/bluefin-server/os-stack.bst`

**Interfaces:**
- Consumes: Target OS image runtime dependencies.
- Produces: `xfs_growfs` inside target OS to allow systemd-growfs partition resizing on first boot.

- [ ] **Step 1: Add xfsprogs dependency**

In `elements/bluefin-server/os-stack.bst`, append `freedesktop-sdk.bst:components/xfsprogs.bst` to the `depends:` list:

```yaml
  # Filesystem resizing support for growing root/var on first boot
  - freedesktop-sdk.bst:components/xfsprogs.bst
```

- [ ] **Step 2: Run validate to verify target DDI graph resolves**

Run: `just validate`
Expected: Elements resolve and compile cleanly.

- [ ] **Step 3: Commit target OS stack modification**

Run:
```bash
git add elements/bluefin-server/os-stack.bst
git commit -m "fix(os): add xfsprogs to os-stack for boot volume expansion

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Purge Knuckle TUI and custom installer systemd units

**Files:**
- Delete: `elements/installer/installer-knuckle.bst`
- Delete: `files/installer/units/installer.service`
- Delete: `files/installer/units/installer.target`
- Modify: `elements/installer/installer-stack.bst`

**Interfaces:**
- Consumes: Installer rootfs composition stack.
- Produces: Cleaned up installer rootfs with zero knuckle/custom installer target references.

- [ ] **Step 1: Delete knuckle element and custom unit files**

Run:
```bash
git rm elements/installer/installer-knuckle.bst
git rm files/installer/units/installer.service
git rm files/installer/units/installer.target
```

- [ ] **Step 2: Remove dependencies from installer-stack.bst**

Edit `elements/installer/installer-stack.bst` to remove:
- `- installer/installer-knuckle.bst`
- `- installer/installer-units.bst`

- [ ] **Step 3: Run validate-installer to verify**

Run: `just validate-installer`
Expected: Elements resolve successfully.

- [ ] **Step 4: Commit purged components**

Run:
```bash
git add elements/installer/installer-stack.bst
git commit -m "refactor(installer): purge knuckle binary element and custom service units

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Configure UKI to boot to system-install.target

**Files:**
- Modify: `elements/oci/bluefin-server-installer.bst`

**Interfaces:**
- Consumes: UKI (Unified Kernel Image) build instructions.
- Produces: EFI kernel cmdline pointing systemd PID 1 to `system-install.target`.

- [ ] **Step 1: Update UKI cmdline**

In `elements/oci/bluefin-server-installer.bst`, edit the `--cmdline` option inside the Step 4 UKI creation command block to:

```yaml
        --cmdline="systemd.unit=system-install.target console=ttyS0,115200 console=tty0 rw" \
```

- [ ] **Step 2: Run validate-installer to verify configuration changes**

Run: `just validate-installer`
Expected: Resolves successfully.

- [ ] **Step 3: Commit UKI boot command-line updates**

Run:
```bash
git add elements/oci/bluefin-server-installer.bst
git commit -m "feat(installer): boot installer directly into system-install.target

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Documentation updates for dd Direct Pipe writing

**Files:**
- Modify: `docs/skills/ddi-installer.md`

**Interfaces:**
- Consumes: Raw flashing documentation instructions.
- Produces: Corrected, sector-aligned write instructions for piping streams.

- [ ] **Step 1: Add iflag=fullblock to flashing command**

In `docs/skills/ddi-installer.md`, locate the direct pipe writing code block:

```bash
sudo sh -c 'zstd -dc dist/bluefin-server-installer-*.raw.zst | dd of=/dev/sda bs=4M oflag=direct status=progress'
```

And update it to:

```bash
sudo sh -c 'zstd -dc dist/bluefin-server-installer-*.raw.zst | dd of=/dev/sda bs=4M iflag=fullblock oflag=direct status=progress'
```

- [ ] **Step 2: Commit documentation updates**

Run:
```bash
git add docs/skills/ddi-installer.md
git commit -m "docs(skills): fix block alignment in direct dd flash pipe instructions

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
