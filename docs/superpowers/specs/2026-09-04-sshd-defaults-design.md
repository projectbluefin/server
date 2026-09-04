# SSH Server Default Policy Design

Date: 2026-09-04
Repository: `projectbluefin/server`
Scope: SSH runtime defaults only

## Goal

Ship OpenSSH in the Bluefin Server image for operators and factory bring-up,
but keep `sshd.service` disabled by default and prevent password-based access
when an operator explicitly enables it.

This change does not implement first-boot SSH authorized-key provisioning.
That remains part of the separate `e02s02` credential-provisioning story.

## Decisions

### Package and service state

- Keep `freedesktop-sdk.bst:components/openssh-systemd.bst` in
  `elements/bluefin-server/os-stack.bst`.
- Remove the repository-local `os-sshd-preset.bst` dependency.
- Delete `files/os/systemd/system-preset/zz-enable-sshd.preset`.
- Rely on the FSDK package's normal preset behavior so installation does not
  enable `sshd.service`.

The `zz-` preset is intentionally removed rather than replaced with another
ordering override. It was a local enablement hack for temporary boot-test
access, and the desired invariant is now that SSH is installed but opt-in.

### Authentication policy

Keep `elements/bluefin-server/os-sshd-config.bst` as the local SSH policy
layer. Its drop-in will specify:

```text
PermitRootLogin prohibit-password
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
```

This permits root access only through a provisioned public key and makes an
explicitly enabled service fail closed when no usable key exists. The image
must not contain a pre-baked authorized key or secret.

### Operator and factory behavior

Documentation will say that an operator must provision an authorized key by an
existing external mechanism before running:

```sh
systemctl enable --now sshd.service
```

Documentation must not imply that the repository already provisions SSH keys
on first boot. Factory boot-test instructions will no longer describe SSH as
automatically enabled; the separate credential work must establish any
future unattended access path.

## Files

Expected implementation changes:

- `elements/bluefin-server/os-stack.bst`
- `elements/bluefin-server/os-sshd-config.bst` (description only if needed)
- `files/os/ssh/sshd_config.d/bluefin-server.conf`
- Delete `elements/bluefin-server/os-sshd-preset.bst` if it has no remaining
  consumers.
- Delete `files/os/systemd/system-preset/zz-enable-sshd.preset`.
- Update directly contradictory SSH statements in
  `docs/skills/factory-integration.md` and `README.md`.
- Update any directly affected readiness/spec wording without claiming that
  first-boot key provisioning is complete.

Unrelated release, SBOM, and existing worktree changes are out of scope.

## Validation

1. Confirm the SSH package remains in the stack and the local enable preset is
   absent.
2. Confirm the drop-in contains the four hardened authentication directives.
3. Run `just validate`.
4. Run existing documentation or workflow checks only if the changed files
   require them.

## Non-goals

- Implementing `systemd-creds` SSH-key delivery.
- Modifying root-password provisioning.
- Changing installer partitioning, boot entries, or update behavior.
- Adding a new local disable preset.
- Enabling SSH in CI or the factory by another hidden mechanism.
