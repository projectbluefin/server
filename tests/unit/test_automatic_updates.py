"""Contracts for automatic updates on installed nodes and the boot health gate.

Installed nodes run systemd-sysupdate.timer and systemd-sysupdate-reboot.timer
by vendor preset; Kubernetes nodes leave the reboot to kured; diskless and USB
installer boots keep every update unit inert; operator lock files hold the
local reboot; boot-complete.target requires that no unit failed before
systemd-bless-boot marks a counted UKI good.
"""

from __future__ import annotations

import configparser
import os
import re
import shlex
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "files" / "os" / "systemd" / "system"
PRESETS = ROOT / "files" / "os" / "systemd" / "system-preset"
PRESET = PRESETS / "80-bluefin-updates.preset"
ELEMENTS = ROOT / "elements" / "bluefin-server"
DISKLESS = UNITS / "systemd-sysupdate.service.d" / "10-diskless.conf"
KURED = UNITS / "systemd-sysupdate.service.d" / "20-kured.conf"
INTERLOCK = UNITS / "systemd-sysupdate-reboot.service.d" / "20-interlock.conf"
MIGRATE_UNIT = UNITS / "bluefin-update-status-migrate.service"
MIGRATE_SCRIPT = ROOT / "files" / "os" / "update-check" / "usr" / "libexec" / "bluefin-update-status-migrate"
STATUS_HOOK = UNITS / "systemd-sysupdate.service.d" / "30-update-status.conf"
STATUS_UNIT = UNITS / "bluefin-update-status.service"
STATUS_SCRIPT = ROOT / "files" / "os" / "update-check" / "usr" / "libexec" / "bluefin-update-status"
MOTD_LINK = ROOT / "files" / "os" / "tmpfiles.d" / "40-bluefin-motd.conf"
DISKLESS_ONLY = "/run/machines/rootdisk.raw"


def ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def values(path: Path, key: str) -> list[str]:
    """Every value of <key> in order; configparser keeps only the last one."""
    return [
        line.split("=", 1)[1]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith(f"{key}=")
    ]


def conditions(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("Condition")
    ]


def preset_lines() -> list[list[str]]:
    return [
        line.split()
        for line in PRESET.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def test_preset_enables_the_update_timers_and_the_health_gate() -> None:
    assert preset_lines() == [
        ["enable", "systemd-sysupdate.timer"],
        ["enable", "systemd-sysupdate-reboot.timer"],
        ["enable", "systemd-boot-check-no-failures.service"],
        ["enable", "bluefin-boot-deadline.timer"],
        ["enable", "bluefin-update-status.service"],
        ["enable", "bluefin-diskless-update-check.timer"],
    ]


def test_preset_overrides_fsdk_and_yields_to_ignition() -> None:
    # FSDK's 90-sysupdate.preset disables both timers; the first match wins.
    assert "20-ignition.preset" < PRESET.name < "90-sysupdate.preset"
    assert PRESET.name < "90-systemd.preset"


def test_no_base_image_preset_enables_kubernetes_or_zfs() -> None:
    for preset in PRESETS.glob("*.preset"):
        for line in preset.read_text(encoding="utf-8").splitlines():
            if line.startswith("enable"):
                assert not re.search(r"kubelet|containerd|k0s|zfs", line), (preset, line)


@pytest.mark.parametrize(
    "dropin",
    [
        "bluefin-update-status.service",
        "systemd-sysupdate-reboot.service.d/10-diskless.conf",
        "systemd-sysupdate.timer.d/10-diskless.conf",
        "systemd-sysupdate-reboot.timer.d/10-diskless.conf",
    ],
)
def test_update_units_are_inert_on_diskless_and_installer_boots(dropin: str) -> None:
    expected = conditions(DISKLESS)
    assert expected == [
        f"ConditionPathExists=!{DISKLESS_ONLY}",
        "ConditionKernelCommandLine=!root=tmpfs",
    ]
    assert conditions(UNITS / dropin) == expected


@pytest.mark.parametrize("diskless", [True, False])
def test_sysupdated_masks_the_uki_transfer_only_on_diskless_boots(tmp_path: Path, diskless: bool) -> None:
    # Without $BOOT, a transfer relative to it fails every sysupdate verb and
    # leaves sysupdated with no host target (#375); the UKI is the only one.
    needs_boot = [
        p.name
        for p in sorted((ROOT / "files" / "os" / "sysupdate.d").glob("*.transfer"))
        if ini(p)["Target"].get("PathRelativeTo", "root") != "root"
    ]
    assert needs_boot == ["20-uki.transfer"]

    argv = shlex.split(ini(UNITS / "systemd-sysupdated.service.d" / "10-diskless.conf")["Service"]["ExecStartPre"])
    assert argv[:2] == ["/usr/bin/sh", "-c"] and DISKLESS_ONLY in argv[2]
    script = argv[2].replace("/run/", f"{tmp_path}/run/")
    if diskless:
        (tmp_path / "run" / "machines").mkdir(parents=True)
        (tmp_path / "run" / "machines" / "rootdisk.raw").touch()
    for _ in range(2):
        subprocess.run(["sh", "-c", script], check=True)

    mask = tmp_path / "run" / "sysupdate.d" / "20-uki.transfer"
    if diskless:
        assert mask.is_symlink() and os.readlink(mask) == "/dev/null"
    else:
        assert not mask.is_symlink() and not mask.exists()

def test_kured_flag_is_set_only_when_an_update_is_pending() -> None:
    service = ini(KURED)["Service"]
    assert "ExecStartPost" not in service, "Type=simple: ExecStartPost runs before the update"
    cmd = service["ExecStopPost"]
    # bluefin-update-pending wraps `systemd-sysupdate pending` and says no
    # when that version already failed its boot tries (test_update_pending.py).
    assert cmd == "/usr/bin/sh -c 'if /usr/libexec/bluefin-update-pending; then touch /run/reboot-required; fi'"
    for dropin in (UNITS / "systemd-sysupdate.service.d").iterdir():
        keys = {key for section in ini(dropin).values() for key in section}
        assert "ExecStartPost" not in keys, dropin
        # The timer runs FSDK's `systemd-sysupdate update`, which also fetches
        # every enabled feature (zfs, kubestellar, kubeadm) in lock-step.
        assert "ExecStart" not in keys, dropin


def test_reboot_is_held_by_the_operator_lock_files() -> None:
    # From projectbluefin/server#182: a failed condition skips the unit.
    assert conditions(INTERLOCK) == [
        "ConditionPathExists=!/run/reboot-lock",
        "ConditionPathExists=!/etc/reboot-lock",
    ]
    # One interlock drop-in: #182's reboot-coordination.conf must not come back.
    assert sorted(p.name for p in INTERLOCK.parent.iterdir()) == ["10-diskless.conf", "20-interlock.conf"]


def test_reboot_skips_an_update_that_already_failed_its_tries() -> None:
    conds = values(INTERLOCK, "ExecCondition")
    assert len(conds) == 3
    assert conds[0] == "/usr/libexec/bluefin-update-pending"


def _interlock_script() -> str:
    cmd = values(INTERLOCK, "ExecCondition")[1]
    argv = shlex.split(cmd.replace("$$", "$"))
    assert argv[:2] == ["/usr/bin/sh", "-c"] and len(argv) == 3, argv
    return argv[2]


def _run_interlock(tmp_path: Path, states: dict[str, str]) -> subprocess.CompletedProcess[str]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    fake = bindir / "systemctl"
    lines = ["#!/bin/sh", '[ "$1" = is-active ] || exit 99', 'case "$2" in']
    for unit, state in states.items():
        lines.append(f'  {unit}) echo {state}; [ {state} = active ]; exit $? ;;')
    lines += ["esac", "echo inactive", "exit 3"]
    fake.write_text("\n".join(lines) + "\n", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    return subprocess.run(["sh", "-c", _interlock_script()], capture_output=True, text=True, env=env)


def test_reboot_proceeds_without_kubernetes(tmp_path: Path) -> None:
    result = _run_interlock(tmp_path, {})
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "unit,state",
    [
        ("kubelet.service", "active"),
        ("k0scontroller.service", "active"),
        ("k0sworker.service", "active"),
        ("kubelet.service", "activating"),
        ("k0sworker.service", "deactivating"),
    ],
)
def test_reboot_stands_down_while_kubernetes_runs(tmp_path: Path, unit: str, state: str) -> None:
    result = _run_interlock(tmp_path, {unit: state})
    # 1..254 makes systemd skip the unit instead of failing it.
    assert result.returncode == 1, result.stdout + result.stderr
    assert "leaving the reboot to kured" in result.stdout


def test_reboot_proceeds_when_kubernetes_is_stopped_or_failed(tmp_path: Path) -> None:
    result = _run_interlock(tmp_path, {"kubelet.service": "failed", "k0sworker.service": "inactive"})
    assert result.returncode == 0, result.stdout + result.stderr


def test_kured_hook_moved_into_the_unit_directory() -> None:
    stack = yaml.safe_load((ELEMENTS / "os-stack.bst").read_text(encoding="utf-8"))["depends"]
    assert "bluefin-server/os-k0s-first-boot.bst" in stack, "installs files/os/systemd/system"
    assert "bluefin-server/os-kured-hook.bst" not in stack
    assert not (ROOT / "files" / "os" / "systemd" / "systemd-sysupdate.service.d").exists()


def test_every_update_run_refreshes_the_login_banners() -> None:
    # A failed run stays a failed unit and also reaches the console and SSH
    # banners; a successful one clears the error there.
    unit = ini(STATUS_HOOK)["Unit"]
    assert unit["OnSuccess"] == "bluefin-update-status.service"
    assert unit["OnFailure"] == "bluefin-update-status.service"


def test_update_checks_wait_for_a_counted_boot_to_be_judged() -> None:
    # An unreachable update source must never fail a unit before
    # systemd-boot-check-no-failures has blessed a boot-counted image.
    assert ini(STATUS_HOOK)["Unit"]["After"] == "boot-complete.target"


def test_the_banner_unit_runs_the_status_helper_with_persistent_state() -> None:
    service = ini(STATUS_UNIT)["Service"]
    assert service["Type"] == "oneshot"
    assert service["ExecStart"] == "/usr/libexec/bluefin-update-status"
    assert service["StateDirectory"] == "bluefin-update-status"
    assert "/var/lib/bluefin-update-status" in STATUS_SCRIPT.read_text(encoding="utf-8")
    assert STATUS_SCRIPT.stat().st_mode & stat.S_IXUSR
    assert ini(STATUS_UNIT)["Install"]["WantedBy"] == "multi-user.target"


def test_the_banners_are_the_files_agetty_login_and_sshd_read() -> None:
    script = STATUS_SCRIPT.read_text(encoding="utf-8")
    # agetty merges /run/issue.d with the image's /usr/lib/issue.d banner.
    assert "/run/issue.d/40-bluefin-update.issue" in script
    assert (ROOT / "files" / "os" / "issue.d" / "30-bluefin.issue").name < "40-bluefin-update.issue"
    # shadow's login (MOTD_FILE /etc/motd) and sshd (UsePAM no) read only
    # /etc/motd; it links to the runtime file, never over an operator's own.
    assert "/run/motd" in script
    lines = [line.split() for line in MOTD_LINK.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    assert lines == [["L", "/etc/motd", "-", "-", "-", "-", "../run/motd"]]


def test_nodes_that_updated_into_the_banner_unit_enable_it_once() -> None:
    # Presets apply on first boot only (#367). The migration is enabled in
    # /usr so it runs on updated nodes, once, on installed nodes only.
    unit = ini(MIGRATE_UNIT)
    assert unit["Service"]["Type"] == "oneshot"
    assert unit["Service"]["ExecStart"] == "/usr/libexec/bluefin-update-status-migrate"
    assert values(MIGRATE_UNIT, "ConditionPathExists") == [
        "!/var/lib/bluefin/update-status-migrate.stamp",
        f"!{DISKLESS_ONLY}",
    ]
    assert unit["Unit"]["ConditionKernelCommandLine"] == "!root=tmpfs"
    assert MIGRATE_SCRIPT.stat().st_mode & stat.S_IXUSR
    usr = (ROOT / "elements" / "oci" / "bluefin-server-usr.bst").read_text(encoding="utf-8")
    assert "multi-user.target.wants/bluefin-update-status-migrate.service" in usr


def test_the_migration_never_reenables_the_update_timers() -> None:
    # An operator who disabled the update or reboot timer keeps them off.
    code = [line for line in MIGRATE_SCRIPT.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")]
    assert "unit=bluefin-update-status.service" in code
    assert not [line for line in code if ".timer" in line or "preset-all" in line or "system-preset" in line]
