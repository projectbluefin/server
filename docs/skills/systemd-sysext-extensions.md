---
name: systemd-sysext-extensions
description: Extensibility via systemd-sysext and systemd-confext for Bluefin Server. Use when adding, debugging, or documenting system extensions.
metadata:
  type: reference
  status: stable
  last_updated: "2026-09-30"
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
- **NVIDIA Container Toolkit** (`oci/nvidia-container-toolkit-sysext.bst`,
  version in `include/nvidia-container-toolkit.yml`) follows k0s: `ID=_any`,
  its own version, merged as `nvidia-container-toolkit.raw`. It is CDI only:
  `nvidia-ctk`, `nvidia-cdi-hook` and `nvidia-cdi-refresh.{service,path}`,
  which write `/var/run/cdi/nvidia.yaml` at boot for containerd (CDI is on by
  default in containerd 2.x). No `nvidia-container-runtime`, OCI hook or
  `nvidia` runtime class. The refresh is ordered after the driver sysext's
  units without requiring them, and skips on nodes without an NVIDIA GPU.
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

The NVIDIA driver sysexts (`nvidia-open-<branch>_<image-version>.raw`, open
kernel modules only; flavours and pins in `include/nvidia.yml`) are
version-locked the same way and ship in the signed release set; installed
nodes follow the OS with them through the optional `nvidia-open-<branch>`
sysupdate feature, exactly like `zfs`. `just dogfood-nvidia` checks one in
QEMU, and `DOGFOOD_SYSEXT=nvidia scripts/dogfood-install.sh` (or
`zfs,nvidia`, both module sysexts merged together) carries it through an A/B
update and a rollback. Their units skip themselves on a node without an
NVIDIA GPU, and `nvidia-flavour-guard.service` fails when two flavours are
merged.

The toolkit is delivered like k0s: the sysupdate component
`nvidia-container-toolkit` (`/usr/lib/sysupdate.nvidia-container-toolkit.d/`)
stages it in `/var/lib/nvidia-container-toolkit/` behind the
`nvidia-container-toolkit.raw` symlink, outside the directories systemd-sysext
scans, because two versions of an `ID=_any` image there would both merge.
`nvidia-container-toolkit-activate.service` (opt-in, disabled by
`80-bluefin-opt-in.preset`) runs `nvidia-container-toolkit-fetch.service`
(`systemd-sysupdate --component=nvidia-container-toolkit update`) when nothing
is staged, then once per boot copies the image to `/run/extensions/`,
refreshes the merge and starts `nvidia-cdi-refresh.{path,service}` by name. It
must not re-request `multi-user.target` the way `bluefin-sysext-activate.service`
does: two oneshots doing that pull each other back in until start limits fail
units. A node opts in with
`systemctl enable nvidia-container-toolkit-activate.service`; newer toolkit
releases arrive with `systemd-sysupdate --component=nvidia-container-toolkit update`.

The GPU-present path (`nvidia-load.service`, `nvidia-device-nodes.service`,
`nvidia-persistenced.service`) is not exercised by `just dogfood-nvidia`, which
runs on a QEMU guest with no NVIDIA GPU and asserts only that those units skip
themselves. It is verified on real hardware during the GPU rollout phase.

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

## Kernel-module sysexts

**A sysext that carries kernel modules ships no `modules.*` index; the base
image's `/usr/libexec/bluefin-sysext-modules` loads them.** Each module sysext
(OpenZFS, NVIDIA) ships only its own signed modules under
`/usr/lib/modules/<kver>/extra/<name>/`, plus its firmware, units and
userspace; the element build fails if a `modules.*` file would ship. An index
in a sysext would shadow the base image's and every other extension's through
the overlay, so any two module sysexts could not merge together.

`bluefin-sysext-modules MODULE...` builds a module index for the merged tree
under `/run/bluefin/kmods`: `lib/modules/<kver>/` there links `kernel/`,
`extra/`, `updates/` and the depmod inputs (`modules.order`,
`modules.builtin*`) back to `/usr/lib/modules/<kver>/`, and `depmod -b` writes
a fresh index beside them. It then runs `modprobe -d /run/bluefin/kmods -a
MODULE...`, so in-tree dependencies (`drm`, `drm_kms_helper`, ...),
cross-extension dependencies and softdeps resolve, and `modprobe.d` options
and blacklists from `/usr/lib`, `/run` and `/etc` apply as usual (`-d` only
moves the module directory). The kernel reads the same signed `.ko` files
from `/usr`, so lockdown and signature checks are unchanged. The index is
rebuilt only when the merged module set changes, under a lock. `--basedir`
rebuilds it if needed and prints the base directory for manual use, e.g.
`modinfo -b "$(/usr/libexec/bluefin-sysext-modules --basedir)" zfs`. The
helper does nothing until a unit calls it: `zfs-load-module.service` loads
`zfs`, `nvidia-load.service` loads `nvidia nvidia-uvm nvidia-modeset
nvidia-drm`.

Caveat: a bare `modprobe zfs` or `modprobe nvidia` (and udev's modalias
autoloading) only sees the base image's index and reports the module as not
found. The load units run at boot; libzfs only calls `modprobe` when
`/dev/zfs` is missing, and `nvidia-modprobe` only when a module is not
loaded yet.

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
