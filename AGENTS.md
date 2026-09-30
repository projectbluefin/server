# Bluefin Server — Agent Entry Point

Bluefin Server is an image-based Linux server OS composed from freedesktop-sdk (FSDK) 26.08 components with BuildStream 2. One build of `oci/bluefin-server-image.bst` produces the full release set for one image version:
- the /usr image (`oci/bluefin-server-usr.bst`): an erofs partition plus its dm-verity hash partition, with the root hash recorded in a `usrhash` file
- three signed UKIs (`oci/bluefin-server-boot.bst`): a netboot UKI that pulls the OS DDI into RAM for a diskless boot, a disk UKI for installed nodes, and an installer UKI for the USB installer
- the OS DDI `bluefin-server_<ver>.raw` (usr + usr-verity + ESP), which doubles as the installer payload for diskless installs
- a netboot ESP image with signed systemd-boot and Secure Boot key enrollment payloads
- an offline USB installer `bluefin-server-installer_<ver>.raw` (usr + usr-verity + ESP with systemd-boot, the installer UKI, the disk UKI and `repart.d`) that boots into `systemd-sysinstall`
- optional opt-in `systemd-sysext` images: `oci/k0s-sysext.bst` (controller, or worker when `/etc/k0s/token` exists), `oci/kubestellar-sysext.bst` (Argo CD, KubeStellar, kiosk; needs k0s), `oci/kubeadm-sysext.bst` (kubeadm worker: kubelet, containerd), `oci/zfs-sysext.bst` and `oci/nvidia-container-toolkit-sysext.bst` (CDI only: `nvidia-ctk`, `nvidia-cdi-hook`)
- an SPDX 2.3 SBOM `bluefin-server_<ver>.spdx.json` (`oci/bluefin-server-sbom.bst`)
- a `SHA256SUMS` over the whole set, signed in-element (`SHA256SUMS.gpg`); nodes verify it against `/etc/systemd/import-pubring.pgp`

A release publishes `dist/diskless/` as-is: a GitHub Release `v<ver>` and an ORAS OCI artifact `ghcr.io/<owner>/bluefin-server:<ver>,latest`, both with provenance and SBOM attestations; pull requests rehearse it in `release-dry-run`.

## What agents should know first

1. Read this file.
2. Load [`docs/skills/index.md`](docs/skills/index.md) to route to the skill for your task.
3. Cross-repo factory directives: follow [`projectbluefin/common:docs/factory/agentic-model.md`](https://github.com/projectbluefin/common/blob/main/docs/factory/agentic-model.md).
4. Mandatory use of `projectbluefin` MCP server: query before investigating, designing, or implementing:
   - `search_knowledge(query, limit)` — engineering patterns, coverage gaps, CI conventions, and per-repository findings across `projectbluefin/*`.
   - `get_factory_status()` / `get_work_queue()` — live Hive factory state.
   - Offline fallback: `~/agent.md`, refreshed by `~/.local/bin/sync-hive-kb` (search with `grep`, never load whole file into context).
5. Never guess label names, workflow secrets, or infrastructure hostnames — check the relevant skill. Use `<build-cache-host>` and `<registry-host>:30500` for generic placeholders.

## Hard rules

1. The OS composes from FSDK components via BuildStream. No Flatcar or other-distro binaries. Never use `platform.bst`.
2. Keep the CPU baseline broad: no `x86_64_v3`.
3. Installation stays `systemd-sysinstall`-native and `systemd-repart`-based; no shell installers or non-native installer scripts.
4. Kubernetes, ZFS, and container runtimes ship only as opt-in `systemd-sysext` images, never in the base /usr, and no preset enables them.
5. /usr is a read-only erofs filesystem verified by dm-verity, pinned by `usrhash=` in a signed UKI. Boot and root selection uses discoverable partitions and verity-derived UUIDs; never hardcode device paths.
6. One canonical source per fact; do not duplicate content across docs.

## Commit and attribution conventions

- Use Conventional Commits (`feat:`, `fix:`, `docs:`, `ci:`, `chore:`, etc.).
- Every AI-authored commit must include standard attribution trailers:
  ```text
  Assisted-by: <Model> via GitHub Copilot
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
  ```
- Staging audit before every commit: never use `git add -A` or `git add .`. Run `git status` and `git diff --cached --name-only` to ensure only intended files are staged.

## Build / test commands

All local `just` targets run BuildStream inside the FSDK `bst2` container via `just bst`; BuildStream is not installed locally.

| Command | Purpose |
|---|---|
| `just validate` | Merge-contract graph check — run this on every change. |
| `just test-unit` | Unit tests (pytest + bats). |
| `just gen-dev-keys` | Generate throwaway Secure Boot, module, and image (`SHA256SUMS`) signing keys in `files/boot-keys/` (gitignored). |
| `just set-version V` | Set `image-version` in `include/image.yml` (≤17 chars, increasing under strverscmp). |
| `just build-image` / `just export-image` | Build and export the release image set to `dist/diskless/`. |
| `just dogfood` / `just dogfood-check` | Boot `dist/diskless/` diskless in QEMU with Secure Boot (interactive / headless probe). |
| `just dogfood-install NEXT=<dir>` | QEMU end-to-end: diskless boot, install to disk, boot it, then A/B update to NEXT. |
| `just publish-oci REF [DIR] [PLAIN_HTTP]` | Push `dist/diskless/` as an ORAS OCI artifact tagged `<version>,latest` (one layer per file). Local rehearsal; CI publishes via `scripts/publish-release.sh`. |
| `just build-sysext` / `just export-sysext` | Build and export the k0s and KubeStellar `systemd-sysext` images. |
| `just build-zfs-sysext` / `just export-zfs-sysext` | Build and export the OpenZFS `systemd-sysext`. |
| `just build-nvidia-container-toolkit-sysext` / `just export-nvidia-container-toolkit-sysext` | Build and export the NVIDIA Container Toolkit (CDI) `systemd-sysext`. |

## Skill routing

| Task | Skill |
|---|---|
| Boot / install / update architecture and local build + dogfood | [`docs/skills/ddi-installer.md`](docs/skills/ddi-installer.md), [`docs/skills/ddi-installer-build.md`](docs/skills/ddi-installer-build.md) |
| Offline USB installer (unattended installs, install-time provisioning) | [`docs/skills/usb-installer.md`](docs/skills/usb-installer.md) |
| Network boot at scale (Booty: HTTP boot, per-node Ignition) | [`docs/skills/booty-integration.md`](docs/skills/booty-integration.md) |
| Diskless boot failures, RAM sizing, node logs, Ignition configs | [`docs/skills/diskless-troubleshooting.md`](docs/skills/diskless-troubleshooting.md) |
| Factory role, k0s sysext rationale, lab integration | [`docs/skills/factory-integration.md`](docs/skills/factory-integration.md) |
| Work with `systemd-sysext` / `systemd-confext` | [`docs/skills/systemd-sysext-extensions.md`](docs/skills/systemd-sysext-extensions.md) |
| Build or run the kubeadm worker sysext | [`docs/skills/kubeadm-sysext.md`](docs/skills/kubeadm-sysext.md) |
| Build or ship the k0s sysext | [`docs/skills/k0s-sysext.md`](docs/skills/k0s-sysext.md), [`docs/skills/k0s-sysext-ops.md`](docs/skills/k0s-sysext-ops.md) |
| Update the FSDK pin / versioning | [`docs/skills/bump-fsdk-version.md`](docs/skills/bump-fsdk-version.md) |
| CI workflows, action SHA pinning | [`docs/skills/ci-tooling.md`](docs/skills/ci-tooling.md) |
| Release signing / sysupdate trust | [`docs/skills/systemd-sysupdate-verification.md`](docs/skills/systemd-sysupdate-verification.md) |
| Secure Boot / module / signing key inventory, rotation, CI secrets | [`docs/skills/secure-boot-keys.md`](docs/skills/secure-boot-keys.md) |
| Node access (root / SSH) and credential sealing with TPM2 | [`docs/skills/tpm2-credential-sealing.md`](docs/skills/tpm2-credential-sealing.md) |
| System containers (`machinectl`) | [`docs/skills/system-containers.md`](docs/skills/system-containers.md) |
| Cut bloat / avoid over-engineering | [`docs/skills/avoid-over-engineering.md`](docs/skills/avoid-over-engineering.md) |
| Add or refactor skills | [`docs/skills/skill-improvement.md`](docs/skills/skill-improvement.md) |

## Documentation conventions

- Update only the skill that matches your change.
- Keep `AGENTS.md` small; do not list deep context here.
- Remove `TODO/FIXME` and work-in-progress markers before merging; move unfinished work to issues.
- Validate documentation changes with `python3 .github/scripts/docs-checks.py`.

## Boundaries

- Do not add Containerfiles or shell-based installers.
- Do not hardcode block device paths in boot configuration.
- Do not put Kubernetes, ZFS, or debug tooling in the base /usr if it can live in a sysext or system container.
- Do not duplicate a fact already in a skill.
- Never hardcode internal-only hostnames or IPs; use `<build-cache-host>` / `<registry-host>:30500` placeholders.
- Never refer to counting or usage metrics as telemetry; call it countme.

## Verification

- [ ] `just validate` passes.
- [ ] `python3 .github/scripts/docs-checks.py` passes.
- [ ] Any changed skill is listed in [`docs/skills/index.md`](docs/skills/index.md).
- [ ] No internal-only hostnames or proprietary names appear in `AGENTS.md` or skills.
