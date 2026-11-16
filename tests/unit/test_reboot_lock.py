"""Wiring of the fleet reboot lock (FleetLock client) on installed nodes.

bluefin-reboot-lock takes a reboot slot before the nightly reboot and the boot
deadline's reboot, and bluefin-reboot-lock-release.service gives it back once
a boot is good. Without a configured server both are no-ops. The client
itself (bluefin-host's bluefin-reboot-lock) runs in test_reboot_lock_client.py.
"""


import os
import stat
import subprocess
from pathlib import Path

import pytest

from _systemd import SystemdFile, preset

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "files" / "os" / "systemd" / "system"
PRESETS = ROOT / "files" / "os" / "systemd" / "system-preset"
HOST = ROOT / "files" / "homelab" / "cluster" / "internal" / "host"
RELEASE = UNITS / "bluefin-reboot-lock-release.service"
REBOOT_DROPINS = UNITS / "systemd-sysupdate-reboot.service.d"
REBOOT_TIMER_DROPINS = UNITS / "systemd-sysupdate-reboot.timer.d"
FLEET_TIMER = UNITS / "bluefin-fleet-reboot.timer"
CREDENTIALS = "bluefin.reboot-lock.*"
CONF = "/etc/bluefin/reboot-lock.conf"
URL_CREDENTIAL = "bluefin.reboot-lock.url"


def reboot_service() -> SystemdFile:
    return SystemdFile(*sorted(REBOOT_DROPINS.glob("*.conf")))


def test_nightly_reboot_takes_a_slot_only_after_every_other_check() -> None:
    # A slot is taken only when the reboot would happen; a failed
    # ExecCondition skips the unit, like the kured interlock before it.
    service = reboot_service()
    conds = service.commands("ExecCondition")
    assert conds[-1] == ["/usr/libexec/bluefin-reboot-lock", "acquire"]
    assert conds[0] == ["/usr/libexec/bluefin-update-pending"]
    assert conds[1] == ["/usr/bin/bluefin-host", "kube-interlock"]
    assert service.values("Service", "ImportCredential") == [CREDENTIALS]
    # The operator lock files still hold the reboot before any request.
    assert service.values("Unit", "ConditionPathExists")[-2:] == ["!/run/reboot-lock", "!/etc/reboot-lock"]


def test_boot_deadline_reads_the_same_configuration() -> None:
    service = SystemdFile(UNITS / "bluefin-boot-deadline.service")
    assert service.values("Service", "ImportCredential") == [CREDENTIALS]
    # The deadline runs the same client in-process (or $BLUEFIN_REBOOT_LOCK).
    source = (HOST / "bootdeadline" / "bootdeadline.go").read_text(encoding="utf-8")
    assert 'fleetlock.Main(h, []string{"acquire"})' in source


def test_release_runs_after_the_boot_is_judged() -> None:
    # Installed nodes only: test_automatic_updates.py.
    unit = SystemdFile(RELEASE)
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


def _bless_condition(tmp_path: Path, host_bin: Path, status: str | None) -> subprocess.CompletedProcess[str]:
    (argv,) = SystemdFile(RELEASE).commands("ExecCondition")
    assert argv == ["/usr/bin/bluefin-host", "boot-is-good"], argv
    bless = tmp_path / "systemd-bless-boot"
    body = f'[ "$1" = status ] && echo {status}\n' if status is not None else "exit 1\n"
    bless.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    bless.chmod(bless.stat().st_mode | stat.S_IXUSR)
    env = dict(os.environ, BLUEFIN_BLESS_BOOT=str(bless))
    return subprocess.run([str(host_bin / "bluefin-host"), argv[1]], capture_output=True, text=True, env=env)


@pytest.mark.parametrize("status", ["good", "clean"])
def test_a_good_boot_releases_the_slot(tmp_path: Path, host_bin: Path, status: str) -> None:
    result = _bless_condition(tmp_path, host_bin, status)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("status", ["indeterminate", "bad", "dirty", None])
def test_an_unblessed_boot_keeps_the_slot(tmp_path: Path, host_bin: Path, status: str | None) -> None:
    # 1 skips the unit; the node keeps its slot until a boot is good.
    result = _bless_condition(tmp_path, host_bin, status)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"boot is {status or 'unknown'}: keeping the reboot slot\n" == result.stdout


def test_release_is_enabled_in_usr_not_by_preset() -> None:
    # Presets apply on first boot only; a node that updated into the unit
    # must still release its slot, or its group stops rebooting.
    usr = (ROOT / "elements" / "oci" / "bluefin-server-usr.bst").read_text(encoding="utf-8")
    assert "multi-user.target.wants/bluefin-reboot-lock-release.service" in usr
    assert preset("bluefin-reboot-lock-release.service", PRESETS.glob("*.preset")) is None


def test_nightly_window_retries_for_a_free_slot() -> None:
    timer = SystemdFile(FLEET_TIMER)
    # FSDK's systemd-sysupdate-reboot.timer: OnCalendar=4:10 with up to 30 min
    # of random delay; this timer adds two more runs of the same service
    # (04:10-05:40).
    assert timer.values("Timer", "OnCalendar") == ["04:40", "05:10"]
    assert timer.value("Timer", "RandomizedDelaySec") == "30min"
    assert timer.value("Timer", "Unit") == "systemd-sysupdate-reboot.service"
    assert not timer.values("Timer", "Persistent")


def test_only_fleet_lock_nodes_get_the_extra_runs() -> None:
    # Every installed node runs the reboot timer; nothing adds runs to it.
    assert not SystemdFile(*sorted(REBOOT_TIMER_DROPINS.glob("*.conf"))).sections.get("Timer")
    timer = SystemdFile(FLEET_TIMER)
    # "|": either source of the server URL the client reads starts the timer.
    # Installed nodes only: test_automatic_updates.py.
    assert [c for c in timer.values("Unit", "ConditionPathExists") if c.startswith("|")] == [f"|{CONF}"]
    assert timer.values("Unit", "ConditionCredential") == [f"|{URL_CREDENTIAL}"]
    source = (HOST / "fleetlock" / "fleetlock.go").read_text(encoding="utf-8")
    assert f'"{CONF}"' in source and f"credential {URL_CREDENTIAL})" in source


def test_disabling_the_reboot_timer_stops_the_extra_runs_too() -> None:
    # Enabled in /usr like the release service, so nodes that updated into it
    # run it too, but wanted by the reboot timer instead of timers.target: the
    # documented opt-out, systemctl disable --now systemd-sysupdate-reboot.timer,
    # must keep stopping every automatic reboot.
    timer = SystemdFile(FLEET_TIMER)
    assert timer.words("Install", "WantedBy") == ["systemd-sysupdate-reboot.timer"]
    assert timer.words("Unit", "PartOf") == ["systemd-sysupdate-reboot.timer"]
    usr = (ROOT / "elements" / "oci" / "bluefin-server-usr.bst").read_text(encoding="utf-8")
    assert "systemd-sysupdate-reboot.timer.wants/bluefin-fleet-reboot.timer" in usr
    assert "timers.target.wants/bluefin-fleet-reboot.timer" not in usr
    assert preset("bluefin-fleet-reboot.timer", PRESETS.glob("*.preset")) is None
