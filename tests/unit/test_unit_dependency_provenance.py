"""Every hard dependency of a shipped unit must have a named provider.

`just validate` resolves the BuildStream graph, but a systemd `Requires=` is not
a bst node — the graph cannot see it. A unit that requires a service nothing
ships still builds, still validates, and then fails at boot with a job that
cannot be resolved. That is a silent, boot-only failure mode.

This module closes it. Every unit named by `Requires=` or `BindsTo=` in a unit
this repository stages must be either:

  * staged by this repository (a peer file in files/os/systemd/system), or
  * listed in EXTERNAL_PROVIDERS with the component that supplies it.

Adding a hard dependency on something nothing provides therefore fails here
rather than on a running machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UNIT_DIR = ROOT / "files" / "os" / "systemd" / "system"

# Units this repository does not stage, mapped to what does supply them.
#
# containerd.service is the load-bearing entry. FSDK 26.08 ships no containerd
# component at all, so nothing can be composed from it — see
# docs/superpowers/specs/2026-09-19-flatcar-runtime-parity.md, which records
# `no elements/components/containerd.bst` in the pinned junction.
#
# Flatcar publishes containerd as a standalone systemd-sysext, the same delivery
# mechanism this repository already uses for Kubernetes.
# elements/flatcar/containerd-sysext.bst imports that image, the installer stages
# it into the initrd, and files/installer/repart.d/30-var.conf seeds it to
# /var/lib/extensions/containerd-flatcar.raw so the first boot merges it offline. The
# image carries its own multi-user.target.wants symlink, so the merge is what
# enables the service.
EXTERNAL_PROVIDERS = {
    "containerd.service": (
        "Flatcar containerd sysext via elements/flatcar/containerd-sysext.bst, "
        "seeded to /var/lib/extensions by files/installer/repart.d/30-var.conf"
    ),
    "systemd-sysext.service": "systemd, present in the base image",
    "network-online.target": "systemd",
    "systemd-networkd.service": "systemd",
    "var.mount": "generated from the installer's /var partition",
}

HARD_DEPENDENCY_KEYS = ("Requires=", "BindsTo=")


def staged_units() -> set[str]:
    return {path.name for path in UNIT_DIR.iterdir() if path.is_file()}


def hard_dependencies() -> list[tuple[str, str]]:
    """Return (unit_file, required_unit) for every hard dependency declared."""
    found: list[tuple[str, str]] = []
    for unit in sorted(UNIT_DIR.glob("*.service")):
        for raw in unit.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            for key in HARD_DEPENDENCY_KEYS:
                if line.startswith(key):
                    # systemd accepts a space-separated list and repeated keys.
                    for name in line[len(key):].split():
                        found.append((unit.name, name))
    return found


def test_units_declare_at_least_one_hard_dependency() -> None:
    """Guard the parser itself: a silent zero-match would make this suite vacuous."""
    assert hard_dependencies(), "parsed no Requires=/BindsTo= at all; parser is broken"


@pytest.mark.parametrize(
    ("unit", "required"),
    hard_dependencies(),
    ids=lambda value: value.replace(".service", ""),
)
def test_hard_dependency_has_a_provider(unit: str, required: str) -> None:
    local = staged_units()
    assert required in local or required in EXTERNAL_PROVIDERS, (
        f"{unit} declares a hard dependency on {required!r}, which this repository "
        f"does not stage and EXTERNAL_PROVIDERS does not account for. Either ship "
        f"the unit, or record who supplies it — a Requires= on a unit nothing "
        f"provides fails only at boot, where nothing else catches it."
    )


def test_kubelet_bridges_the_cni_plugin_directory() -> None:
    """Plugins ship at the bakery path; containerd and Cilium read /opt/cni/bin.

    Without the bridge the loopback plugin is absent, every pod sandbox fails to
    get a network, and the node never leaves NotReady with no obvious cause.

    The bridge must also refresh: /opt/cni/bin lives on /var and outlives a
    sysext update, so a copy that can only ever add files would leave the node
    running the plugins it first booted with while the version stamp advertises
    newer ones.
    """
    kubelet = (UNIT_DIR / "kubelet.service").read_text(encoding="utf-8")

    assert "/opt/cni/bin" in kubelet, "kubelet does not populate /opt/cni/bin"
    assert "/usr/local/bin/cni" in kubelet, (
        "kubelet does not read the sysext's CNI plugin directory"
    )

    bridge = next(
        line for line in kubelet.splitlines() if "cp -a" in line and "cni" in line
    )
    assert "-an" in bridge or "--no-clobber" in bridge, (
        "the copy must not clobber when the sysext is unchanged; cilium-cni is "
        "not a name the sysext ships, but an unconditional overwrite of a "
        "steady-state /opt/cni/bin buys nothing and widens the blast radius"
    )
    assert "/usr/local/share/kubernetes-cni-version" in bridge, (
        "the bridge must key off the sysext's CNI version stamp, or a sysext "
        "update never reaches /opt/cni/bin and the node runs stale plugins "
        "while advertising the new version"
    )

    body = kubelet.split("[Service]", 1)[1]
    assert body.index("/opt/cni/bin") < body.index("ExecStart=/usr/bin/kubelet"), (
        "the bridge must run before kubelet starts"
    )
