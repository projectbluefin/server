---
name: system-containers
description: Add or document system containers that should behave like first-class systemd machines rather than podman/OCI workloads. Use when managing container lifecycle with machinectl and systemd-run.
---

# system containers

Use this skill when adding or documenting system containers that should behave like first-class systemd machines rather than podman/OCI workloads.

## Core model

- A system container is a plain rootfs image imported with `machinectl import-tar`.
- It is managed with `machinectl` and `systemd-run --machine=`.
- The host experience should be a transparent machine experience, not a container runtime UI.

## Homebrew defaults

- Use `/home/linuxbrew` as the writable prefix.
- Set `HOMEBREW_NO_AUTO_UPDATE=1` and `HOMEBREW_NO_INSTALL_CLEANUP=1`.
- Make `brew shellenv` available in the login shell, for example by sourcing `eval "$($(brew --prefix)/bin/brew shellenv)"` in the container user's profile.

## Lifecycle

- `system-container start <name>`
- `system-container stop <name>`
- `system-container enter <name>`
- `system-container reset <name>`

## Examples

- Homebrew is the default-on convenience toolbox experience.
- Ubuntu is the second built-in example for a more familiar server shell.
- Debian is another transparent example for users who want a Debian-style toolbox.
