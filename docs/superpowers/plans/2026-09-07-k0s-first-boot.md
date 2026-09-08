# k0s First-Boot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make a new Bluefin Server installation activate the optional k0s
sysext and reconcile its KubeStellar manifests without blocking boot. Provide
a supported interactive QEMU flow that opens the ready Console in the host's
default XDG browser.

**Architecture:** The DDI stays free of Kubernetes. A base systemd service
downloads the already-defined k0s Transfer, merges the independently shipped
sysext, seeds its manifests, and enables its controller. The service records
success under `/var/lib/k0s`; this allows failures to retry at the current boot
and future boots without rerunning after success. A separate QEMU recipe
forwards the existing guest `hostPort: 8080` to host loopback and calls
`xdg-open` only after HTTP readiness.

**Tech Stack:** BuildStream, systemd-sysupdate, systemd-sysext, systemd
services, k0s, QEMU, just, pytest.

**Spec:** User-approved sysext-first, background-activation design in this
session.

## Global Constraints

- Keep k0s and KubeStellar in the existing optional sysext, never in the base
  DDI.
- Do not add a shell to the target DDI. Service commands call native binaries
  directly.
- The Installer stays systemd-sysinstall-native. Bash belongs in the Installer
  runtime only because its existing wrapper explicitly requires `/bin/bash`.
- Published Installer media is interactive; the headless smoke test passes
  `unattended` through its PXE kernel command line.
- `k0s-first-boot.service` is wanted by `multi-user.target` but does not order
  the target after itself. Normal boot does not wait for sysext download,
  image pulls, or Console readiness.
- The QEMU forward is only
  `127.0.0.1:8080` -> guest `127.0.0.1:8080`; it is not production networking.
- Keep the VM operation canonical in `docs/skills/k0s-sysext-ops.md`; README
  links to it rather than repeating the procedure.

---

### Task 1: Repair the Installer and preserve interactive release media

**Files:**
- Modify: `elements/installer/installer-stack.bst`
- Modify: `elements/oci/bluefin-server-installer.bst`
- Modify: `Justfile`
- Create: `tests/unit/test_installer_contract.py`

**Interfaces:**
- Consumes: `/usr/bin/bluefin-sysinstall`, whose interpreter is `/bin/bash`,
  and the Installer's exported PXE kernel/initrd.
- Produces: interactive published raw Installer media and an unattended
  `show-me-the-future` smoke install.

- [ ] **Step 1: Write the failing installer contracts**

Create `tests/unit/test_installer_contract.py`. Assert:

```python
assert "freedesktop-sdk.bst:components/bash.bst" in installer_stack
assert 'console=ttyS0,115200 rw"' in installer_element
assert "unattended" not in published_uki_cmdline
assert '-append "systemd.unit=system-install.target console=tty0 console=ttyS0,115200 rw unattended"' in justfile
```

Extract `published_uki_cmdline` from the `ukify build` command, not from the
whole element, so the assertion permits the wrapper's `unattended` check.

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```sh
python3 -m pytest tests/unit/test_installer_contract.py -q
```

Expected: Bash is absent from the Installer stack, the published UKI embeds
`unattended`, and the QEMU smoke test does not supply a PXE kernel command
line.

- [ ] **Step 3: Apply the smallest source corrections**

1. Add the following runtime dependency to
   `elements/installer/installer-stack.bst`:

   ```yaml
   - freedesktop-sdk.bst:components/bash.bst
   ```

2. Remove only the `unattended` token from the UKI `--cmdline` in
   `elements/oci/bluefin-server-installer.bst`. Keep both console arguments
   and `systemd.unit=system-install.target`.

3. In `show-me-the-future`, retain the raw Installer disk as the data source
   but boot its exported `bluefin-server-pxe-vmlinuz-*` and
   `bluefin-server-pxe-initrd-*.cpio.gz` via QEMU's `-kernel`, `-initrd`, and
   `-append`. The exact `-append` value is the tested one above. This leaves
   the published UEFI UKI interactive while preserving an unattended,
   headless smoke install. Continue booting the installed target through
   OVMF, which validates the target's UEFI path.

- [ ] **Step 4: Run the focused validation**

Run:

```sh
python3 -m pytest tests/unit/test_installer_contract.py -q
just validate
```

- [ ] **Step 5: Commit the Installer repair**

```sh
git add elements/installer/installer-stack.bst elements/oci/bluefin-server-installer.bst Justfile tests/unit/test_installer_contract.py
git commit -m "fix(installer): restore interactive sysinstall"
```

### Task 2: Activate the k0s sysext until it succeeds

**Files:**
- Create: `files/os/systemd/system/k0s-first-boot.service`
- Create: `files/os/systemd/system-preset/zz-enable-k0s-first-boot.preset`
- Create: `elements/bluefin-server/os-k0s-first-boot.bst`
- Modify: `elements/bluefin-server/os-stack.bst`
- Create: `tests/unit/test_k0s_first_boot.py`

**Interfaces:**
- Consumes: `files/os/sysupdate.d/70-k0s.transfer`,
  `/var/lib/extensions/k0s.raw`, `systemd-sysext.service`,
  `/usr/lib/tmpfiles.d/k0s-manifests.conf`, and
  `k0scontroller.service` supplied by the sysext.
- Produces: a preset-enabled bootstrap unit which retries only until all those
  operations succeed.

- [ ] **Step 1: Write the failing service contracts**

Create `tests/unit/test_k0s_first_boot.py` that reads the service, preset,
and new element. Assert:

```python
assert "ConditionPathExists=!/var/lib/k0s/.first-boot-complete" in service
assert "Wants=network-online.target" in service
assert "After=network-online.target" in service
assert "Before=multi-user.target" not in service
assert "Type=oneshot" in service
assert "StateDirectory=k0s" in service
assert "Restart=on-failure" in service
assert "ExecStart=/usr/bin/systemd-sysupdate update" in service
assert "ExecStart=/usr/bin/systemctl enable --now systemd-sysext.service" in service
assert "ExecStart=/usr/bin/systemd-sysext merge" in service
assert "ExecStart=/usr/bin/systemd-tmpfiles --create /usr/lib/tmpfiles.d/k0s-manifests.conf" in service
assert "ExecStart=/usr/bin/systemctl daemon-reload" in service
assert "ExecStart=/usr/bin/systemctl enable --now k0scontroller.service" in service
assert "ExecStartPost=/usr/bin/touch /var/lib/k0s/.first-boot-complete" in service
assert "WantedBy=multi-user.target" in service
assert "enable k0s-first-boot.service" in preset
assert "path: files/os/systemd/system" in element
assert "target: /usr/lib/systemd/system" in element
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```sh
python3 -m pytest tests/unit/test_k0s_first_boot.py -q
```

Expected: failure because the service, its preset, and import element do not
exist.

- [ ] **Step 3: Package the bootstrap unit**

Create `elements/bluefin-server/os-k0s-first-boot.bst` as an import:

```yaml
kind: import
description: Install the first-boot k0s sysext activation unit.

sources:
  - kind: local
    path: files/os/systemd/system

config:
  target: /usr/lib/systemd/system
```

Add this element to `elements/bluefin-server/os-stack.bst`. The existing
`os-sshd-preset.bst` already imports the full
`files/os/systemd/system-preset` directory, so adding the new preset there
requires no second preset import.

Create the unit with exactly this command ordering:

```ini
[Unit]
Description=Activate k0s sysext after first installation
ConditionPathExists=!/var/lib/k0s/.first-boot-complete
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
StateDirectory=k0s
Restart=on-failure
RestartSec=30s
ExecStart=/usr/bin/systemd-sysupdate update
ExecStart=/usr/bin/systemctl enable --now systemd-sysext.service
ExecStart=/usr/bin/systemd-sysext merge
ExecStart=/usr/bin/systemd-tmpfiles --create /usr/lib/tmpfiles.d/k0s-manifests.conf
ExecStart=/usr/bin/systemctl daemon-reload
ExecStart=/usr/bin/systemctl enable --now k0scontroller.service
ExecStartPost=/usr/bin/touch /var/lib/k0s/.first-boot-complete

[Install]
WantedBy=multi-user.target
```

Create `zz-enable-k0s-first-boot.preset` containing:

```text
enable k0s-first-boot.service
```

The completion stamp is written only after the controller has started. A
download, merge, manifest seeding, or controller-start failure therefore
retries after `RestartSec` and again on following boots. It replaces
`ConditionFirstBoot=yes`, which would suppress retries once systemd considers
the host initialized.

- [ ] **Step 4: Run the focused tests and graph validation**

Run:

```sh
python3 -m pytest tests/unit/test_k0s_first_boot.py tests/unit/test_k0s_manifests.py tests/unit/test_sysupdate_transfers.py -q
just validate
```

- [ ] **Step 5: Commit the activation path**

```sh
git add elements/bluefin-server/os-k0s-first-boot.bst elements/bluefin-server/os-stack.bst files/os/systemd/system/k0s-first-boot.service files/os/systemd/system-preset/zz-enable-k0s-first-boot.preset tests/unit/test_k0s_first_boot.py
git commit -m "feat(k0s): activate sysext on first boot"
```

### Task 3: Add a persistent interactive VM and browser flow

**Files:**
- Modify: `Justfile`
- Create: `tests/unit/test_vm_dashboard_contract.py`

**Interfaces:**
- Consumes: the interactive raw Installer and an installed persistent target
  disk.
- Produces: `just install-vm`, a graphical QEMU flow that forwards the
  Console and opens it in the host browser when ready.

- [ ] **Step 1: Write the failing launcher contract**

Create `tests/unit/test_vm_dashboard_contract.py`. Isolate the `install-vm`
recipe text and assert:

```python
assert "hostfwd=tcp:127.0.0.1:8080-:8080" in recipe
assert 'curl --silent --show-error --max-time 2 --output /dev/null http://127.0.0.1:8080/' in recipe
assert "xdg-open http://127.0.0.1:8080/" in recipe
assert "XDG_STATE_HOME" in recipe
assert "qemu-system-x86_64" in recipe
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```sh
python3 -m pytest tests/unit/test_vm_dashboard_contract.py -q
```

- [ ] **Step 3: Add `install-vm` without changing the smoke-test interface**

Add an `install-vm` recipe next to `show-me-the-future`:

1. Store assets beneath
   `${XDG_STATE_HOME:-$HOME/.local/state}/bluefin-server/vm-<fsdk-version>`,
   creating the target disk and copied OVMF variables only when absent.
2. On first invocation, run `just export-installer`, decompress the raw
   Installer there, and start it with QEMU's normal graphical display so the
   user completes systemd-sysinstall. Wait for the Installer to power off
   before continuing.
3. Start the installed disk through OVMF in the background using:

   ```text
   -nic user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:8080-:8080
   ```

4. Poll the tested curl command until it succeeds. Before every retry, confirm
   the QEMU process is still live and exit nonzero if it died. Do not use a
   fixed sleep as readiness evidence.
5. Call exactly:

   ```sh
   xdg-open http://127.0.0.1:8080/
   ```

   then keep QEMU attached until the user exits it. Its exit trap terminates
   only that recorded QEMU PID.

Retain `show-me-the-future` as a headless CI smoke target.

- [ ] **Step 4: Run focused tests and graph validation**

Run:

```sh
python3 -m pytest tests/unit/test_installer_contract.py tests/unit/test_vm_dashboard_contract.py -q
just validate
```

- [ ] **Step 5: Commit the VM launcher**

```sh
git add Justfile tests/unit/test_vm_dashboard_contract.py
git commit -m "feat(vm): open Kubestellar after installation"
```

### Task 4: Document only the proven operation

**Files:**
- Modify: `docs/skills/k0s-sysext-ops.md`
- Modify: `README.md`
- Modify: `tests/unit/test_vm_dashboard_contract.py`

**Interfaces:**
- Consumes: the verified `just install-vm` operation.
- Produces: one canonical user-facing flow and a README pointer.

- [ ] **Step 1: Extend the failing documentation contract**

Assert that `docs/skills/k0s-sysext-ops.md` contains `just install-vm` and
`http://127.0.0.1:8080/`.

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```sh
python3 -m pytest tests/unit/test_vm_dashboard_contract.py -q
```

- [ ] **Step 3: Add only supplied operation copy**

Add this supplied sentence to the k0s operation skill:

```text
Install -> VM -> working Kubestellar in their default XDG Flatpak browser.
```

Place `just install-vm` and its local Console URL beside it. Link to that
section from README; do not duplicate its instructions elsewhere.

- [ ] **Step 4: Validate docs and unit tests**

Run:

```sh
python3 .github/scripts/docs-checks.py
python3 -m pytest tests/unit/test_vm_dashboard_contract.py -q
```

- [ ] **Step 5: Commit the documentation**

```sh
git add README.md docs/skills/k0s-sysext-ops.md tests/unit/test_vm_dashboard_contract.py
git commit -m "docs: describe Kubestellar VM workflow"
```

### Task 5: Verify the end-to-end delivery

**Files:**
- No source changes expected.

- [ ] **Step 1: Build the three delivered artifacts**

Run:

```sh
just build-ddi
just build-installer
just build-sysext
```

- [ ] **Step 2: Run all repository gates**

Run:

```sh
just test-unit
just validate
python3 .github/scripts/docs-checks.py
```

- [ ] **Step 3: Prove the user journey**

On a clean VM state directory, run:

```sh
just install-vm
```

Complete the Installer, wait for the host Console URL to respond, and verify
the command invokes the XDG browser with that URL. Confirm the guest's
`k0s-first-boot.service` reached success and that
`/var/lib/k0s/.first-boot-complete` was created only after
`k0scontroller.service` started.

## Plan Review

- **Spec coverage:** Task 1 makes the released Installer usable; Task 2
  activates only the optional k0s delivery path without holding boot; Task 3
  supplies loopback forwarding and browser readiness; Task 4 makes the
  validated operation discoverable.
- **Retry safety:** The stamp condition records success rather than merely the
  first attempt, so temporary networking or registry failures recover without
  manual intervention.
- **Boundary check:** Kubernetes remains sysext-delivered, no target-shell
  dependency is introduced, and the installer remains native systemd-sysinstall.
