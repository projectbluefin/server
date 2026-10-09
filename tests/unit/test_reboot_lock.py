"""Wiring of the fleet reboot lock (FleetLock client) on installed nodes.

bluefin-reboot-lock takes a reboot slot before the nightly reboot and the boot
deadline's reboot, and bluefin-reboot-lock-release.service gives it back once
a boot is good. Without a configured server both are no-ops. The client
itself runs in tests/unit/bluefin-reboot-lock_test.bats.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from _systemd import SystemdFile, preset

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "files" / "os" / "systemd" / "system"
PRESETS = ROOT / "files" / "os" / "systemd" / "system-preset"
CLIENT = ROOT / "files" / "os" / "update-check" / "usr" / "libexec" / "bluefin-reboot-lock"
RELEASE = UNITS / "bluefin-reboot-lock-release.service"
REBOOT_DROPINS = UNITS / "systemd-sysupdate-reboot.service.d"
TIMER_DROPIN = UNITS / "systemd-sysupdate-reboot.timer.d" / "20-fleet-lock.conf"
CREDENTIALS = "bluefin.reboot-lock.*"


def reboot_service() -> SystemdFile:
    return SystemdFile(*sorted(REBOOT_DROPINS.glob("*.conf")))


def test_client_ships_where_the_units_run_it() -> None:
    element = yaml.safe_load((ROOT / "elements" / "bluefin-server" / "os-update-check.bst").read_text(encoding="utf-8"))
    assert element["sources"] == [{"kind": "local", "path": "files/os/update-check"}]
    stack = yaml.safe_load((ROOT / "elements" / "bluefin-server" / "os-stack.bst").read_text(encoding="utf-8"))
    assert "bluefin-server/os-update-check.bst" in stack["depends"]
    assert CLIENT.read_text(encoding="utf-8").startswith("#!/usr/bin/bash\n")
    assert CLIENT.stat().st_mode & stat.S_IXUSR
    subprocess.run(["bash", "-n", str(CLIENT)], check=True)


def test_nightly_reboot_takes_a_slot_only_after_every_other_check() -> None:
    # A slot is taken only when the reboot would happen; a failed
    # ExecCondition skips the unit, like the kured interlock before it.
    service = reboot_service()
    conds = service.commands("ExecCondition")
    assert conds[-1] == ["/usr/libexec/bluefin-reboot-lock", "acquire"]
    assert conds[0] == ["/usr/libexec/bluefin-update-pending"]
    assert "leaving the reboot to kured" in conds[1][-1]
    assert service.values("Service", "ImportCredential") == [CREDENTIALS]
    # The operator lock files still hold the reboot before any request.
    assert service.values("Unit", "ConditionPathExists")[-2:] == ["!/run/reboot-lock", "!/etc/reboot-lock"]


def test_boot_deadline_reads_the_same_configuration() -> None:
    service = SystemdFile(UNITS / "bluefin-boot-deadline.service")
    assert service.values("Service", "ImportCredential") == [CREDENTIALS]
    script = (ROOT / "files" / "os" / "update-check" / "usr" / "libexec" / "bluefin-boot-deadline").read_text(encoding="utf-8")
    assert "/usr/libexec/bluefin-reboot-lock" in script


def test_release_runs_on_installed_nodes_after_the_boot_is_judged() -> None:
    unit = SystemdFile(RELEASE)
    assert unit.values("Unit", "ConditionPathExists") == ["!/run/machines/rootdisk.raw"]
    assert unit.values("Unit", "ConditionKernelCommandLine") == ["!root=tmpfs"]
    after = unit.words("Unit", "After")
    for dep in ("boot-complete.target", "systemd-bless-boot.service", "network-online.target"):
        assert dep in after, dep
    # Requiring boot-complete.target would pull it (and the no-failures check)
    # into boots that are not counted; the ExecCondition judges those.
    assert "boot-complete.target" not in unit.words("Unit", "Requires") + unit.words("Unit", "Wants")
    # Without this multi-user.target orders itself after the unit, a cycle
    # through systemd-boot-check-no-failures.service on counted boots.
    assert "multi-user.target" in after
    assert unit.words("Install", "WantedBy") == ["multi-user.target"]
    assert unit.value("Service", "Type") == "oneshot"
    assert unit.commands("ExecStart") == [["/usr/libexec/bluefin-reboot-lock", "release"]]
    assert unit.values("Service", "ImportCredential") == [CREDENTIALS]


def test_release_retries_with_backoff() -> None:
    unit = SystemdFile(RELEASE)
    # systemd refuses Restart=always/on-success for Type=oneshot, not on-failure.
    assert unit.value("Service", "Restart") == "on-failure"
    assert unit.value("Service", "RestartSec") == "1min"
    assert unit.value("Service", "RestartSteps") == "5"
    assert unit.value("Service", "RestartMaxDelaySec") == "1h"


def _bless_condition(tmp_path: Path, status: str | None) -> subprocess.CompletedProcess[str]:
    (argv,) = SystemdFile(RELEASE).commands("ExecCondition")
    assert argv[:2] == ["/usr/bin/sh", "-c"] and len(argv) == 3, argv
    bless = tmp_path / "systemd-bless-boot"
    body = f'[ "$1" = status ] && echo {status}\n' if status is not None else "exit 1\n"
    bless.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    bless.chmod(bless.stat().st_mode | stat.S_IXUSR)
    script = argv[2].replace("/usr/lib/systemd/systemd-bless-boot", str(bless))
    assert script != argv[2]
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=dict(os.environ))


@pytest.mark.parametrize("status", ["good", "clean"])
def test_a_good_boot_releases_the_slot(tmp_path: Path, status: str) -> None:
    result = _bless_condition(tmp_path, status)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("status", ["indeterminate", "bad", "dirty", None])
def test_an_unblessed_boot_keeps_the_slot(tmp_path: Path, status: str | None) -> None:
    # 1 skips the unit; the node keeps its slot until a boot is good.
    result = _bless_condition(tmp_path, status)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "keeping the reboot slot" in result.stdout


def test_release_is_enabled_in_usr_not_by_preset() -> None:
    # Presets apply on first boot only; a node that updated into the unit
    # must still release its slot, or its group stops rebooting.
    usr = (ROOT / "elements" / "oci" / "bluefin-server-usr.bst").read_text(encoding="utf-8")
    assert "multi-user.target.wants/bluefin-reboot-lock-release.service" in usr
    assert preset("bluefin-reboot-lock-release.service", PRESETS.glob("*.preset")) is None


def test_nightly_window_retries_for_a_free_slot() -> None:
    timer = SystemdFile(TIMER_DROPIN)
    # FSDK's systemd-sysupdate-reboot.timer: OnCalendar=4:10; the drop-in adds
    # two more runs, each with up to 30 min of random delay (04:10-05:40).
    assert timer.values("Timer", "OnCalendar") == ["04:40", "05:10"]
    assert timer.value("Timer", "RandomizedDelaySec") == "30min"
    assert not timer.values("Timer", "Persistent")
