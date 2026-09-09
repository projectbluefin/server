# Task 5 Report — Repair First-Boot Delivery Prerequisites

## Outcome

Implemented the narrowly scoped delivery correction on `feat/k0s-first-boot`.

- Added the FSDK-style `20-wired.network` configuration to the target DDI
  with wired `DHCP=ipv4`, packaged through a dedicated BuildStream import.
- Enabled `systemd-networkd.service` through the existing target system preset
  import so the installed OS does not depend on the Installer-only network
  configuration.
- Split the k0s transfer into the `k0s` systemd-sysupdate component directory
  and changed `k0s-first-boot.service` to run only
  `systemd-sysupdate --component=k0s update`.
- Changed release staging and the release job label to use the requested
  `k0s-*.raw.zst` artifact; the focused contract rejects legacy `k3s-` staging.
- Updated the k0s version checker and directly related documentation for the
  component-scoped transfer path.

The target DDI remains shell-free, k0s remains only in the optional sysext, and
no authentication, secret, lab, or deployment configuration was changed.

## TDD evidence

### RED

After strengthening the focused contracts, the current branch failed as
expected:

```sh
cd /home/jorge/src/server-k0s-first-boot
python3 -m pytest tests/unit/test_k0s_first_boot.py tests/unit/test_sysupdate_transfers.py -q
```

Result: `10 failed, 21 passed`. Failures covered the unscoped sysupdate
command, missing target network configuration and packaging, the transfer
being in the generic directory, and missing `k0s-` release staging.

The version-checker path contract also failed before its production correction:

```sh
python3 -m pytest tests/unit/test_k0s_version.py::test_k0s_version_checker_reads_the_component_transfer -q
```

### GREEN

The corrected focused contracts pass:

```sh
python3 -m pytest \
  tests/unit/test_k0s_version.py::test_k0s_version_checker_reads_the_component_transfer \
  tests/unit/test_k0s_first_boot.py \
  tests/unit/test_sysupdate_transfers.py -q
```

Result: `32 passed`.

## Verification

```sh
cd /home/jorge/src/server-k0s-first-boot
python3 .github/scripts/docs-checks.py
```

Passed: `Docs checks passed.`

```sh
just test-unit
```

Passed: `118 passed, 1 xfailed`; Bats passed all `41` tests.

```sh
just validate
```

Passed: release-version and k0s-version checks succeeded, and all three
BuildStream dependency graphs resolved successfully with exit code `0`.

`git diff --check` also passed with no whitespace errors.

## Commit

The intended change set is committed with:

```text
fix(k0s): repair first-boot delivery prerequisites
Assisted-by: GPT-5.6 Luna via GitHub Copilot
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```
