# Documentation Audit Report — Bluefin Server

Date: 2026-07-20
Scope: `README.md`, `CONTRIBUTING.md`, `docs/skills/*.md`, and the stale
`docs/superpowers/` plans/specs.
Sources of truth: `Justfile`, `elements/`, `.github/workflows/build.yml`, `files/`,
and the official freedesktop.org systemd 261.1 man pages.

## Context7 status

No Context7 MCP server is registered in this environment. I indexed the official
freedesktop.org systemd 261.1 man pages instead:

- `systemd-sysinstall`
- `systemd-repart`
- `repart.d`
- `bootctl`
- `ukify`
- `systemd-sysinstall.service`
- `systemd-sysupdate`
- `sysupdate.d`
- `systemd-creds`
- `systemd-nspawn`
- `systemd-sysext`

## Findings and actions

### Top-level docs rewritten

- `README.md` now describes Bluefin Server (DDI-first FSDK server OS, real `just`
  targets, system containers, CI release pipeline) instead of the copied
  `fsdk-containers` OCI image narrative.
- `CONTRIBUTING.md` now points to server-appropriate validation (`just validate`,
  local installer/DDI builds) and server skill routing.

### DDI installer skill refreshed

`docs/skills/ddi-installer.md` was aligned with
`elements/oci/bluefin-server-installer.bst` and the systemd 261.1 docs:

- Installer-media ESP is 1 GiB fixed, data partition is auto-sized.
- Unattended path uses `--reboot=no` plus service `SuccessAction=poweroff`.
- Interactive path is documented, with a note that the reference UKI hardcodes
  `unattended` for headless testing.
- Initrd assembly now uses gzip cpio and the actual UKI cmdline.
- Upstream man-page cross-references added.

### Stale OCI/fsdk-containers skills removed

The following files were inherited from `fsdk-containers` and did not apply to
Bluefin Server; they were deleted and removed from `docs/skills/README.md`:

- `docs/skills/add-new-image.md`
- `docs/skills/artifacthub-automation.md`
- `docs/skills/nspawn-machine-image.md`
- `docs/skills/signing-and-sbom.md`
- `docs/skills/slim-an-image.md`
- `docs/skills/verify-distroless.md`
- `docs/brew-nspawn-container-spec.md`
- `docs/superpowers/plans/*`
- `docs/superpowers/specs/*`

### Remaining skills updated

- `docs/skills/README.md` — routing table updated to list only current server
  skills.
- `docs/skills/bump-fsdk-version.md` — description fixed; `just verify` replaced
  with `just validate` / local installer/DDI builds.
- `docs/skills/ci-tooling.md` — rewritten for the server release workflow in
  `.github/workflows/build.yml`; removed OCI signing/ORAS/cosign sections.
- `docs/skills/gap-analysis-architecture.md` — `.raw.xz` corrected to `.raw.zst`;
  clarified that A/B dual slots are planned, not implemented.
- `docs/skills/skill-improvement.md` — generic `oci-builder` example replaced
  with a server-relevant build-sandbox note; `just verify` → `just validate`.
- `docs/skills/systemd-sysext-extensions.md` — extended with correct paths
  (`/var/lib/extensions/`, `/var/lib/confexts/`), `systemd-sysext refresh`, and
  Flatcar compatibility notes.
- `docs/skills/system-containers.md` — expanded with the actual
  `files/bin/system-container` helper commands and `machinectl` workflow.

## Validation

- `just --list` confirms all `just` targets referenced in the docs exist.
- `README.md` and `CONTRIBUTING.md` no longer reference OCI images or
  `fsdk-containers`.
- No docs/skills file references a deleted skill or `just verify` anymore.
- `actionlint .github/workflows/build.yml` reports three pre-existing findings
  in the workflow (untrusted expression and shellcheck style warnings) that were
  not introduced by this documentation change.
