"""Contracts for delivering the NVIDIA Container Toolkit sysext to installed nodes.

The toolkit is on its own version axis like k0s, so it is delivered the way
k0s is: a sysupdate component (``/usr/lib/sysupdate.nvidia-container-toolkit.d``)
fetches it into ``/var/lib/nvidia-container-toolkit`` behind a stable
``nvidia-container-toolkit.raw`` symlink, and an opt-in unit merges it through
``/run/extensions`` on every boot.
"""

from pathlib import Path

import yaml

from _systemd import SystemdFile, preset

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "files" / "os" / "systemd" / "system"
ACTIVATE = UNITS / "nvidia-container-toolkit-activate.service"
FETCH = UNITS / "nvidia-container-toolkit-fetch.service"
PRESETS = sorted((ROOT / "files" / "os" / "systemd" / "system-preset").glob("*.preset"))
ELEMENTS = ROOT / "elements"
COMPONENT_ELEMENT = ELEMENTS / "bluefin-server" / "os-nvidia-container-toolkit-sysupdate.bst"
UNITS_ELEMENT = ELEMENTS / "bluefin-server" / "os-k0s-first-boot.bst"
STACK = ELEMENTS / "bluefin-server" / "os-stack.bst"
STATE = "/var/lib/nvidia-container-toolkit"
IMAGE = f"{STATE}/nvidia-container-toolkit.raw"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def in_os_stack(element: Path) -> bool:
    return element.relative_to(ELEMENTS).as_posix() in load(STACK)["depends"]


def test_component_transfer_ships_in_usr() -> None:
    data = load(COMPONENT_ELEMENT)
    assert data["kind"] == "import"
    assert [s["path"] for s in data["sources"]] == ["files/os/sysupdate.nvidia-container-toolkit.d"]
    assert data["config"]["target"] == "/usr/lib/sysupdate.nvidia-container-toolkit.d"
    assert in_os_stack(COMPONENT_ELEMENT)


def test_units_ship_in_usr_but_stay_opt_in() -> None:
    assert [s["path"] for s in load(UNITS_ELEMENT)["sources"]] == ["files/os/systemd/system"]
    assert in_os_stack(UNITS_ELEMENT)
    for unit in (ACTIVATE.name, FETCH.name):
        assert preset(unit, PRESETS) == "disable", (
            f"the toolkit is opt-in: FSDK has no 'disable *' default, so {unit} "
            "must be disabled explicitly and no earlier preset may enable it"
        )


def test_a_seeded_node_skips_the_network_fetch() -> None:
    fetch = SystemdFile(FETCH)
    assert f"!{IMAGE}" in fetch.values("Unit", "ConditionPathExists")
    assert fetch.commands() == [
        ["/usr/bin/systemd-sysupdate", "--component=nvidia-container-toolkit", "update"]
    ]
    assert fetch.value("Service", "Type") == "oneshot"
    assert fetch.value("Service", "Restart") == "on-failure"
    assert "network-online.target" in fetch.words("Unit", "After")
    assert ACTIVATE.name in fetch.words("Unit", "Before")


def test_activation_merges_through_run_extensions_after_a_soft_fetch() -> None:
    unit = SystemdFile(ACTIVATE)
    assert FETCH.name in unit.words("Unit", "Wants") and FETCH.name in unit.words("Unit", "After")
    for hard in ("Requires", "Requisite", "BindsTo"):
        assert FETCH.name not in unit.words("Unit", hard), "a failed fetch must not fail activation"
    assert unit.value("Service", "StateDirectory") == "nvidia-container-toolkit"
    assert unit.value("Service", "RemainAfterExit") == "yes", (
        "bluefin-sysext-activate.service re-requests multi-user.target; without "
        "RemainAfterExit the merge would run again under running services"
    )
    assert unit.value("Service", "Restart") == "on-failure"
    assert ["/usr/bin/test", "-e", IMAGE] in unit.commands("ExecStartPre")
    start = unit.commands()
    install = ["/usr/bin/install", "-D", "-m", "0644", IMAGE, "/run/extensions/nvidia-container-toolkit.raw"]
    refresh = ["/usr/bin/systemd-sysext", "refresh"]
    reload = ["/usr/bin/systemctl", "daemon-reload"]
    units = ["/usr/bin/systemctl", "start", "--no-block", "nvidia-cdi-refresh.path", "nvidia-cdi-refresh.service"]
    assert start == [install, refresh, reload, units], (
        "copy, merge, reload, then start the sysext's units by name: the merge "
        "comes after PID 1 built the boot transaction"
    )
    assert "multi-user.target" not in [w for argv in start for w in argv], (
        "re-requesting multi-user.target pulls this unit and "
        "bluefin-sysext-activate.service back in, and the two loop until start "
        "limits fail units"
    )
    assert not [w for argv in start for w in argv if "systemd-sysupdate" in w]
    assert unit.words("Install", "WantedBy") == ["multi-user.target"]
