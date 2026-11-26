---
name: homebrew-seed
description: Homebrew in the base image as a seed archive extracted at first boot. Use when changing the brew pins, the seed element, its unit, tmpfiles or shell profile.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-11-07"
---
# homebrew seed

Use this skill when changing how Homebrew ships in the base image.

Homebrew is in the base /usr as a seed archive, not a system container or sysext.
`elements/homebrew/seed.bst` builds `/usr/share/homebrew/brew.tar.zst`: Homebrew/brew
at a pinned tag (a local git repo with origin Homebrew/brew) plus the portable-ruby
that tag vendors, under one `.linuxbrew` directory. Pins (tag, commit, ruby version,
per-arch sha256) live only in `include/homebrew.yml`; move them together. Brew 5.0.1
is used because newer tags need a ruby published only on ghcr.io.

## First boot

`bluefin-homebrew-seed.service` (also triggered by `bluefin-homebrew-seed.path` when
`/etc/passwd` changes) runs `/usr/libexec/bluefin-homebrew-seed`: it extracts the
archive to `/home/linuxbrew/.linuxbrew`, owned by the first regular user
(UID 1000-59999), then writes `/var/lib/bluefin-homebrew/seeded`. It defers while no
such user exists, never overwrites an existing prefix and is offline.

`/home/linuxbrew` is a tmpfiles link to `/var/home/linuxbrew`, so packages persist.
`/etc/profile.d/90-bluefin-homebrew.sh` runs `brew shellenv` only for the
non-root owner recorded in `/var/lib/bluefin-homebrew/seed-owner`, or the
existing prefix's filesystem owner when that record is absent. Root and other
users do not receive automatic Brew setup.
For that owner, unset or empty `CONTAINER_HOST` defaults to the Bluefin Podman
socket. Unset or empty `DOCKER_HOST` defaults to the Bluefin Docker socket when
its user service is active, otherwise the Bluefin Podman socket. Nonempty
explicit values are preserved.
The base carries git, curl, file, zstd, tar, xz and gzip, and no compiler.

## Home Server profile

`home-server.bu` only selects the Podman/Docker host engines
(`bluefin.homebrew.{podman,docker,cluster}` credentials); `bluefin-oci-owner-prepare`
prepares the first regular user for them.
