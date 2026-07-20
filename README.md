# Bluefin Server

**An FSDK-based, image-based Linux server OS.**

Bluefin Server targets the same use-case space as Flatcar Linux, Fedora CoreOS,
and Talos, but it is built from scratch with [BuildStream 2](https://buildstream.build/)
from [freedesktop-sdk](https://freedesktop-sdk.freedesktop.org/) components.

It is [DDI first](https://0pointer.net/blog/fitting-everything-together.html):
the OS payload is a compressed XFS DDI filesystem image that is deployed by an
offline, systemd-native installer.

## What it is

- **Image-based updates and atomic rollbacks** via A/B partition slots and
  `systemd-sysupdate`.
- **DDI-first delivery** — the installer embeds the OS payload as a data
  partition; no network is required at install time.
- **Minimal, distroless OS image** — no shell in the running rootfs.
- **systemd-native installer** — `systemd-sysinstall` provides the interactive
  terminal UI and `systemd-repart` handles partitioning and block-copy DDI
  placement.
- **Fully automated GitOps-driven builds** — Renovate tracks FSDK point releases,
  GitHub Actions builds and publishes DDI + installer + k3s sysext assets.

## Build model

All `just` targets run BuildStream inside the FSDK `bst2` container via `podman`;
you do not install BuildStream locally.

```sh
just validate              # resolve the element graph
just version               # print the FSDK-derived release version
just tags                  # print latest / YY.MM / YY.MM.PP tags
just build-ddi             # build the OS DDI payload
just export-ddi            # export DDI artifacts to dist/ddi/
just build-installer       # build the live installer disk image
just export-installer      # export installer + UKI to dist/
just build-sysext          # build the optional k3s systemd-sysext
just export-sysext         # export sysext artifacts to dist/sysext/
just flash-installer       # write the installer image to a USB device
just show-me-the-future    # end-to-end QEMU installer smoke test
```

The merge contract for element graph changes is `just validate`.

## Versioning

There is no separate application version axis. Versions follow the pinned FSDK
release in `elements/freedesktop-sdk.bst`:

- `:latest` — rolling, every publish
- `:25.08` — FSDK minor line
- `:25.08.13` — FSDK point release, treated as immutable

Installers, DDI payloads, and the k3s sysext all use the same `release-version`
value from `project.conf`.

## System containers

System containers are transparent, systemd-managed toolboxes. They run via
`systemd-nspawn` and are operated with `machinectl` plus the
`system-container` helper shipped in the OS image at `/usr/bin/system-container`.

First-time setup:

```sh
sudo machinectl import-tar <image-url> homebrew
sudo system-container start homebrew
sudo system-container enter homebrew
```

When finished:

```sh
exit
sudo system-container stop homebrew
```

To reset and start over:

```sh
sudo system-container reset homebrew
sudo machinectl import-tar <image-url> homebrew
sudo system-container start homebrew
```

`system-container` is a thin wrapper around `machinectl start|poweroff|shell|remove`.

## CI / Release pipeline

GitHub Actions compiles the full project and publishes release assets automatically.

| Trigger | Workflow / Job | What happens |
|---|---|---|
| Pull request | `build.yml` / `build-and-release` | Resolves the element graph (`just validate`) and performs a full BuildStream compile to verify stability. Tracks Renovate refs if opened by Renovate. |
| Push to `main`, `workflow_dispatch` | `build.yml` / `build-and-release` | Builds DDI, live installer, target UKI, and k3s sysext on `/mnt` storage, signs a combined `SHA256SUMS` manifest, and uploads everything to a GitHub Release tagged `installer-v<FSDK-RELEASE>`. |

No PATs or `repository_dispatch` are used; Renovate drives dependency updates.
See [`docs/skills/ci-tooling.md`](docs/skills/ci-tooling.md) for workflow conventions.

## License

Apache-2.0.
