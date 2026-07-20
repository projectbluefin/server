---
name: system-containers
version: "1.0"
last_updated: "2026-07-20"
tags: ['containers', 'machinectl', 'nspawn']
description: "Add or document system containers that should behave like first-class systemd machines rather than podman/OCI workloads. Use when managing container lifecycle with machinectl and systemd-run."
metadata:
  context7-sources:
    - /systemd/systemd
---

# system containers

Use this skill when adding or documenting system containers that should behave
like first-class systemd machines rather than podman/OCI workloads.

A system container is a plain rootfs image imported with
`machinectl import-tar`. It is managed with `machinectl` and the thin
`/usr/bin/system-container` helper shipped in the OS image (backed by
`machinectl start`/`poweroff`/`shell`/`remove`).

The host experience should be a transparent machine experience, not a container
runtime UI.

## When to Use

- Shipping a development or debugging toolbox as a `systemd-nspawn` rootfs.
- Documenting how operators import, start, enter, and reset a machine image.
- Changing `files/bin/system-container` or the default toolbox justfile in
  `files/os/justfile`.

## When NOT to Use

- Adding a distroless OCI runtime image — the server repo does not build those.
- Kubernetes workload or cluster questions — use `k3s-sysext.md`.

## Lifecycle

The OS image ships a small helper at `/usr/bin/system-container`:

```bash
system-container start <name>
system-container stop  <name>    # machinectl poweroff
system-container enter <name>    # machinectl shell
system-container reset <name>    # machinectl remove
```

Under the hood these map directly to `machinectl`.

## First-time setup

Replace `<image-url>` with the published `.tar.zst` rootfs URL for the toolbox.

```bash
sudo machinectl import-tar <image-url> homebrew
sudo system-container start homebrew
sudo system-container enter homebrew
```

When done inside the container:

```bash
exit
sudo system-container stop homebrew
```

## Reset a container

Resetting removes the machine and starts over from a fresh import:

```bash
sudo system-container reset homebrew
sudo machinectl import-tar <image-url> homebrew
sudo system-container start homebrew
```

## Inspecting machines on a host

```bash
machinectl list
machinectl list-images
```

## Homebrew conventions

If the toolbox is Homebrew-based, use `/home/linuxbrew` as the writable prefix.
Set `HOMEBREW_NO_AUTO_UPDATE=1` and `HOMEBREW_NO_INSTALL_CLEANUP=1` in its
environment so updates are explicit and the environment behaves like a standard
Linux Homebrew installation.

## Interacting with a machine service

To run a command inside a running machine:

```bash
systemd-run --machine=homebrew --pty /usr/bin/env
```

## Verification

- [ ] `files/bin/system-container` exists and maps to valid `machinectl` commands.
- [ ] The rootfs image format is documented (`.tar.zst` for `import-tar`).
- [ ] Toolbox images are not confused with OCI images or sysexts in docs.
