---
name: nvidia-sysext
description: Build and ship the NVIDIA driver (open kernel modules) and NVIDIA Container Toolkit (CDI) sysexts for Bluefin Server. Load when adding, bumping, or debugging an NVIDIA flavour, or when wiring the toolkit to a container runtime.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-09-30"
---
# NVIDIA sysexts

Use this skill when working on the NVIDIA driver and toolkit sysexts shipped
as opt-in overlays for Bluefin Server. How extensions load, merge and reach
nodes, these two included, is canonical in
[systemd-sysext-extensions.md](systemd-sysext-extensions.md); this skill covers
what is specific to NVIDIA: flavours, bumps, and container runtimes.

## When to Use

- Bumping an NVIDIA driver flavour (`include/nvidia.yml`) or the NVIDIA
  Container Toolkit (`include/nvidia-container-toolkit.yml`).
- Adding a driver flavour for a new NVIDIA branch (e.g. `nvidia-open-615`).
- Changing the shared recipe (`include/nvidia-driver.yml`), the units and
  drop-ins in `files/nvidia/sysext/`, or the toolkit's drop-in in
  `files/nvidia-container-toolkit/sysext/`.
- Changing the `nvidia-open-<branch>` sysupdate feature and transfer, or the
  `nvidia-container-toolkit` sysupdate component.
- Wiring containerd or the GPU Operator to a Bluefin GPU node.

## When NOT to Use

- Extension identity, merging, delivery, and the kernel-module loader
  `bluefin-sysext-modules`: [systemd-sysext-extensions.md](systemd-sysext-extensions.md).
- Sysupdate features, components and signing:
  [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md).
- Choosing sysexts per node with Booty: [booty-integration.md](booty-integration.md).
- Other sysexts: [k0s-sysext.md](k0s-sysext.md), [kubeadm-sysext.md](kubeadm-sysext.md);
  ZFS and KubeStellar live in systemd-sysext-extensions.md.

## What ships

| Sysext | Release asset | Version | Contents |
| --- | --- | --- | --- |
| Driver flavour | `nvidia-open-<branch>_<image-version>.raw.zst` | Locked to the image (`ID=bluefin-server`, `VERSION_ID=<image-version>`) | The open kernel modules (signed, zstd-compressed), the headless userspace, GSP firmware, NVIDIA's license, and the units and modprobe / sysusers / tmpfiles drop-ins every flavour shares. |
| Container Toolkit | `nvidia-container-toolkit-<ctk-ver>.raw.zst` | Own axis (`ID=_any`), like k0s | `nvidia-ctk`, `nvidia-cdi-hook` and upstream's `nvidia-cdi-refresh.{service,path}`, with upstream's drop-in and a Bluefin one. CDI only: no `nvidia-container-runtime`, OCI hook or `libnvidia-container`. |

Both are opt-in: nothing in the base image ships or enables them.

### Open kernel modules only (Turing and newer)

- Only `kernel-open/` is built (`make -C payload/kernel-open`), never the
  closed `kernel/` tree, so a flavour drives Turing and newer GPUs only. The
  modules are `nvidia nvidia-uvm nvidia-modeset nvidia-drm`; `nvidia-peermem`
  is left out, because it serves GPUDirect RDMA over InfiniBand, which the
  FSDK kernel lacks.
- The `.run` is never executed: the build unpacks its payload after the
  makeself prologue and checks that the payload's `.manifest` names the
  pinned version.
- The userspace is headless: the `nvidia-libs` and `nvidia-tools` lists in
  `include/nvidia-driver.yml`, and no 32-bit libraries, X driver,
  `nvidia-settings`, `libglvnd`, OpenCL ICD loader, NGX, OptiX, VDPAU, NvFBC,
  VulkanSC or `nvidia-powerd`. NVIDIA's binaries ship byte-for-byte
  (`strip-binaries` is empty). The install fails when a shipped ELF needs a
  library that neither the sysext nor `nvidia-external-needed` provides, so a
  library NVIDIA splits out in a later release breaks the build, not a node.

## Flavours

`include/nvidia.yml` is the only list of flavours. Each flavour is a comment
line and two atoms, so per-flavour pull requests never edit adjacent lines:

```yaml
variables:
  # nvidia-open-595: production branch 595
  nvidia-open-595-version: "595.104.02"
  nvidia-open-595-sha256: "e421c202e4c79f58c3c7f3161bbe71454ebb3d88936f88205a0e327cd04c59ca"
```

The version is NVIDIA's directory under
`https://download.nvidia.com/XFree86/Linux-x86_64/`, and the sha256 is that of
`NVIDIA-Linux-x86_64-<version>.run`, as NVIDIA publishes it in
`<file>.sha256sum` next to the `.run`. The driver element's `ref:` reads the
sha256 atom, so a bump edits `include/nvidia.yml` only.

A node runs one flavour. When more than one `nvidia-open-*` extension is
merged, `nvidia-flavour-guard.service` fails and `nvidia-load.service`, which
requires it, loads nothing: every flavour installs the same module, binary
and library-link paths, so two merged flavours would shadow each other.
Booty refuses a second flavour per host up front. A flavour and the ZFS
sysext merge together (see the kernel-module sysexts in
systemd-sysext-extensions.md). Moving a node to a new branch means adding a
flavour, overlapping, then retiring the old one.

### Adding a flavour

Only add a branch NVIDIA publishes. Every flavour enlarges every release set
and image build; [ci-tooling.md](ci-tooling.md) has the cost of one.

1. `include/nvidia.yml`: a comment line and the two atoms
   `<flavour>-version` and `<flavour>-sha256`.
2. Copy `elements/nvidia/nvidia-open-595.bst`,
   `elements/nvidia/nvidia-open-595-signed.bst` and
   `elements/oci/nvidia-open-595-sysext.bst` to the new flavour's names and
   replace `nvidia-open-595` throughout: `nvidia-flavour`, `nvidia-version`,
   the `ref:` atom, the `sysext-*` variables, and the dependencies between
   the three.
3. `elements/oci/bluefin-server-image.bst`: stage `oci/<flavour>-sysext.bst`
   and add its `<flavour>_%{image-version}.raw.zst` to the signed set;
   `scripts/publish-release.sh`: expect the new asset.
4. `files/os/sysupdate.d/`: a `<flavour>.feature` and a
   `<NN>-<flavour>.transfer`, copied from `nvidia-open-595.feature` and
   `33-nvidia-open-595.transfer`.
5. `Justfile`: add `oci/<flavour>-sysext.bst` to the graph `just validate`
   resolves. `build-nvidia-sysext`, `export-nvidia-sysext` and
   `dogfood-nvidia` take the flavour as their argument.
6. `.github/scripts/track-binaries.py`: register
   `NvidiaDriverComponent("<flavour>")` in `COMPONENTS`.
7. `tests/unit/test_nvidia_sysext.py`: update the flavour list that
   `test_flavour_table_matches_the_element_files` pins; the other tests there
   read `include/nvidia.yml` and run for every flavour.

Booty accepts any `nvidia-open-<branch>`, so nothing changes there. A missed
step fails `tests/unit/test_nvidia_sysext.py` (elements, signed release set,
`publish-release.sh`, feature and transfer, Justfile) or
`tests/unit/test_track_binaries.py` (every flavour tracked).

## Bumping

### Driver

`.github/workflows/track-binaries.yml` runs `.github/scripts/track-binaries.py`
daily ([ci-tooling.md](ci-tooling.md)). For each flavour it reads NVIDIA's
directory index; a newer release of the flavour's branch counts once its
`.run` and `.run.sha256sum` are both there, and `check` never downloads a
`.run`. It then opens one pull request per flavour that moves both atoms,
with the sha256 read from NVIDIA's `.run.sha256sum` and confirmed against the
downloaded `.run`. To move to a given release of the branch by hand, with the
same verification:

```bash
python3 .github/scripts/track-binaries.py apply nvidia-open-595 --version 595.<x>.<y>
```

The tracker refuses a version outside the flavour's branch: a new branch is a
new flavour.

### Container Toolkit

The element fetches the release tag with git (`git_repo`) and builds from
the vendored modules upstream commits. Its `ref:` reads the two atoms in
`include/nvidia-container-toolkit.yml`: the version and the commit the tag
points to. NVIDIA publishes no checksum for any archive of the source, so
the tracker pins the commit instead, and writes it only when the GitHub API
and the git remote (`git ls-remote`) name the same commit for the tag.

The same tracker run proposes patch releases of the pinned `MAJOR.MINOR`
(stable GitHub releases only). A minor bump runs the same verification:

```bash
python3 .github/scripts/track-binaries.py apply nvidia-container-toolkit --version <x>.<y>.<z>
```

Before merging any bump, compare upstream's `deployments/systemd/` units for
the new release with
`files/nvidia-container-toolkit/sysext/nvidia-cdi-refresh-bluefin.conf`,
which replaces upstream's `ExecCondition=`.

## GPU nodes

### Choosing the sysexts

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

### Containers (CDI)

Once the toolkit is merged, and after `nvidia-ldconfig.service` and
`nvidia-device-nodes.service`, `nvidia-cdi-refresh.service` runs
`nvidia-ctk cdi generate`, which writes `/var/run/cdi/nvidia.yaml`.
containerd 2.x has CDI on by default and reads that directory; the kubeadm
sysext's containerd defines only the `runc` runtime, and there is no `nvidia`
runtime class or OCI hook.

### GPU Operator

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

Not verified yet: with `cdi.enabled=true` and its NRI plugin off (the
default), the operator still runs its own pods (device plugin, GPU feature
discovery, DCGM exporter, validator) with `runtimeClassName: nvidia`
(`operator.runtimeClass`), and no `nvidia` runtime handler is configured.
How those pods start is settled on real hardware in the GPU rollout, with the
rest of the GPU-present path that QEMU cannot exercise
(systemd-sysext-extensions.md).

## Build and test

- Driver: `just build-nvidia-sysext [FLAVOUR]`, `just export-nvidia-sysext
  [FLAVOUR]` and the QEMU checks `just dogfood-nvidia [FLAVOUR]` and
  `DOGFOOD_SYSEXT=nvidia` / `zfs,nvidia` with `just dogfood-install`, all in
  [ddi-installer-build.md](ddi-installer-build.md). `FLAVOUR` defaults to
  `nvidia-open-595`.
- Toolkit: `just build-nvidia-container-toolkit-sysext`,
  `just export-nvidia-container-toolkit-sysext`.
- Both release assets are in the signed release set
  ([ddi-installer.md](ddi-installer.md)).
- Contracts: `tests/unit/test_nvidia_sysext.py` (driver),
  `tests/unit/test_nvidia_container_toolkit_sysext.py` (toolkit),
  `tests/unit/test_nvidia_container_toolkit_delivery.py` (toolkit activation
  and sysupdate), `tests/unit/test_track_binaries.py` (driver and toolkit tracking).

## Repository layout

| Path | Purpose |
| --- | --- |
| `include/nvidia.yml` | The flavours: version and sha256 atoms. |
| `include/nvidia-driver.yml` | Shared build, install, sign and stage recipe. |
| `include/nvidia-container-toolkit.yml` | The toolkit version and its tag's commit. |
| `elements/nvidia/<flavour>.bst` | Driver build: unpacks the `.run` payload, builds `kernel-open/`, unsigned. |
| `elements/nvidia/<flavour>-signed.bst` | Signs the modules (sha512, `linux-module-cert.key`) and zstd-compresses them. |
| `elements/oci/<flavour>-sysext.bst` | The image-locked EROFS sysext. |
| `elements/nvidia/nvidia-container-toolkit.bst` | Toolkit build: the release tag via git, Go with its vendored modules, no network. |
| `elements/oci/nvidia-container-toolkit-sysext.bst` | The `ID=_any` toolkit sysext. |
| `elements/bluefin-server/os-nvidia-container-toolkit-sysupdate.bst` | Installs the toolkit's sysupdate component, `/usr/lib/sysupdate.nvidia-container-toolkit.d/`. |
| `files/nvidia/sysext/` | Driver units (`nvidia-flavour-guard`, `nvidia-load`, `nvidia-device-nodes`, `nvidia-ldconfig`, `nvidia-persistenced`), modprobe / sysusers / tmpfiles drop-ins, `extension-release.nvidia` template. |
| `files/nvidia-container-toolkit/sysext/` | Toolkit extension-release and the `nvidia-cdi-refresh.service` drop-in. |
| `files/os/systemd/system/nvidia-container-toolkit-{activate,fetch}.service` | Opt-in toolkit activation on installed nodes, disabled by `80-bluefin-opt-in.preset`. |
| `files/os/sysupdate.d/<flavour>.feature`, `<NN>-<flavour>.transfer` | The driver's opt-in sysupdate feature and its image-locked transfer. |
| `files/os/sysupdate.nvidia-container-toolkit.d/` | The toolkit's sysupdate transfer (own version axis). |
| `scripts/dogfood-nvidia.sh` | QEMU: merge a driver sysext on a disk install without a GPU and probe it. |

## See also

- [systemd-sysext-extensions.md](systemd-sysext-extensions.md) — extension
  identity, delivery, `bluefin-sysext-modules`, the GPU-present path.
- [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md) —
  features, components, signing.
- [booty-integration.md](booty-integration.md) — per-host `extensions`.
- [ddi-installer-build.md](ddi-installer-build.md) — build and dogfood
  commands.
- [ci-tooling.md](ci-tooling.md) — `track-binaries.yml` and the build cost.
- [k0s-sysext.md](k0s-sysext.md) — the other `ID=_any` sysext.
- [skill-improvement.md](skill-improvement.md) — how to update this skill.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary.
- `systemd-sysext(8)`, `systemd-sysupdate(8)`, `nvidia-ctk cdi generate --help`.
