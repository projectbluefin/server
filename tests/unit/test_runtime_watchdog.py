"""The runtime hardware watchdog (files/os/system.conf.d/50-bluefin-watchdog.conf).

- PID 1 keeps the hardware watchdog armed while the system runs, so a node
  whose kernel or service manager freezes resets itself. systemd's default
  arms it only in the last phase of a reboot (RebootWatchdogSec=), which a
  freeze while running or while services stop never reaches.
- The reboot watchdog stays on and outlasts the runtime one.
- The drop-in ships in /usr (so A/B updates carry it) through an element of
  the OS stack, and the kernel builds the x86 drivers PID 1 opens, as modules
  udev loads for the matching chipset (0007-linux-watchdog.patch).
"""


from pathlib import Path

import yaml

from _systemd import SystemdFile

ROOT = Path(__file__).resolve().parents[2]
CONF = ROOT / "files" / "os" / "system.conf.d" / "50-bluefin-watchdog.conf"
ELEMENT = ROOT / "elements" / "bluefin-server" / "os-system-conf.bst"
STACK = ROOT / "elements" / "bluefin-server" / "os-stack.bst"
KERNEL_PATCH = ROOT / "patches" / "freedesktop-sdk" / "0007-linux-watchdog.patch"


def seconds(value: str | None) -> int:
    assert value, "setting missing"
    units = {"s": 1, "min": 60, "h": 3600}
    for suffix, factor in sorted(units.items(), key=lambda u: -len(u[0])):
        if value.endswith(suffix):
            return int(value[: -len(suffix)]) * factor
    return int(value)


def test_runtime_watchdog_is_armed() -> None:
    runtime = seconds(SystemdFile(CONF).value("Manager", "RuntimeWatchdogSec"))
    # Long enough that a busy node's PID 1 pings in time (every runtime / 2),
    # short enough that a frozen canary is back within minutes.
    assert 30 <= runtime <= 300


def test_reboot_watchdog_stays_on_and_outlasts_the_runtime_one() -> None:
    conf = SystemdFile(CONF)
    reboot = seconds(conf.value("Manager", "RebootWatchdogSec"))
    assert reboot >= seconds(conf.value("Manager", "RuntimeWatchdogSec"))


def test_drop_in_ships_in_usr_through_the_os_stack() -> None:
    data = yaml.safe_load(ELEMENT.read_text(encoding="utf-8"))
    assert data["kind"] == "import"
    assert data["config"]["target"] == "/usr/lib/systemd/system.conf.d"
    assert [s["path"] for s in data["sources"]] == ["files/os/system.conf.d"]
    stack = yaml.safe_load(STACK.read_text(encoding="utf-8"))
    assert "bluefin-server/os-system-conf.bst" in stack["depends"]


def test_kernel_builds_the_drivers_pid1_opens() -> None:
    added = [line[1:].split("#")[0].split() for line in KERNEL_PATCH.read_text().splitlines()
             if line.startswith("+") and not line.startswith("+++")]
    options = {(w[0], w[1]) for w in added if len(w) >= 2}
    assert ("enable", "WATCHDOG_CORE") in options
    for driver in ("ITCO_WDT", "SP5100_TCO", "I6300ESB_WDT"):
        assert ("module", driver) in options, driver
