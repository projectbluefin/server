# CoreOS-Compatible Operator Login Design

**Status:** Approved design

## Problem

Bluefin Server currently bakes the known `root` password `bluefin` into every
OS DDI, permits root login on standard consoles, advertises that credential on
the console, and permits root, password, and keyboard-interactive SSH
authentication. The OS DDI also contains SSH host private keys generated at
image-build time, so every installed host has the same private host identity.

This is incompatible with an image-based server OS: it supplies a shared,
untraceable administrator identity, allows remote root access as soon as SSH
is enabled, and makes SSH host verification ineffective.

## Goals

- Use the familiar Fedora CoreOS and Flatcar `core` operator account.
- Remove interactive root access completely.
- Allow key-only remote administration and passwordless privilege escalation.
- Ensure user authorization and SSH host identity persist across OS DDI
  updates.
- Provide a physical or hypervisor-mediated recovery process without a
  fallback password or a root SSH exception.
- Use systemd-native provisioning; do not add an installer script.

## Non-goals

- Support password login for `root` or `core`.
- Provide a second remote break-glass identity.
- Add a general-purpose identity-management system.
- Change the installer partition layout beyond using the existing persistent
  `/var` partition.

## Competitor Precedent

Fedora CoreOS and Flatcar use a `core` account with key-based access and
passwordless privilege escalation. Ubuntu Server creates an operator-selected
administrator account instead of assigning an interactive root login. All
three distributions normally set `PermitRootLogin prohibit-password`; Bluefin
will deliberately be stricter and use `PermitRootLogin no`.

References:

- Fedora CoreOS authentication:
  <https://docs.fedoraproject.org/en-US/fedora-coreos/authentication/>
- Flatcar users:
  <https://www.flatcar.org/docs/latest/os-config/host-config/adding-users/>
- Ubuntu Server user management:
  <https://ubuntu.com/server/docs/how-to/security/user-management/>

## Design

### Identities and Privilege

`root` remains the required UID 0 system identity, but its password field is
locked and it has no interactive console or SSH login path. The image contains
no password hash, password credential consumer, root login banner, or
`securetty` policy that enables root console access.

The OS creates a regular operator account:

- username and group: `core`
- UID and GID: `1000`
- shell: `/bin/bash`
- home: `/var/home/core`
- supplementary group: `wheel`

The OS includes FSDK's `sudo` component and an immutable wheel sudoers rule
that grants `NOPASSWD` elevation. This is required because `core` is key-only:

```sh
ssh core@server.example
sudo -i
```

### Persistent Account State and Key Provisioning

The DDI creates `/home` as a symlink to `/var/home`. Consequently, `core`'s
home and its authorization data remain outside the replaceable OS DDI.

`systemd-sysusers` declaratively creates `core`; `systemd-tmpfiles` creates
`/var/home/core` and `/var/home/core/.ssh` with mode `0700`. The
`tmpfiles.extra` system credential supplies a base64-encoded tmpfiles rule
which writes the public-key file with mode `0600`:

```text
d /var/home/core 0700 core core -
d /var/home/core/.ssh 0700 core core -
f~ /var/home/core/.ssh/authorized_keys 0600 core core - c3NoLWVkMjU1MTkgQUFBQUMzTnphQzFsWkRJMU5UR...
```

The credential is delivered as
`/loader/credentials/tmpfiles.extra.cred` on the installed system's ESP, or
through the supported hypervisor system-credential mechanism. The credential
payload is public-key material, not a password or private key.

### Recovery Contract

There is no password or root-key bypass. A missing or unusable `core` key
leaves SSH unavailable. Recovery requires physical access or equivalent
hypervisor access:

1. Shut down the host and attach or mount its ESP from a trusted machine.
2. Replace the `tmpfiles.extra` credential with one that writes the intended
   `core` public key.
3. Boot the host. Systemd processes the replacement and SSH becomes available.

This is a deliberate fail-closed policy. Documentation must clearly state that
the credential is required before a headless deployment can be reached.

### SSH Policy and Host Identity

One replacement SSH configuration is authoritative:

```text
PermitRootLogin no
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
```

It replaces the existing permissive drop-in rather than relying on an
alphabetically later override, since OpenSSH normally accepts the first value
it reads for these settings.

`sshd` is explicitly enabled at boot. It is not enabled merely by changing a
preset, because a preset alone does not establish the runtime enablement
symlink in this image.

The DDI contains no SSH host private keys. A native systemd one-shot service:

- runs after the persistent `/var` filesystem and before `sshd`;
- creates host keys once beneath `/var/lib/ssh`, with root-only ownership and
  permissions;
- configures SSH to use those persistent paths; and
- gates `sshd` if initialization fails.

This yields unique host identities that persist across OS DDI updates.

### Readiness and Failure Handling

A second one-shot readiness unit runs after tmpfiles provisioning and before
`sshd`. It verifies that `core`'s authorized-keys file exists and is non-empty.
When the check fails, it prevents `sshd` from starting and emits a clear
systemd failure rather than booting a machine that appears remotely available
but cannot accept an operator.

The host continues booting and reports the failed readiness unit on its
console, but offers no interactive login. The documented ESP procedure is the
only supported recovery path. No automatic password, root login exception, or
silent fallback is permitted.

### Update and Migration Semantics

`/var/home/core` and `/var/lib/ssh` persist across OS DDI replacements. The
image recreates the `/home` symlink, `core` account definition, sudo policy,
SSH configuration, and service units on every update.

This is a security-breaking change for any installation that currently relies
on `root / bluefin`. Operators must provision the `core` key credential before
booting the hardened release. The release documentation will call this out as
a migration prerequisite.

## Implementation Surfaces

- `elements/oci/bluefin-server-ddi.bst`: remove the baked root password,
  root-console setup, root account-file overwrites, console login hint, and
  build-time SSH key generation; create the persistent home layout.
- `elements/bluefin-server/os-stack.bst`: include `sudo` and the new
  systemd-native login provisioning elements.
- `files/os/ssh/`: replace the permissive SSH configuration and add persistent
  host-key configuration.
- `files/os/sysusers.d/` and `files/os/tmpfiles.d/`: define `core`, its
  persistent home, and root's locked state.
- `files/os/systemd/`: add host-key initialization and core-access readiness
  units, then explicitly enable `sshd`.
- `files/os/sudoers.d/`: add the passwordless wheel policy.
- `files/os/issue.d/`, `README.md`, and the affected skills: remove root
  credential guidance and document the `core` key/ESP recovery contract.
- `tests/unit/`: add focused login-security and provisioning contract tests.

## Verification

Focused unit tests must prove that:

- no known password, root login banner, root console policy, or build-time SSH
  private key is present in the DDI recipe;
- the effective shipped SSH configuration disables root, password, and
  keyboard-interactive authentication;
- `sudo`, UID/GID-stable `core`, persistent home setup, host-key initialization,
  and access readiness ordering are all declared;
- the provisioning example produces owner-only `core` authorization data; and
- missing authorization prevents SSH startup without preventing local boot.

Run the focused tests, `just validate`, and the repository documentation checks.
