---
name: systemd-sysext-extensions
description: Extensibility via systemd-sysext and systemd-confext for Bluefin Server. Use when adding, debugging, or documenting system extensions.
metadata:
  type: reference
  status: stable
  last_updated: "2026-09-27"
  context7-sources:
    - /systemd/systemd
---
# Extensibility via systemd-sysext

Bluefin Server's base OS includes bash for login and bring-up, while heavy
developer and debug tools live in sysexts or system containers. For debugging,
monitoring, or runtime modifications, use systemd-sysext to overlay package
bundles into `/usr` and `/opt`, or systemd-confext to overlay files into `/etc`.

## Canonical scope

This file is the canonical home for extension-loading behavior, compatibility
checks, and runtime management. Future roadmap items for deeper integration
with the provisioning flow remain in [architecture-roadmap.md](architecture-roadmap.md).

## Where extensions live

System extensions are searched in:

- `/etc/extensions/`
- `/run/extensions/`
- `/var/lib/extensions/` (the primary location for persisted extension images)

Configuration extensions (confext) are searched in:

- `/run/confexts/`
- `/var/lib/confexts/`
- `/usr/lib/confexts/`
- `/usr/local/lib/confexts/`

Placing an empty directory named like the extension (without `.raw`) under
`/etc/extensions/` masks an extension of the same name in a lower-precedence
directory.

## Extension identity and version matching

The base OS `/usr/lib/os-release` identifies as `ID=bluefin-server` with
`VERSION_ID=<image-version>` (`elements/bluefin-server/os-release.bst`). A
sysext merges when its `extension-release` metadata matches the host `ID=` (or
uses `ID=_any`) and, when it pins `VERSION_ID=`, the host version.

The first-party extensions make opposite choices:

- **k0s** (`files/k0s/sysext/extension-release.k0s`) uses `ID=_any` and does
  not pin the image version, so it merges on any host image.
- **OpenZFS and KubeStellar** are version-locked to the image: their
  extension-release file is named after the versioned image file
  (`extension-release.zfs_<image-version>`,
  `extension-release.kubestellar_<image-version>`) with `ID=bluefin-server`
  and `VERSION_ID=<image-version>`, because the ZFS kernel modules only load
  on the exact kernel they were built against (and the KubeStellar stack is
  validated against one image). Several versions sit side by side in
  `/var/lib/extensions` as `zfs_<ver>.raw` / `kubestellar_<ver>.raw`;
  systemd-sysext merges only the one matching the booted image, so an A/B
  rollback keeps its ZFS. Installed nodes receive them in lock-step with OS
  updates through the optional `zfs` / `kubestellar` sysupdate features
  (see `systemd-sysupdate-verification.md`); diskless nodes get them from
  Ignition, which writes `/etc/extensions/<name>_<ver>.raw` with a sha256
  verification hash.

Compatible third-party userspace extensions are supported and encouraged.
Prefer an existing [Flatcar System Extension Bakery](https://extensions.flatcar.org/)
image over rebuilding an equivalent bundle when it satisfies the host's runtime
contract. This does not permit other-distro binaries in the base OS image.

Inspect the downloaded image's `extension-release` before activation. An image
using `ID=_any` with the matching architecture can merge normally; an image
locked to another distribution is not automatically compatible. Do not use
`--force` as an installation default or bypass kernel-module version checks.
Third-party userspace extensions still depend on the host's kernel features,
libraries, writable paths, and runtime configuration; verify their binaries and
exercise the intended workload after merging and after reboot.

Pin the image version and verify its digest before merging. A checksum fetched
from the same publisher proves integrity, not publisher authenticity. Use signed
manifests or verified provenance where available; do not silently enable
unattended `Verify=false` updates. Keep extension update paths and symlinks
consistent with the active merge path; see
[systemd-sysupdate-verification.md](systemd-sysupdate-verification.md).

### Flatcar Kubernetes and containerd runtime notes

The inspected bakery Kubernetes `v1.37.1` and containerd `2.4.1` images use
`ID=_any`, `ARCHITECTURE=x86-64`, and `EXTENSION_RELOAD_MANAGER=1`. They merge
normally on the matching Bluefin Server architecture; inspect every selected
release rather than assuming all bakery extensions have the same metadata.

**Updates and trust.** The bakery's transfer examples use `Verify=false` and
do not supply the signed manifest/keyring contract used by Bluefin's updater.
Checking bakery `SHA256SUMS` detects corruption but does not independently
authenticate the publisher. Keep direct unsigned updates operator-reviewed:
pin approved digests and verify provenance/signatures when available. For
automatic product delivery, include approved payloads in the signed Bluefin
release inventory instead of pulling unchecked upstream releases on nodes.
Never disable the base `systemd-sysupdate` service/timer to stop component
pulls; remove only the component-update drop-ins. Keep transfer targets and
active symlinks consistent, and do not shadow them with higher-precedence
`/etc/extensions` links.

**Containerd and kubelet.** The inspected containerd image's unit sets
`CONTAINERD_CONFIG=/usr/share/containerd/config.toml`. An `/etc` config alone
does not override it. Use a systemd unit drop-in with:

```ini
[Service]
Environment=CONTAINERD_CONFIG=/etc/containerd/config.toml
```

For containerd 2.4.x, the seeded TOML uses `version = 4` and sets
`SystemdCgroup = true` under
`[plugins."io.containerd.cri.v1.runtime".containerd.runtimes.runc.options]`.
The quoted plugin name is required: omitting quotes creates unrelated nested
tables that containerd ignores. Confirm the running unit's config path and its
effective config dump, not just the override file.

After changing the runtime config, reload systemd and restart containerd,
then restart kubelet. Modern kubelet can obtain and cache its cgroup driver
from CRI at startup. Confirm its journal reports `cgroupDriver="systemd"` and
create a fresh pod. Restarting only containerd can leave kubelet using its old
cgroupfs driver; new pod sandboxes then fail with
`expected cgroupsPath to be of format "slice:prefix:name"`. Existing Ready
pods do not prove new sandbox creation works. Verify again after reboot.

## Adding an extension

The k0s sysext is the built-in example; a compatible extension layers the same
way.

```bash
# Download an extension image to the persistence directory
wget <extension-url> -O /var/lib/extensions/myext.raw

# Merge it into the running system
systemd-sysext merge

# Verify it is active
systemd-sysext status
```

To pick up newly dropped extension images automatically, refresh instead of
manually merging:

```bash
systemd-sysext refresh
```

The `systemd-sysext.service` unit performs a refresh at boot, so extensions in
`/var/lib/extensions/` become available without manual intervention. One
caveat: the refresh happens after PID 1 has built the boot transaction, so
`[Install]` symlinks shipped inside a sysext (for example `zfs.target` in
`multi-user.target.wants`) are not part of it. The enabled oneshot
`bluefin-sysext-activate.service` runs after `systemd-sysext.service` and
re-requests `multi-user.target`, which adds jobs for the now-visible wants;
that is how `zfs.target` comes up at boot when the ZFS sysext is merged.

## Removing an extension

```bash
rm /var/lib/extensions/myext.raw
systemd-sysext refresh
```

## Key constraints

- Keep extensions as simple read-only bundles. Do not ship a `/usr/lib/os-release`
  file inside an extension; it would override the host OS version metadata.
- The extension image format is the same one `systemd-repart` and `systemd-sysext`
  accept: a GPT/EROFS/directory tree that contains `/usr/` and/or `/opt/`.
- For files that belong under `/etc/`, ship a **confext** and place it under
  `/var/lib/confexts/`, then use `systemd-confext merge`/`refresh`.

## Debugging

```bash
# List discovered extensions
systemd-sysext list

# Show merge state and any compatibility errors
systemd-sysext status

# Force a merge ignoring version mismatches (debugging only)
systemd-sysext merge --force
```

## See also

- [k0s-sysext.md](k0s-sysext.md) for the built-in Kubernetes extension
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary (Sysext definition).
- `systemd-sysext(8)`, `systemd-confext(8)`
