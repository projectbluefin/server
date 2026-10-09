"""Executed coverage for the rollback half of the boot health gate.

bluefin-boot-deadline reboots a boot-counted boot that has not reached
boot-complete.target by its deadline, so systemd-boot uses up a try and falls
back. It runs here against fake systemd tools.
"""

from __future__ import annotations

import configparser
import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "files" / "os" / "systemd" / "system"
LIBEXEC = ROOT / "files" / "os" / "update-check" / "usr" / "libexec"
DEADLINE = LIBEXEC / "bluefin-boot-deadline"
COUNTED = "/sys/firmware/efi/efivars/LoaderBootCountPath-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f"
BOOTED = "26.09.3"


def ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def conditions(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("Condition")]


def executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.mark.parametrize("unit", ["bluefin-boot-deadline.timer", "bluefin-boot-deadline.service"])
def test_deadline_runs_only_on_boot_counted_disk_boots(unit: str) -> None:
    assert conditions(UNITS / unit) == [
        f"ConditionPathExists={COUNTED}",
        "ConditionPathExists=!/run/machines/rootdisk.raw",
        "ConditionKernelCommandLine=!root=tmpfs",
    ]


def test_deadline_timer_defaults_to_fifteen_minutes() -> None:
    timer = ini(UNITS / "bluefin-boot-deadline.timer")
    assert timer["Timer"]["OnBootSec"] == "15min"
    assert timer["Install"]["WantedBy"] == "timers.target"


def test_deadline_fires_even_when_the_boot_hangs() -> None:
    unit = ini(UNITS / "bluefin-boot-deadline.service")["Unit"]
    assert unit["DefaultDependencies"] == "no"
    assert unit["After"] == "sysinit.target"
    for target in ("basic.target", "multi-user.target", "boot-complete.target"):
        assert target not in unit.get("After", ""), target
        assert target not in unit.get("Requires", ""), target
    service = ini(UNITS / "bluefin-boot-deadline.service")["Service"]
    assert service["ExecStart"] == "/usr/libexec/bluefin-boot-deadline"


def test_helpers_ship_in_the_os_and_are_executable_bash() -> None:
    stack = yaml.safe_load((ROOT / "elements" / "bluefin-server" / "os-stack.bst").read_text(encoding="utf-8"))
    assert "bluefin-server/os-update-check.bst" in stack["depends"]
    for script in (DEADLINE,):
        assert script.read_text(encoding="utf-8").startswith("#!/usr/bin/bash\n")
        assert script.stat().st_mode & stat.S_IXUSR
        subprocess.run(["bash", "-n", str(script)], check=True)


def deadline(
    tmp_path: Path,
    status: str,
    *,
    complete: bool = False,
    failed: tuple[str, ...] = ("dogfood-broken.service",),
    units: dict[str, str] | None = None,
    ukis: tuple[str, ...] = (),
    lock: bool = False,
    fleet: int = 0,
):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "systemctl.calls"
    units = units or {}
    unit_cases = "".join(f"      {u}) echo {s}; [ {s} = active ]; exit $? ;;\n" for u, s in units.items())
    failed_lines = "".join(f"echo '{u} loaded failed failed Test'\n" for u in failed)
    executable(
        bindir / "systemctl",
        f'echo "$*" >> {calls}\n'
        'case "$1 $2" in\n'
        f'  "is-active --quiet") exit {0 if complete else 3} ;;\n'
        '  "list-units --state=failed")\n'
        f"{failed_lines}"
        "    exit 0 ;;\n"
        '  "--no-block reboot") exit 0 ;;\n'
        "esac\n"
        'if [ "$1" = is-active ]; then\n'
        '  case "$2" in\n'
        f"{unit_cases}"
        "  esac\n"
        "  echo inactive; exit 3\n"
        "fi\n"
        "exit 99\n",
    )
    bless = tmp_path / "bless"
    executable(bless, f'[ "$1" = status ] && echo {status}\n')
    boot = tmp_path / "boot"
    (boot / "EFI" / "Linux").mkdir(parents=True)
    for uki in ukis:
        (boot / "EFI" / "Linux" / uki).touch()
    os_release = tmp_path / "os-release"
    os_release.write_text(f'IMAGE_ID=bluefin-server\nIMAGE_VERSION="{BOOTED}"\n', encoding="utf-8")
    lockfile = tmp_path / "etc-reboot-lock"
    if lock:
        lockfile.touch()
    sentinel = tmp_path / "run" / "reboot-required"
    # The FleetLock client exits with `fleet`: 0 slot held, 1 refused,
    # 3 server unreachable.
    client = tmp_path / "bluefin-reboot-lock"
    executable(client, f'echo "$*" >> {tmp_path / "fleet.calls"}\nexit {fleet}\n')
    env = dict(
        os.environ,
        PATH=f"{bindir}:{os.environ['PATH']}",
        BLUEFIN_BLESS_BOOT=str(bless),
        BLUEFIN_BOOT_PATH=str(boot),
        BLUEFIN_OS_RELEASE=str(os_release),
        BLUEFIN_REBOOT_LOCKS=f"{tmp_path / 'run-reboot-lock'} {lockfile}",
        BLUEFIN_REBOOT_SENTINEL=str(sentinel),
        BLUEFIN_REBOOT_LOCK=str(client),
    )
    result = subprocess.run([str(DEADLINE)], capture_output=True, text=True, env=env, timeout=30)
    # 75: no fleet reboot slot; bluefin-boot-deadline.service runs it again.
    # An unreachable server (3) does not hold the rollback.
    assert result.returncode == (0 if fleet in (0, 3) else 75), result.stdout + result.stderr
    rebooted = "--no-block reboot" in (calls.read_text(encoding="utf-8") if calls.exists() else "")
    return rebooted, sentinel.exists(), result.stdout + result.stderr


@pytest.mark.parametrize("status", ["indeterminate", "bad"])
def test_unblessed_counted_boot_reboots(tmp_path: Path, status: str) -> None:
    rebooted, flagged, log = deadline(tmp_path, status)
    assert rebooted and not flagged, log
    assert f"<3>Bluefin Server {BOOTED} did not reach boot-complete.target before the boot deadline" in log
    assert "failed: dogfood-broken.service" in log


def test_hung_boot_with_no_failed_unit_reboots(tmp_path: Path) -> None:
    rebooted, _, log = deadline(tmp_path, "indeterminate", failed=())
    assert rebooted, log
    assert "no unit failed, but the boot never got there" in log


@pytest.mark.parametrize("status", ["clean", "good", ""])
def test_blessed_or_uncounted_boot_never_reboots(tmp_path: Path, status: str) -> None:
    rebooted, flagged, log = deadline(tmp_path, status)
    assert not rebooted and not flagged, log
    assert "nothing to do" in log


def test_boot_that_reached_boot_complete_never_reboots(tmp_path: Path) -> None:
    rebooted, flagged, log = deadline(tmp_path, "indeterminate", complete=True, failed=())
    assert not rebooted and not flagged, log


def test_operator_lock_holds_the_reboot(tmp_path: Path) -> None:
    rebooted, flagged, log = deadline(tmp_path, "indeterminate", lock=True)
    assert not rebooted and not flagged, log
    assert "holds reboots, not rebooting" in log


@pytest.mark.parametrize(
    "unit,state",
    [("kubelet.service", "active"), ("k0scontroller.service", "active"), ("k0sworker.service", "activating")],
)
def test_kubernetes_node_is_left_to_kured(tmp_path: Path, unit: str, state: str) -> None:
    rebooted, flagged, log = deadline(tmp_path, "indeterminate", units={unit: state})
    assert not rebooted and flagged, log
    assert f"{unit} is {state}: flagged" in log


def test_node_whose_kubelet_failed_reboots_directly(tmp_path: Path) -> None:
    # NotReady: nothing to drain, and kured's pod cannot run there.
    rebooted, flagged, log = deadline(
        tmp_path, "indeterminate", failed=("kubelet.service",), units={"kubelet.service": "failed"}
    )
    assert rebooted and not flagged, log


def test_last_try_reboots_when_there_is_a_fallback(tmp_path: Path) -> None:
    rebooted, _, log = deadline(
        tmp_path, "dirty", ukis=("bluefin-server-26.09.4+0-3.efi", "bluefin-server-26.09.3.efi")
    )
    assert rebooted, log


def test_last_try_without_a_fallback_does_not_loop(tmp_path: Path) -> None:
    rebooted, _, log = deadline(tmp_path, "dirty", ukis=("bluefin-server-26.09.4+0-3.efi",))
    assert not rebooted, log
    assert "no other UKI to fall back to" in log


def test_reboot_waits_for_a_fleet_reboot_slot(tmp_path: Path) -> None:
    # A rollback reboot must not bypass a FleetLock server that refuses it.
    rebooted, flagged, log = deadline(tmp_path, "indeterminate", fleet=1)
    assert not rebooted and not flagged, log
    assert (tmp_path / "fleet.calls").read_text(encoding="utf-8") == "acquire\n"
    assert "no fleet reboot slot, retrying later" in log


@pytest.mark.parametrize("status", ["indeterminate", "bad"])
def test_unreachable_fleet_lock_server_does_not_hold_the_rollback(tmp_path: Path, status: str) -> None:
    # The update being rolled back may be what broke the network, DNS or TLS;
    # waiting for the server would keep the node on it for good.
    rebooted, flagged, log = deadline(tmp_path, status, fleet=3)
    assert rebooted and not flagged, log
    assert (tmp_path / "fleet.calls").read_text(encoding="utf-8") == "acquire\n"
    assert "<4>the FleetLock server could not be reached; the rollback goes ahead without a reboot slot" in log
    assert "rebooting so systemd-boot falls back after the last try" in log


def test_reboot_takes_the_fleet_slot_first(tmp_path: Path) -> None:
    rebooted, _, log = deadline(tmp_path, "indeterminate")
    assert rebooted, log
    assert (tmp_path / "fleet.calls").read_text(encoding="utf-8") == "acquire\n"


@pytest.mark.parametrize("units", [{"kubelet.service": "active"}, {}])
def test_kured_and_operator_holds_never_take_a_fleet_slot(tmp_path: Path, units: dict[str, str]) -> None:
    rebooted, _, log = deadline(tmp_path, "indeterminate", units=units, lock=not units)
    assert not rebooted, log
    assert not (tmp_path / "fleet.calls").exists()


def test_deadline_retries_only_when_no_fleet_slot_was_free() -> None:
    service = ini(UNITS / "bluefin-boot-deadline.service")["Service"]
    assert service["RestartForceExitStatus"] == "75"
    assert service.get("Restart", "no") == "no"
    assert service["RestartSec"] == "5min"
    assert service["ImportCredential"] == "bluefin.reboot-lock.*"
