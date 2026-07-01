# AGENTS.md

`projectbluefin/server` is **Bluefin Server** — an FSDK-based, image-based Linux
server OS in the same use-case space as Flatcar Linux, Fedora CoreOS, and Talos.
It is a [BuildStream 2](https://buildstream.build/) project. No Containerfiles —
BST elements build reproducible OCI images and DDI installer media from FSDK
`components/*`.

Load **[docs/skills/README.md](docs/skills/README.md)** for the skill routing table.
Only load the docs relevant to your task.

> **Before using any tool or library: look up its docs via Context7 first. Always.**
> BuildStream, knuckle, podman, GitHub Actions, systemd (repart/ukify) —
> every tool has live, authoritative docs. Pattern: `resolve-library-id` →
> `get-library-docs` → implement → cite the section. Guessing is banned.

## What this repo is

- **OS image:** `oci/bluefin-server-ddi.bst` — the server OS DDI payload (ext4
  image compressed with zstd), deployed by the installer onto the target disk.
- **Installer media:** `oci/bluefin-server-installer.bst` — a bootable GPT image
  (ESP + embedded DDI data partition). At boot, systemd reaches
  `installer.target`, which launches **knuckle** — a Go TUI interactive installer.
  The OS DDI is embedded at build time; no network required at install time.
  SSH is available on the live installer (`ssh root@<ip>`, no password).
- **Knuckle installer:** `installer/installer-knuckle.bst` stages the
  `projectbluefin/knuckle` release binary at `/opt/knuckle`. knuckle prompts for
  disk, username, password, and SSH key; runs systemd-repart + user provisioning;
  writes a stable PARTUUID boot entry; then reboots.
- **No shell in the OS image.** The DDI payload is distroless. The installer
  rootfs carries only what knuckle needs to install the OS.

## Hard rules

1. **Compose from `components/*`, never `platform.bst`.** `platform.bst` drags in
   Wayland/Mesa/PipeWire desktop bloat.
2. **No `x86_64_v3`.** Broad-compatibility baseline only.
3. **No non-interactive bash installer scripts.** The installer is knuckle.
   A bash script cannot prompt for username, password, or SSH key on a TTY.
4. **Installer binary comes from knuckle releases.** Update `installer-knuckle.bst`
   `ref:` (sha256) when bumping knuckle. Never vendor the binary directly.
5. **PARTUUID boot entries only.** Never hardcode `/dev/vda2` or similar.
   knuckle uses `lsblk` to find the `PARTLABEL=bluefin-server-root-a` PARTUUID.

## Build / test commands (verified)

BuildStream runs inside the FSDK `bst2` container via the `just bst` wrapper —
nothing to install but `podman` + [`just`](https://github.com/casey/just).

```
just validate-installer   # resolve installer element graph (no build)
just build-installer      # full build: cpio + ukify + systemd-repart
just export-installer     # export .raw.zst + SHA256SUMS to dist/
just build-ddi            # build OS DDI filesystem payload
just export-ddi           # export DDI + SHA256SUMS to dist/ddi/
just tags                 # show FSDK-derived version tags
```

There is no `just verify` gate for the server repo (that is fsdk-containers).
The contract here is: element graph resolves (`just validate-installer`) and the
lab build completes without error.

## Versioning

The version axis is the **FSDK release**, parsed from the pinned junction ref in
`elements/freedesktop-sdk.bst`. The installer and DDI assets carry matching
version strings from the same FSDK pin. Follow the FSDK lifecycle — see
[docs/skills/bump-fsdk-version.md](docs/skills/bump-fsdk-version.md).

Knuckle is versioned independently. Current: **v0.9.0**. Update
`elements/installer/installer-knuckle.bst` (`url:` + `ref:`) when bumping.

## The self-improvement loop

Every session produces two outputs:

1. **The work** — the element, fix, or image.
2. **The learning** — what a future agent needs to know, written into `docs/skills/`.

Output 1 without Output 2 leaves the project no smarter. Before handoff, update or
add the relevant skill file. See [docs/skills/skill-improvement.md](docs/skills/skill-improvement.md).
