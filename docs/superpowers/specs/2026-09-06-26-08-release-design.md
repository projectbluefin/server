# Bluefin Server 26.08 Release Design & Plan

## Overview

This document specifies the design, changes, and verification for the **26.08.0** major baseline release of Bluefin Server. It upgrades the base operating system junction to the upstream **freedesktop-sdk 26.08.0** release line, decouples the k3s sysext onto its own version axis, enforces architectural invariants, updates CI action dependencies, and sets the stage for cluster boot validation.

## Context & Objectives

1. **Upstream FSDK 26.08.0 Alignment**:
   - Upstream freedesktop-sdk released `26.08.0`.
   - `projectbluefin/fsdk-containers` established the reference implementation for 26.08:
     - CAS limits patch is obsolete (already upstream in FSDK 26.08).
     - FSDK 26.08 ships its own systemd; GNOME build-meta systemd overrides are removed.
     - `runtime-minimal` dropped bash and coreutils, which moved to `public-stacks/runtime-gnu.bst`. Stacks executing shell-based integration commands (e.g. `base-stack.bst`) need `runtime-gnu.bst` explicitly staged.
2. **k3s Sysext Version Axis Decoupling (#32, PR #47, PR #48)**:
   - Previously, the k3s sysext was named on the OS release axis (`k3s-%{release-version}.raw`), while its payload and `VERSION_ID` were pinned to the k3s axis.
   - Fixed by introducing `include/k3s.yml` as the single source of truth for the k3s version axis.
   - Enforced by `.github/scripts/check-k3s-version.py`, comprehensive unit test suite in `tests/unit/test_k3s_version.py`, pre-commit hook, and `just validate`.
   - PR #48 closed in favor of PR #47 changes, with Bob Killen credited as co-author.
3. **k3s Architecture Guard (#32 Problem 2)**:
   - Added fail-closed build constraint in `elements/oci/k3s-sysext.bst` guarding that `arch == 'x86_64'`, preventing accidental creation of invalid aarch64 images with x86_64 ELF payloads.
4. **Action Digest Bump (PR #46)**:
   - Updated `taiki-e/install-action` pin from `b6b84cf49ebfe0176417bdce007c624f0db37f20` to `7b8d4719ee4aaa279bdf55df38dacb9ebfe12a6c` in `build.yml` and `unit-tests.yml`.
5. **PXE Network DDI Pull Scoping (#14, PR #27)**:
   - Standalone PXE kernel/initrd artifacts were already shipped in #23.
   - Network DDI downloading (`inst.ddi_url`) deferred to a subsequent point release; PR #27 kept on hold with explanatory note.
6. **OS Release Version Invariant**:
   - `project.conf` `release-version: "26.08.0"`.
   - Verified by `.github/scripts/check-release-version.py` against `freedesktop-sdk.bst`.

## Changes Summary

| Subsystem | File(s) | Change |
|---|---|---|
| k3s Single Source of Truth | `include/k3s.yml` | New version specification for k3s upstream tag and asset version. |
| k3s Binary & Sysext | `elements/k3s/k3s-bin.bst`, `elements/oci/k3s-sysext.bst`, `files/k3s/sysext/extension-release.k3s` | Consume `include/k3s.yml`; generate `VERSION_ID` and `ARCHITECTURE` dynamically; fail closed on non-x86_64. |
| k3s Validation & Tests | `.github/scripts/check-k3s-version.py`, `tests/unit/test_k3s_version.py`, `.pre-commit-config.yaml`, `Justfile` | Fail closed if literal version leaked or axis mismatch occurs; unit test test suite. |
| FSDK Junction | `elements/freedesktop-sdk.bst` | Point to `freedesktop-sdk-26.08*` track, ref `freedesktop-sdk-26.08.0-0-gdb97cce32cecadc7a3e98f06d557ebfa6ba9ad46`, drop systemd overrides. |
| FSDK Patches | `patches/freedesktop-sdk/` | Dropped upstreamed CAS limits patch; keep GNOME CAS servers patch. |
| Runtime Stack | `elements/base/base-stack.bst` | Added `runtime-gnu.bst` dependency for integration scripts. |
| OS Release & Tagging | `project.conf`, `Justfile` | `release-version: "26.08.0"`. Tags resolve to `latest`, `26.08`, `26.08.0`. |
| CI Workflows | `.github/workflows/build.yml`, `.github/workflows/unit-tests.yml` | Update `taiki-e/install-action` digest. |
| Documentation | `docs/skills/bump-fsdk-version.md`, `docs/skills/k3s-sysext.md` | Document FSDK 26.08 lifecycle and k3s axis isolation. |

## Verification & Gates

1. `python3 .github/scripts/check-release-version.py` -> PASS
2. `python3 .github/scripts/check-k3s-version.py` -> PASS
3. `pytest tests/unit/` -> PASS (89 passed, 1 expected xfail)
4. `just validate` -> PASS (element graph resolves cleanly for OS DDI, installer, and sysext)
5. `just tags` -> PASS (`latest`, `26.08`, `26.08.0`)
6. `python3 .github/scripts/docs-checks.py` -> PASS

## Post-Release Verification Plan

Once the release tag `installer-v26.08.0` is published by GitHub Actions:
1. Download `bluefin-server-installer-26.08.0.raw.zst` and UKI `bluefin-server-26.08.0.efi`.
2. Execute smoke test via `just show-me-the-future` (QEMU headless test).
3. Cluster smoke test in ghost lab: verify node provisioning and `systemd-sysext status` reports `VERSION_ID=1.36.2-k3s1`.
