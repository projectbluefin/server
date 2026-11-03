---
name: sysext-kernel-modules
description: How kernel-module-carrying sysexts (OpenZFS, NVIDIA) load modules via /usr/libexec/bluefin-sysext-modules. Load when working on a sysext that ships kernel modules, or debugging module loading under a merged extension set.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-30"
  context7-sources:
    - /systemd/systemd
---
# Kernel-module sysexts

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

## See also

- [systemd-sysext-extensions.md](systemd-sysext-extensions.md) — extension
  identity, loading, and version matching.
- [nvidia-sysext.md](nvidia-sysext.md) — the NVIDIA module sysexts.
