# Bluefin Server — Agent Entry Point

Bluefin Server is a BuildStream 2-based, image-based Linux server OS.
Load **[docs/skills/INDEX.md](docs/skills/INDEX.md)** to route to the skill
for your task.

## What this repo is

- **Core OS:** `oci/bluefin-server-ddi.bst` produces the immutable XFS DDI
  payload.
- **Installer media:** `oci/bluefin-server-installer.bst` produces a UEFI
  bootable raw GPT image with the DDI embedded as a data partition.
- **Interactive installer:** `systemd-sysinstall` (systemd 261+) on
  `/dev/console`; partitioning by `systemd-repart`.
- **Updates:** image-based A/B updates via `systemd-sysupdate` from GitHub
  Releases, verified with GPG-signed `SHA256SUMS` manifests.
- **Extensions:** optional layers are `systemd-sysext` (or `systemd-confext`)
  images, not packages baked into the base DDI.
- **Factory floor:** this OS is designed to be the base image for downstream
  CI labs and OS factories that build and test image-based Linux workloads.

## Hard rules

1. Compose from FSDK `components/*`. Never use `platform.bst`.
2. Keep the CPU baseline broad: no `x86_64_v3`.
3. Installer must stay `systemd-sysinstall`-native; no custom installer
   scripts or non-native installers.
4. No shell in the running OS DDI image.
5. Boot entries use GPT `PARTUUID`; never hardcode device paths.

## Build / test commands

BuildStream runs inside the FSDK `bst2` container via the `just bst` wrapper.
Only `podman` and `just` are required locally.

```bash
just validate              # merge contract: resolve the element graph
just tags                  # show derived FSDK versions
just build-installer       # local full installer build
just export-installer      # export .raw.zst + SHA256SUMS
just build-ddi             # local OS DDI payload build
just export-ddi            # export DDI + SHA256SUMS
just build-sysext          # build k3s systemd-sysext
just export-sysext         # export sysext artifacts
just cluster-build         # submit build to the CI cluster (preferred)
just show-me-the-future    # QEMU smoke test of the installer
```

## Skill routing

| Task | Load |
|------|------|
| Build or debug the installer / DDI | `docs/skills/ddi-installer.md` |
| Factory role, k3s sysext rationale | `docs/skills/factory-integration.md` |
| Work with systemd-sysext / confext | `docs/skills/systemd-sysext-extensions.md` |
| Build or ship the k3s sysext | `docs/skills/k3s-sysext.md` |
| Update the FSDK pin / versioning | `docs/skills/bump-fsdk-version.md` |
| CI workflows, action SHA pinning | `docs/skills/ci-tooling.md` |
| Release signing / sysupdate trust | `docs/skills/systemd-sysupdate-verification.md` |
| Credential sealing with TPM2 | `docs/skills/tpm2-credential-sealing.md` |
| System containers (machinectl) | `docs/skills/system-containers.md` |
| Cut bloat / avoid over-engineering | `docs/skills/avoid-over-engineering.md` |
| Add or refactor skills or this file | `docs/skills/skill-improvement.md` |

## Documentation conventions

- Keep `AGENTS.md` small. For task-specific guidance, load the skill from
  `docs/skills/INDEX.md` rather than asking here.
- Update the skill that matches your work before handoff. Output = work +
  learning (see `docs/skills/skill-improvement.md`).
- Before using an external tool, prefer Context7 lookup for authoritative docs.
  If Context7 is unavailable, fetch the public spec and label uncertainty.

## Boundaries

- **Do not** add Containerfiles or shell-based installers.
- **Do not** hardcode block device paths in boot configuration.
- **Do not** put Kubernetes or debug tooling in the base DDI if it can live in
  a sysext or system container.
- **Do not** duplicate a fact that already lives in a skill file.

## Verification

- [ ] `just validate` passes before any handoff.
- [ ] Any changed skill file is listed in `docs/skills/INDEX.md`.
- [ ] Internal-only references (hostnames, private infra names) are not added to
      `AGENTS.md` or skill files.
