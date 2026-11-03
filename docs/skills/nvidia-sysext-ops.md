---
name: nvidia-sysext-ops
description: Running NVIDIA GPU nodes on Bluefin Server. Load when enabling the driver or Container Toolkit sysexts on a node, evicting nouveau on mixed-generation hosts, wiring containerd's CDI/nvidia runtime handler, or installing the GPU Operator chart.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-30"
  context7-sources:
    - /systemd/systemd
---
# NVIDIA GPU nodes

Building the sysexts: [nvidia-sysext.md](nvidia-sysext.md). This file is the
runtime side: enabling them on a node and what runs once they merge.

## Choosing the sysexts

- Installed node: enable the `nvidia-open-<branch>` sysupdate feature
  ([systemd-sysupdate-verification.md](systemd-sysupdate-verification.md)) and
  `nvidia-container-toolkit-activate.service` (systemd-sysext-extensions.md).
- Booty: list `nvidia-open-<branch>` and `nvidia-container-toolkit` in the
  host's `extensions` ([booty-integration.md](booty-integration.md)).

A node without an NVIDIA GPU can merge both. `nvidia-load.service` skips
itself (its `ExecCondition=` finds no PCI display controller, class `0x03`,
from vendor `0x10de`), `nvidia-device-nodes.service` and
`nvidia-persistenced.service` then skip on their conditions, and the
toolkit's drop-in skips `nvidia-cdi-refresh.service` on the same PCI check.
`nvidia-ldconfig.service` and the flavour guard run on every node.

## nouveau and mixed-generation hosts

The base kernel no longer builds nouveau (`patches/freedesktop-sdk/0009`
turns off the GPU drivers that need firmware the image never ships), so no
driver holds an NVIDIA GPU when the sysext merges. The eviction below stays
as a guard for a kernel that does build it: there udev binds nouveau to
every NVIDIA GPU before systemd-sysext merges the driver sysext, the
sysext's `/usr/lib/modprobe.d/nvidia.conf` (`blacklist nouveau`, `options
nouveau modeset=0`) only covers loads after the merge, and nvidia refuses a
GPU another driver holds (`NVRM: GPU 0000:01:00.0 is already bound to
nouveau`, then `could not insert 'nvidia': No such device`).

`nvidia-load.service` runs `/usr/libexec/nvidia-load`
(`files/nvidia/sysext/nvidia-load`), which: lists the NVIDIA display
controllers and, when nouveau holds any, runs `modprobe -r nouveau`
(nothing has opened `/dev/dri` this early), writing each
held address to `/sys/bus/pci/drivers/nouveau/unbind` when the module is in
use; loads `nvidia nvidia-uvm nvidia-modeset nvidia-drm` through
`bluefin-sysext-modules`; succeeds when `/proc/driver/nvidia/gpus/` lists at
least one GPU, warning about every NVIDIA GPU nvidia does not drive (the
open modules are Turing and newer only, so a Pascal card in a mixed box
stays unused while the supported one comes up); fails only when the loader
failed or no GPU came up. `tests/unit/nvidia-load_test.bats` runs it
against a fake `/sys` and `/proc/driver/nvidia/gpus`.

## Containers (CDI)

Once the toolkit is merged, and after `nvidia-ldconfig.service` and
`nvidia-device-nodes.service`, `nvidia-cdi-refresh.service` runs
`nvidia-ctk cdi generate`, which writes `/var/run/cdi/nvidia.yaml`.
containerd 2.x has CDI on by default and reads that directory, so a plain
pod that asks for a CDI device gets it from `runc`: the default runtime
stays `runc` and there is no OCI hook.

## The `nvidia` runtime handler

The toolkit also ships `/usr/bin/nvidia-container-runtime`, a symlink to
upstream's `nvidia-container-runtime.cdi` (`cmd/nvidia-container-runtime.cdi`:
the runtime wrapper with its mode fixed to `cdi` in code). It reads the
container's device requests (`NVIDIA_VISIBLE_DEVICES=all`, a fully qualified
`nvidia.com/gpu=...`, or CDI annotations), injects the matching devices from
`/etc/cdi` and `/var/run/cdi` into the OCI spec and execs `runc` from
`PATH`. Upstream's defaults already are `default-kind = "nvidia.com/gpu"`
and those spec directories, so no `/etc/nvidia-container-runtime/config.toml`
ships or is needed (one is honoured for `log-level`, `debug` and the like;
its `mode` is ignored). The plain `nvidia-container-runtime`, whose default
`mode = "auto"` resolves to the legacy stack (`nvidia-container-runtime-hook`
and `libnvidia-container`, neither of which ships), is not built.

For the kubeadm sysext the toolkit ships
`/usr/share/bluefin/containerd/conf.d/nvidia-container-runtime.toml`
(`files/nvidia-container-toolkit/sysext/containerd-nvidia-container-runtime.toml`),
which the kubeadm containerd config imports by glob
([kubeadm-sysext.md](kubeadm-sysext.md)): a `runtimes.nvidia` entry of type
`io.containerd.runc.v2` with `BinaryName = "/usr/bin/nvidia-container-runtime"`
and `SystemdCgroup = true`, and no `default_runtime_name`. A node without
the toolkit has no `nvidia` handler; a node with it serves
`RuntimeClass nvidia`. k0s's containerd reads `/etc/k0s/containerd.d/`
instead and is not wired up here.

containerd resolves `imports` once, at config load. A diskless node merges
the toolkit before containerd starts, but an installed node merges it later
(the activate unit waits for the network fetch) while containerd is already
up, so the glob would match nothing. `nvidia-container-toolkit-activate`
therefore runs `systemctl try-restart containerd.service` after the refresh;
containers survive it (`KillMode=process`). `try-restart` only acts on an
*active* unit — systemd turns it into a no-op for a unit that is inactive or
still `activating` — so the activate unit is ordered `After=containerd.service`
(ordering only, no `Wants=`: a node without the kubeadm sysext has no such
unit). Otherwise, on a node whose `.raw` is already seeded the fetch unit is
skipped, the merge runs while containerd is still `activating` (`Type=notify`),
the restart is skipped, and `RuntimeClass nvidia` keeps failing until someone
restarts containerd by hand. A node that rewrites
`/etc/containerd/config.toml` afterwards still restarts containerd itself.

`nvidia-container-runtime.cdi` honours `NVIDIA_VISIBLE_DEVICES` even for
unprivileged containers (upstream defaults
`accept-nvidia-visible-devices-envvar-when-unprivileged = true`), so with a
cluster-wide `RuntimeClass nvidia` any pod asking for that class and
`NVIDIA_VISIBLE_DEVICES=all` claims every GPU, bypassing device-plugin
accounting. The operands rely on it, so nothing here changes it; a cluster
can tighten it in `/etc/nvidia-container-runtime/config.toml` (plus policy on
the RuntimeClass) at the cost of operands that ask for devices by env var.

## GPU Operator

The driver and the CDI spec come from the sysexts, so the GPU Operator chart
installs neither:

```yaml
driver:
  enabled: false   # the driver sysext
toolkit:
  enabled: false   # the toolkit sysext and its CDI spec
cdi:
  enabled: true    # the chart's default since v25.10.0
```

That is `--set driver.enabled=false --set toolkit.enabled=false --set
cdi.enabled=true`. Time-slicing and MIG are GPU Operator settings
(`devicePlugin.config`, `mig.strategy`), not changes to the sysexts.

The operator schedules its own operands (device plugin, GPU feature
discovery, DCGM exporter, validator) with `runtimeClassName: nvidia`
(`operator.runtimeClass`) and `NVIDIA_VISIBLE_DEVICES=all`, and creates the
`RuntimeClass` cluster-wide. Verified on a kubeadm node with the toolkit
sysext but no `nvidia` handler: every operand stays in `ContainerCreating`
with `FailedCreatePodSandBox ... unable to get OCI runtime for sandbox`, so
there is no device plugin, no `nvidia.com/gpu` resource and no CDI injection
for workloads, which then fail with `CUDA driver version is insufficient`.
The `nvidia` handler above is what lets those operands start: the runtime
injects the whole GPU set into them through CDI, and workloads keep getting
their GPUs from the device plugin's CDI requests under `runc`.

## See also

- [nvidia-sysext.md](nvidia-sysext.md) — building and shipping the sysexts.
- [sysext-kernel-modules.md](sysext-kernel-modules.md) — how the modules load.
