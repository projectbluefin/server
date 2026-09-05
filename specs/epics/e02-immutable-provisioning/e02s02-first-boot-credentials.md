### Story e02s02: Provision first-boot root credentials and SSH keys

**type:** feat
**risk:** P0
**context:** security

## Context

The image currently installs a sysusers fragment but has no repository-defined
SSH authorized-key input or installer-to-target credential handoff. Alpha 2
needs a systemd-native credential contract without embedding secrets.

## Requirements

- **ADDED** — First boot accepts the documented encrypted root password and SSH
  authorized-key credentials, consumes them once, and leaves no plaintext in
  the DDI or installer image.
- **ADDED** — Missing or malformed credentials fail safely and do not grant an
  unintended login path.

## Steps

1. Verify the pinned systemd credential interfaces and define credential names,
  delivery, and consumers → verify: `grep -RIn 'systemd-creds\|credential' docs elements files | head -120`
2. Implement credential consumption using systemd sysusers/tmpfiles or native
  units, with no shell provisioning script → verify: `just validate`
3. Exercise credentialed first boot in QEMU/factory test → verify:
  `just test`

## Out of scope

- Fleet-wide TPM key rotation or network credential productization.

## Risks

- Credentials are a security boundary; release evidence must prove no secrets
  enter BuildStream outputs or logs.
