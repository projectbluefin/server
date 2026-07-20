---
name: k3s-sysext
version: "1.0"
last_updated: "2026-07-20"
tags: ['k3s', 'sysext', 'kubernetes']
description: "Build, ship, and enable the k3s systemd-sysext extension for Bluefin Server."
metadata:
  context7-sources:
    - /systemd/systemd
---

# k3s systemd-sysext

Use this skill when working on the k3s systemd-sysext extension shipped as an
optional overlay for Bluefin Server.

## When to Use

- Bumping the pinned k3s binary version or its SHA256.
- Modifying the sysext image contents (`files/k3s/sysext/`).
- Changing k3s tuning defaults or how they are seeded into `/etc/rancher/k3s/`.
- Adding or changing the sysupdate transfer definition
  (`files/os/sysupdate.d/70-k3s.transfer`).
- Debugging why a host cannot pull, merge, or start k3s.

## When NOT to Use

- General OS image composition questions (use `ddi-installer.md` or
  `avoid-over-engineering.md`).
- systemd-sysupdate signature verification (use
  `systemd-sysupdate-verification.md`).
- Kubernetes workload or cluster architecture questions outside the sysext
  packaging.

## Architecture

Bluefin Server's base DDI image is distroless and read-only. k3s is **not**
baked into the OS stack. Instead it is delivered as a `systemd-sysext` EROFS
image that overlays `/usr` at runtime. This keeps the base DDI small and lets
operators opt into Kubernetes on a per-host basis.

Design choices:

- **BST-pure build.** `elements/k3s/k3s-bin.bst` fetches the upstream release
  binary directly from GitHub; the get.k3s.io installer is not used.
- **Neutral tuning only.** The sysext ships a small set of controller/kubelet
  timing defaults in `/usr/share/bluefin/k3s/50-bluefin-tuning.yaml` and seeds
  them into `/etc/rancher/k3s/config.yaml.d/` with a `tmpfiles.d` `C+` line.
  Everything else is stock k3s: vxlan flannel, Traefik, ServiceLB, and SQLite.
- **Role chosen at provisioning time.** Both `k3s.service` and
  `k3s-agent.service` are installed inside the sysext, but neither is enabled.
  Provisioning enables exactly one unit and writes `/etc/rancher/k3s/config.yaml`
  with the server or agent role.
- **Flatcar sysext pattern.** The extension uses `ID=_any` in its release
  metadata so it merges on any host image.
- **OTA delivery.** A `systemd-sysupdate` transfer file
  (`files/os/sysupdate.d/70-k3s.transfer`) is installed in the base OS so hosts
  can pull new k3s sysext releases from GitHub Releases.

## Repository Layout

| Path | Purpose |
|------|---------|
| `elements/k3s/k3s-bin.bst` | Pins the upstream `k3s` binary release and SHA256. |
| `elements/oci/k3s-sysext.bst` | Builds the EROFS sysext image (`k3s-<release-version>.raw`). |
| `files/k3s/sysext/k3s.service` | systemd unit for the k3s server. Not enabled. |
| `files/k3s/sysext/k3s-agent.service` | systemd unit for the k3s agent. Not enabled. |
| `files/k3s/sysext/extension-release.k3s` | Sysext identity (`ID=_any`). |
| `files/k3s/sysext/50-bluefin-tuning.yaml` | Bluefin tuning defaults shipped in `/usr`. |
| `files/k3s/sysext/k3s-bluefin.conf` | `tmpfiles.d` rule that copies tuning defaults to `/etc`. |
| `files/os/sysupdate.d/70-k3s.transfer` | sysupdate transfer track for the k3s sysext. |
| `Justfile` | `build-sysext` / `export-sysext` targets. |
| `.github/workflows/build.yml` | Builds, signs, and publishes sysext assets. |

## Build Outputs

`elements/oci/k3s-sysext.bst` produces:

- `k3s-<release-version>.raw` — uncompressed EROFS sysext image.
- `k3s-<release-version>.raw.zst` — zstd-compressed release asset.
- `SHA256SUMS` — checksum manifest for the compressed asset.

`<release-version>` is the OS release version from `%{release-version}`
(e.g. `25.08.13`), the same FSDK-derived axis used for the installer and DDI
assets. The k3s upstream version lives only in
`files/k3s/sysext/extension-release.k3s` as `VERSION_ID`.

## Justfile Commands

```
just validate              # resolve the element graph (includes oci/k3s-sysext.bst)
just build-sysext          # build oci/k3s-sysext.bst
just export-sysext         # export sysext artifacts to dist/sysext/
```

`export-sysext` checks out the BuildStream artifact into `dist/sysext/` and
prints the resulting files.

## Release and Signing

On pushes to `main`, the workflow in `.github/workflows/build.yml`:

1. Runs `just build-sysext` and `just export-sysext` (which writes per-directory
   manifests such as `dist/sysext/SHA256SUMS` for local use).
2. Assembles a combined release manifest under `dist/release/` containing the
   installer `.raw.zst`, UKI `.efi`, DDI `.raw.zst`, and k3s sysext `.raw.zst`
   artifacts.
3. Generates `dist/release/SHA256SUMS` for all assets and signs it with the
   `SYSUPDATE_SIGNING_KEY` secret, producing `dist/release/SHA256SUMS.gpg`.
4. Uploads everything in `dist/release/` to the matching
   `installer-v<release-version>` GitHub Release.

`systemd-sysupdate` fetches `<Path>/SHA256SUMS` from the static `Path=` defined
in each transfer file and verifies the detached `.gpg` signature before using
any asset. The combined manifest is required so that the same `SHA256SUMS` file
satisfies all transfer definitions.

The base OS already ships the public keyring and the transfer definition, so
existing hosts can pull the update via `systemd-sysupdate`.

## Bumping the k3s Version

Two places must change together when the upstream k3s release moves:

1. **Binary pin and checksum** in `elements/k3s/k3s-bin.bst`:
   - Update the `url:` release tag and the `ref:` SHA256 from the upstream
     `sha256sum-amd64.txt` asset.
   - The URL must URL-encode the `+` in the tag (`%2B`).

2. **Extension metadata** in `files/k3s/sysext/extension-release.k3s`:
   - Update `VERSION_ID=` to the real upstream tag (with `+` intact).

The sysext artifact filename is keyed to the OS release version
(`%{release-version}`), so it does not change when k3s itself is bumped.
Renovate can track the remote source in `k3s-bin.bst`, but the
`extension-release.k3s` file must still be kept in sync manually (or by a
Renovate post-update step) because it is a local file.

After changing these values, run `just validate` to confirm the element graph
still resolves.

## Enabling k3s on a Host

Because the OS image has no shell and `/usr` is read-only, role selection is
done with systemd unit enablement and a drop-in config file, not by running the
k3s installer.

### Server

1. Write the server token and any role-specific settings to
   `/etc/rancher/k3s/config.yaml`. This file lives on the writable `/etc`
   overlay.

2. Enable the server unit:
   ```
   systemctl enable k3s.service
   ```

3. Reboot or start `k3s.service`.

### Agent

1. Write the agent config to `/etc/rancher/k3s/config.yaml`, including at least
   `server:` and `token:`.

2. Enable the agent unit:
   ```
   systemctl enable k3s-agent.service
   ```

3. Reboot or start `k3s-agent.service`.

The tuning defaults from `50-bluefin-tuning.yaml` are copied into
`/etc/rancher/k3s/config.yaml.d/` on first boot by the `tmpfiles.d` rule. They
are not merged by k3s; they are plain YAML files in the config directory. Admins
can override a value by editing the file in `/etc` or by providing their own
`/etc/rancher/k3s/config.yaml.d/` drop-in.

## Common Gotchas

- **Neither unit is enabled.** Both services are shipped in `/usr/lib/systemd/system`
  inside the sysext but no symlink is created in any target's `wants.d`. A host
  must explicitly `systemctl enable` the role it needs.
- **No shell in the OS image.** `k3s.service` no longer runs any `/bin/sh`
  `ExecStartPre` checks. It loads `br_netfilter` and `overlay` directly with
  `/sbin/modprobe`, matching the agent unit.
- **No shell means no `curl | sh`.** Do not try to use the upstream k3s install
  script. Use unit enablement and `/etc/rancher/k3s/config.yaml` instead.
- **Tuning defaults live in `/usr` and are copied, not merged.** The `C+`
  tmpfiles rule creates `/etc/rancher/k3s/config.yaml.d/50-bluefin-tuning.yaml`
  from `/usr/share/bluefin/k3s/50-bluefin-tuning.yaml` only if the destination
  does not already exist. To override, edit the `/etc` copy directly.
- **Role-specific environment files are optional.** Both units source
  `/etc/default/%N`, `/etc/sysconfig/%N`, and `/etc/systemd/system/%N.env`.
  These can be used for settings that must not live in `config.yaml`.
- **`ID=_any` in extension-release.** The sysext merges on any host image. If
  you ever scope it to a specific OS version, update both `extension-release.k3s`
  and the base OS `os-release`.
- **The base DDI does not include k3s.** `elements/bluefin-server/os-stack.bst`
  does not depend on `k3s-sysext.bst`. k3s is delivered OTA or dropped into
  `/var/lib/extensions/` by provisioning.

## Runtime Testing Without a Lab VM

Both halves of the delivery path can be exercised on a workstation with podman;
neither requires touching the host OS.

### OTA discovery and download (systemd-sysupdate)

Copy `files/os/sysupdate.d/70-k3s.transfer` into a scratch `sysupdate.d/`,
rewrite only the `[Target] Path=` to a scratch directory, then run inside a
Fedora container:

```bash
podman run --rm -v "$SCRATCH:/scratch:z" quay.io/fedora/fedora:latest bash -c '
  dnf -yq install systemd-udev systemd-container >/dev/null
  /usr/lib/systemd/systemd-sysupdate --definitions=/scratch/sysupdate.d list
  /usr/lib/systemd/systemd-sysupdate --definitions=/scratch/sysupdate.d update'
```

- `systemd-sysupdate` is in `systemd-udev`; the `systemd-pull` helper needed
  for `url-file` sources is in `systemd-container`. Both are required.
- To test the full trust chain, copy `files/os/sysupdate-keys/import-pubring.pgp`
  to `/usr/lib/systemd/import-pubring.pgp` in the container; the live release
  `SHA256SUMS.gpg` must verify. Only use `Verify=no` (a `[Transfer]` option)
  for structural tests, never in shipped transfers.

### Sysext merge and unit checks

Run a privileged systemd container, place the decompressed image, and merge:

```bash
podman run -d --name sysext-test --privileged --cgroupns=host \
  -v "$SCRATCH:/test:z" quay.io/fedora/fedora:latest \
  bash -c 'dnf install -y systemd erofs-utils && exec /usr/sbin/init'
podman exec sysext-test bash -c '
  mount --make-shared /usr && mount --make-shared /opt
  erofsfuse /test/k3s.raw /mnt && cp -a /mnt/. /var/lib/extensions/k3s/
  systemd-sysext merge && systemd-sysext status
  k3s --version
  systemd-tmpfiles --create
  cat /etc/rancher/k3s/config.yaml.d/50-bluefin-tuning.yaml
  systemctl list-unit-files | grep k3s'
```

- Rootless podman cannot loop-mount the `.raw` directly (`Permission denied`
  reading image metadata); extract via `erofsfuse` into a
  `/var/lib/extensions/<name>/` directory instead. This is a test-environment
  limitation, not an image defect.
- `systemd-sysext merge` requires `/usr` and `/opt` to be shared mount points
  inside the container (`mount --make-shared`).
- `systemctl start k3s` will fail in a nested container on modprobe and
  overlayfs snapshotter errors. That is environmental; full k3s startup
  verification needs a real VM or bare metal.

## Verification

- [ ] `elements/k3s/k3s-bin.bst` uses a real upstream k3s release URL and a
      matching SHA256.
- [ ] `files/k3s/sysext/extension-release.k3s` has `VERSION_ID=` set to the real
      upstream tag (with `+`).
- [ ] `files/k3s/sysext/extension-release.k3s` has `ID=_any`.
- [ ] Both `k3s.service` and `k3s-agent.service` are present and neither is
      enabled by default.
- [ ] `k3s.service` uses `/sbin/modprobe` ExecStartPre lines, not `/bin/sh`.
- [ ] `files/k3s/sysext/k3s-bluefin.conf` seeds tuning defaults with a `C+` line
      targeting `/etc/rancher/k3s/config.yaml.d/`.
- [ ] `files/os/sysupdate.d/70-k3s.transfer` uses a static `Path=` and OS-release
      `@v` patterns (`k3s-@v.raw.zst`, `k3s-@v.raw`) plus `CurrentSymlink=k3s.raw`.
- [ ] `just validate` resolves the element graph after any k3s version bump,
      including `oci/k3s-sysext.bst`.
- [ ] `just build-sysext && just export-sysext` produces `k3s-<release-version>.raw`,
      `k3s-<release-version>.raw.zst`, and `SHA256SUMS`.
- [ ] CI uploads a combined `dist/release/SHA256SUMS` and `SHA256SUMS.gpg`
      alongside all release assets.
