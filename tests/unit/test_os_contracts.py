"""Base-OS facts that several features' tests rely on, asserted here once.

bluefin-host (os-host.bst) runs the helpers of the update path, first boot
and the module sysexts; os-k0s-first-boot.bst installs files/os/systemd/system,
where the units that run them live. Presets keep every opt-in feature off
(AGENTS.md, hard rule 4).
"""


from pathlib import Path

import pytest
import yaml

from _systemd import SystemdFile
from conftest import HOST_HELPERS

ROOT = Path(__file__).resolve().parents[2]
ELEMENTS = ROOT / "elements" / "bluefin-server"
PRESETS = sorted((ROOT / "files").rglob("*.preset"))
BASE_PRESETS = sorted((ROOT / "files" / "os" / "systemd" / "system-preset").glob("*.preset"))


def element(name: str) -> dict:
    return yaml.safe_load((ELEMENTS / name).read_text(encoding="utf-8"))


def host_install() -> str:
    return "\n".join(element("os-host.bst")["config"]["install-commands"])


@pytest.mark.parametrize(
    "dependency",
    [
        # bluefin-host and its /usr/libexec/bluefin-* links.
        "bluefin-server/os-host.bst",
        # files/os/systemd/system: the units of the update path, k0s and the
        # NVIDIA Container Toolkit.
        "bluefin-server/os-k0s-first-boot.bst",
    ],
)
def test_the_os_stack_includes(dependency: str) -> None:
    assert dependency in element("os-stack.bst")["depends"]


def test_helpers_are_links_to_the_cluster_modules_bluefin_host() -> None:
    assert element("os-host.bst")["sources"] == [{"kind": "local", "path": "files/homelab/cluster"}]
    assert 'ln -s ../bin/bluefin-host "%{install-root}/usr/libexec/bluefin-${helper}"' in host_install()


# HOST_HELPERS: the names conftest's host_bin links for the tests that run them.
@pytest.mark.parametrize("helper", HOST_HELPERS)
def test_helper_is_linked(helper: str) -> None:
    linked = host_install().split("for helper in", 1)[1].split("; do", 1)[0]
    assert helper in linked.replace("\\", " ").split()


def test_presets_sort_between_ignition_and_fsdk_defaults() -> None:
    # systemd reads preset files from every directory in filename order and
    # the first matching line wins. Ignition enables units through
    # /etc/systemd/system-preset/20-ignition.preset, so a vendor preset that
    # sorts before it (e.g. 20-bluefin-sshd.preset: "disable sshd.service")
    # silently overrides a node config's `enabled: true`. Vendor presets,
    # including those a sysext merges into /usr, must still sort before
    # FSDK's 90-systemd.preset (and so before its 90-sysupdate.preset, which
    # disables the update timers) to take effect at all.
    presets = sorted(p.name for p in (ROOT / "files").rglob("*.preset"))
    assert presets, "no presets found under files/"
    for name in presets:
        assert "20-ignition.preset" < name < "90-systemd.preset", (
            f"{name} must sort after 20-ignition.preset (so Ignition can "
            "enable units Bluefin disables) and before 90-systemd.preset"
        )


def enable_lines(presets: list[Path], name: str) -> list[str]:
    return [
        f"{path.relative_to(ROOT)}: {line}"
        for path in presets
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.split()[:1] == ["enable"] and name in line
    ]


@pytest.mark.parametrize("name", ["containerd", "k0s", "kubeadm", "kubelet", "nvidia"])
def test_no_preset_enables(name: str) -> None:
    assert not enable_lines(PRESETS, name)


def test_no_base_image_preset_enables_zfs() -> None:
    # The ZFS sysext's own 50-zfs.preset enables its units; a preset in a
    # sysext does nothing until the admin runs `systemctl preset`.
    assert not enable_lines(BASE_PRESETS, "zfs")


# Oneshots multi-user.target wants that must run again when started again.
RERUN_ON_PURPOSE = {
    # bluefin-sysext-fetch starts it again after a retry merged more sysexts.
    "bluefin-sysext-activate.service",
    # systemd-sysupdate.service's OnSuccess=/OnFailure= refresh the banners.
    "bluefin-update-status.service",
}


def multi_user_oneshots() -> list[Path]:
    return [
        path
        for path in sorted((ROOT / "files").rglob("*.service"))
        if SystemdFile(path).value("Service", "Type") == "oneshot"
        and "multi-user.target" in SystemdFile(path).words("Install", "WantedBy")
    ]


def test_the_multi_user_oneshots_are_found() -> None:
    names = [path.name for path in multi_user_oneshots()]
    assert RERUN_ON_PURPOSE <= set(names)
    assert "k0s-first-boot.service" in names


@pytest.mark.parametrize("path", multi_user_oneshots(), ids=lambda path: path.name)
def test_multi_user_oneshots_run_once_per_boot(path: Path) -> None:
    # bluefin-sysext-activate.service re-requests multi-user.target after
    # sysexts merge, which starts every wanted unit that is inactive again.
    remain = SystemdFile(path).value("Service", "RemainAfterExit")
    if path.name in RERUN_ON_PURPOSE:
        assert remain is None, f"{path.name} must stay restartable"
    else:
        assert remain == "yes", f"{path.name} needs RemainAfterExit=yes or it runs twice per boot"


def release_fields(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


# Every first-party extension-release names its extension by the file's stem
# (versioned images append _<version> to the image name, not to NAME=).
@pytest.mark.parametrize(
    "path",
    sorted(p for p in (ROOT / "files").rglob("extension-release.*") if "@" not in p.read_text(encoding="utf-8")),
    ids=lambda path: path.name,
)
def test_extension_release_name_is_its_stem(path: Path) -> None:
    name = release_fields(path).get("NAME")
    assert name == path.name.removeprefix("extension-release.")


@pytest.mark.parametrize("stem", ["homebrew-integration", "tailscale", "netbird"])
def test_extension_release_names_itself(stem: str) -> None:
    (path,) = (ROOT / "files").rglob(f"extension-release.{stem}")
    assert release_fields(path)["NAME"] == stem
