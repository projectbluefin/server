# Bluefin Server — Agent Entry Point

Bluefin Server is an FSDK-based, image-based Linux server OS. It produces:
- an immutable XFS DDI OS payload (`oci/bluefin-server-ddi.bst`)
- an offline, systemd-native installer raw disk (`oci/bluefin-server-installer.bst`)
- an optional k3s `systemd-sysext` (`oci/k3s-sysext.bst`)

## What agents should know first

1. Read this file.
2. Load [`docs/skills/index.md`](docs/skills/index.md) to route to the skill for your task.
3. Never guess label names, workflow secrets, or infrastructure hostnames — check the relevant skill.

## Hard rules

1. Compose from FSDK `components/*`. Never use `platform.bst`.
2. Keep the CPU baseline broad: no `x86_64_v3`.
3. Installer must stay `systemd-sysinstall`-native; no custom installer scripts or non-native installers.
4. No shell in the running OS DDI image. OpenSSH is installed for operators but `sshd.service` is disabled by default and key-only; see [`docs/skills/factory-integration.md`](docs/skills/factory-integration.md).
5. Vendor-authored configuration belongs under `/usr/etc` by repo policy (systemd does not automatically search it); `/etc` is mutable but boot-local operator/runtime state — durable operator overrides belong in a `systemd-confext` under `/var/lib/confexts/`. A file under `/etc` is allowed only when an upstream tool hardcodes that path (or has no vendor-config lookup) or the file is generated/local state, and the exception must be documented with its compatibility mechanism; see [`docs/skills/systemd-sysext-extensions.md`](docs/skills/systemd-sysext-extensions.md).
6. Boot entries use GPT `PARTUUID`; never hardcode device paths.
7. One canonical source per fact; do not duplicate content across docs.

## Build / test commands

All `just` targets run BuildStream inside the FSDK `bst2` container via `just bst`; BuildStream is not installed locally.

| Command | Purpose |
|---|---|
| `just validate` | Merge-contract graph check — run this on every change. |
| `just build-ddi` | Local OS DDI payload build. |
| `just export-ddi` | Export DDI artifacts to `dist/ddi/`. |
| `just build-installer` | Local full installer build. |
| `just export-installer` | Export installer + UKI to `dist/`. |
| `just build-sysext` | Build the k3s `systemd-sysext`. |
| `just export-sysext` | Export sysext artifacts to `dist/sysext/`. |
| `just test` | Local QEMU installer-to-boot acceptance test. |

## Skill routing

| Task | Skill |
|---|---|
| Build or debug the installer / DDI | [`docs/skills/ddi-installer.md`](docs/skills/ddi-installer.md), [`docs/skills/ddi-installer-build.md`](docs/skills/ddi-installer-build.md) |
| Factory role, k3s sysext rationale, lab integration | [`docs/skills/factory-integration.md`](docs/skills/factory-integration.md) |
| Work with `systemd-sysext` / `systemd-confext` | [`docs/skills/systemd-sysext-extensions.md`](docs/skills/systemd-sysext-extensions.md) |
| Build or ship the k3s sysext | [`docs/skills/k3s-sysext.md`](docs/skills/k3s-sysext.md), [`docs/skills/k3s-sysext-ops.md`](docs/skills/k3s-sysext-ops.md) |
| Update the FSDK pin / versioning | [`docs/skills/bump-fsdk-version.md`](docs/skills/bump-fsdk-version.md) |
| CI workflows, action SHA pinning | [`docs/skills/ci-tooling.md`](docs/skills/ci-tooling.md) |
| Release signing / sysupdate trust | [`docs/skills/systemd-sysupdate-verification.md`](docs/skills/systemd-sysupdate-verification.md) |
| Credential sealing with TPM2 | [`docs/skills/tpm2-credential-sealing.md`](docs/skills/tpm2-credential-sealing.md) |
| System containers (`machinectl`) | [`docs/skills/system-containers.md`](docs/skills/system-containers.md) |
| Cut bloat / avoid over-engineering | [`docs/skills/avoid-over-engineering.md`](docs/skills/avoid-over-engineering.md) |
| Add or refactor skills | [`docs/skills/skill-improvement.md`](docs/skills/skill-improvement.md) |

## Documentation conventions

- Update only the skill that matches your change.
- Keep `AGENTS.md` small; do not list deep context here.
- Remove `TODO/FIXME` and work-in-progress markers before merging; move unfinished work to issues.
- Use Conventional Commits. For doc-only changes: `docs:`.

## Boundaries

- Do not add Containerfiles or shell-based installers.
- Do not ship vendor defaults in `/etc`; use `/usr/etc` unless a documented exception (upstream-hardcoded path or no vendor-config lookup) applies.
- Do not hardcode block device paths in boot configuration.
- Do not put Kubernetes or debug tooling in the base DDI if it can live in a sysext or system container.
- Do not duplicate a fact already in a skill.

## Verification

- [ ] `just validate` passes.
- [ ] Any changed skill is listed in [`docs/skills/index.md`](docs/skills/index.md).
- [ ] No new internal-only hostnames or proprietary names appear in `AGENTS.md` or skills.

## Factory workflow and ownership

Use the shared
[`label workflow`](https://github.com/projectbluefin/common/blob/main/docs/skills/label-workflow.md)
for labels, lifecycle, and ownership, and
[`bonedigger templates`](https://github.com/projectbluefin/bonedigger/blob/main/docs/skills/bonedigger-templates.md)
for template synchronization. Humans triage and approve; agents claim only
queued work; Clankers only transports Hive assignments. Keep server-specific
workflow and ownership local, and never write to `ublue-os/*`.
