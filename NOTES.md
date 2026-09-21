# Bluefin Server — Developer Notes & Vocabulary

## Domain & Repository
- **Repository**: `projectbluefin/server` (upstream of Bluefin Server OS).
- **Core Architecture**: FSDK 26.08 (`components/*`), immutable XFS DDI OS (`oci/bluefin-server-ddi.bst`), systemd-sysinstall offline raw disk installer (`oci/bluefin-server-installer.bst`), and optional Kubernetes `systemd-sysext` (`oci/kubernetes-sysext.bst`).
- **Release Automation**: Driven by Renovate dependency updates and merges to `main`. Pushes trigger `.github/workflows/build.yml`.

## Tooling Stack
- **BuildStream (bst2)**: Invoked inside FSDK `bst2` container via Podman (`just bst`).
- **Justfile**: Central command orchestrator (`just validate`, `just build-ddi`, `just export-ddi`, `just build-installer`, `just export-installer`, `just build-sysext`, `just export-sysext`, `just test-unit`, `just show-me-the-future`).
- **Testing**: `pytest tests/unit` and `bats tests/unit`.
- **Docs Enforcement**: `python3 .github/scripts/docs-checks.py` checks skill YAML frontmatter, line budgets, draft/todo markers, and internal markdown links.
- **GitHub CLI (`gh`)**: Monitors workflow runs (`gh run list/view`), releases (`gh release list/create/upload`), and PRs.

## Release & Sysupdate Lifecycle
- **Version Source**: Pinned FSDK point release in `elements/freedesktop-sdk.bst` (e.g. `26.08.0`).
- **Kubernetes Sysext**: Upstream `kubeadm`/`kubelet`/`kubectl` plus CNI plugins (`oci/kubernetes-sysext.bst`). Emits `kubernetes-@v.raw.zst`. Version axis lives in `include/kubernetes.yml`.
- **Sysupdate Contracts** (`files/os/sysupdate.d/` plus the `kubernetes` component directory):
  - `50-root.transfer`: OS rootfs DDI (`bluefin-server-ddi-@v.raw.zst`).
  - `60-uki.transfer`: Boot UKI (`bluefin-server-@v.efi`).
  - `files/os/sysupdate.kubernetes.d/70-kubernetes.transfer`: Kubernetes sysext (`kubernetes-@v.raw.zst`), on a minor-pinned track.
- **Signing & Manifest**: `dist/release/SHA256SUMS` signed via detached GPG (`SHA256SUMS.gpg`) using secret `SYSUPDATE_SIGNING_KEY`.
