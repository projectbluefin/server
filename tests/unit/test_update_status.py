"""Executed coverage for bluefin-update-status and bluefin-update-status-migrate
(bluefin-host).

systemctl, journalctl, agetty and systemd-analyze are stubs on PATH. The
systemctl stub answers for systemd-sysupdate.service from SU_* variables, the
journalctl stub prints JOURNAL_ERR for -p err (the errors a run logged) and
nothing otherwise, and the systemd-analyze stub compares versions with sort -V.
"""


import os
import subprocess
from pathlib import Path

import pytest

SYSTEMCTL = """#!/usr/bin/env bash
echo "systemctl $*" >> "${LOG}"
case "$*" in
    "show -P InvocationID systemd-sysupdate.service") echo "${SU_INVOCATION:-}" ;;
    "show -P ActiveState systemd-sysupdate.service") echo "${SU_ACTIVE:-inactive}" ;;
    "show -P ExecMainExitTimestamp --timestamp=unix systemd-sysupdate.service") echo "${SU_EXIT:-}" ;;
    "show -P Result systemd-sysupdate.service") echo "${SU_RESULT:-success}" ;;
    "is-enabled systemd-sysupdate.timer") echo "${TIMER:-enabled}"; [ "${TIMER:-enabled}" = enabled ] ;;
    *) exit 1 ;;
esac
"""
JOURNALCTL = """#!/usr/bin/env bash
echo "journalctl $*" >> "${LOG}"
case " $* " in
    *" -p err "*) printf '%s\\n' "${JOURNAL_ERR:-}" ;;
    *) ;;
esac
"""
AGETTY = """#!/usr/bin/env bash
echo "agetty $*" >> "${LOG}"
"""
ANALYZE = """#!/usr/bin/env bash
[ "$1" = compare-versions ] && [ "$3" = gt ] || exit 2
[ "$2" != "$4" ] && [ "$(printf '%s\\n%s\\n' "$2" "$4" | sort -V | tail -n1)" = "$2" ]
"""


def stub(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


class Status:
    def __init__(self, tmp: Path, host_bin: Path) -> None:
        self.helper = host_bin / "bluefin-update-status"
        self.bin = tmp / "bin"
        self.bin.mkdir()
        self.log = tmp / "calls.log"
        self.log.touch()
        self.state = tmp / "state"
        self.boot = tmp / "boot"
        self.issue = tmp / "run" / "issue.d" / "40-bluefin-update.issue"
        self.motd = tmp / "run" / "motd"
        (self.boot / "EFI" / "Linux").mkdir(parents=True)
        (self.boot / "EFI" / "Linux" / "bluefin-server-1.0.efi").touch()
        self.os_release = tmp / "os-release"
        self.os_release.write_text('ID=bluefin-server\nIMAGE_VERSION="1.0"\n', encoding="utf-8")
        for name, body in (("systemctl", SYSTEMCTL), ("journalctl", JOURNALCTL), ("agetty", AGETTY), ("systemd-analyze", ANALYZE)):
            stub(self.bin / name, body)

    def __call__(self, **env: str) -> subprocess.CompletedProcess[str]:
        full = dict(
            os.environ,
            PATH=f"{self.bin}:{os.environ['PATH']}",
            TZ="UTC",
            LOG=str(self.log),
            BLUEFIN_OS_RELEASE=str(self.os_release),
            BLUEFIN_BOOT_PATH=str(self.boot),
            BLUEFIN_UPDATE_STATE_DIR=str(self.state),
            BLUEFIN_ISSUE_FILE=str(self.issue),
            BLUEFIN_MOTD_FILE=str(self.motd),
            **env,
        )
        for var in ("STATE_DIRECTORY", "BLUEFIN_SYSTEMCTL", "BLUEFIN_JOURNALCTL", "BLUEFIN_AGETTY"):
            if var not in env:
                full.pop(var, None)
        return subprocess.run([str(self.helper)], capture_output=True, text=True, env=full, timeout=30)

    def uki(self, name: str) -> None:
        (self.boot / "EFI" / "Linux" / name).touch()

    def issue_lines(self) -> list[str]:
        return self.issue.read_text(encoding="utf-8").splitlines()

    def state_lines(self) -> list[str]:
        return (self.state / "state").read_text(encoding="utf-8").splitlines()


@pytest.fixture()
def status(tmp_path: Path, host_bin: Path) -> Status:
    return Status(tmp_path, host_bin)


def test_a_node_that_never_checked_shows_its_version_updates_on_and_never(status: Status) -> None:
    result = status()
    assert result.returncode == 0, result.stderr
    # printf '%s\n' of the text plus its own newline: a blank last line.
    assert status.issue.read_text(encoding="utf-8") == "Bluefin Server 1.0, automatic updates on\nLast update check: never\n\n"
    assert status.motd.read_text(encoding="utf-8") == status.issue.read_text(encoding="utf-8")
    assert status.issue.stat().st_mode & 0o777 == 0o644
    assert "agetty --reload" in status.log.read_text(encoding="utf-8").splitlines()
    assert not (status.state / "state").exists()


def test_a_successful_run_is_recorded_and_shown_as_up_to_date(status: Status) -> None:
    result = status(SU_INVOCATION="aaa", SU_EXIT="@1700000000", SU_RESULT="success")
    assert result.returncode == 0, result.stderr
    assert status.state_lines() == ["last_success=1700000000", "last_error=", "error=", "recorded=aaa"]
    assert "Last update check: 2023-11-14 22:13 UTC, up to date" in status.issue_lines()
    assert "FAILED" not in status.issue.read_text(encoding="utf-8")


def test_a_signature_failure_is_a_banner_line_with_its_message(status: Status) -> None:
    status(
        SU_INVOCATION="bbb", SU_EXIT="@1700000600", SU_RESULT="exit-code",
        JOURNAL_ERR="Signature verification failed.\nFailed to acquire manifest: Bad message",
    )
    assert status.issue_lines() == [
        "Bluefin Server 1.0, automatic updates on",
        "Last update check: never",
        "Last update check FAILED 2023-11-14 22:23 UTC: signature verification failed (Signature verification failed.)",
        "  journalctl -u systemd-sysupdate.service",
        "",
    ]
    assert "  journalctl -u systemd-sysupdate.service" in status.motd.read_text(encoding="utf-8").splitlines()
    assert "journalctl -q -o cat --no-pager -p err _SYSTEMD_INVOCATION_ID=bbb" in status.log.read_text(encoding="utf-8")


def test_an_unreachable_source_is_a_banner_line(status: Status) -> None:
    status(
        SU_INVOCATION="ccc", SU_EXIT="@1700000600", SU_RESULT="exit-code",
        JOURNAL_ERR="Transfer failed: Couldn't connect to server\nFailed to acquire manifest: Input/output error",
    )
    assert (
        "Last update check FAILED 2023-11-14 22:23 UTC: update source unreachable (Transfer failed: Couldn't connect to server)"
        in status.issue_lines()
    )


def test_an_unclassified_failure_shows_its_first_error_line_or_the_unit_result(status: Status) -> None:
    status(SU_INVOCATION="ddd", SU_EXIT="@1700000600", SU_RESULT="exit-code", JOURNAL_ERR="\nDisk full\nNo space left")
    assert "Last update check FAILED 2023-11-14 22:23 UTC: Disk full" in status.issue_lines()
    status(SU_INVOCATION="eee", SU_EXIT="@1700000700", SU_RESULT="timeout", JOURNAL_ERR="")
    assert (
        "Last update check FAILED 2023-11-14 22:25 UTC: systemd-sysupdate.service failed with result timeout"
        in status.issue_lines()
    )


def test_the_error_stays_until_a_later_check_succeeds(status: Status) -> None:
    status(SU_INVOCATION="a1", SU_EXIT="@1700000000", SU_RESULT="success")
    status(SU_INVOCATION="a2", SU_EXIT="@1700000600", SU_RESULT="exit-code", JOURNAL_ERR="HTTP request to x failed with code 404.")
    lines = status.issue_lines()
    assert "Last update check: 2023-11-14 22:13 UTC" in lines
    assert any(line.startswith("Last update check FAILED 2023-11-14 22:23 UTC: update source unreachable") for line in lines)
    # A refresh at boot (no run since) keeps showing the failure.
    status()
    assert "FAILED 2023-11-14 22:23 UTC" in status.issue.read_text(encoding="utf-8")
    status(SU_INVOCATION="a3", SU_EXIT="@1700001200", SU_RESULT="success")
    assert "Last update check: 2023-11-14 22:33 UTC, up to date" in status.issue_lines()
    assert "FAILED" not in status.issue.read_text(encoding="utf-8")


def test_a_run_is_recorded_once(status: Status) -> None:
    status(SU_INVOCATION="f1", SU_EXIT="@1700000000", SU_RESULT="success")
    status(SU_INVOCATION="f1", SU_EXIT="@1700000000", SU_RESULT="exit-code", JOURNAL_ERR="Transfer failed")
    assert "FAILED" not in status.issue.read_text(encoding="utf-8")
    assert "last_error=" in status.state_lines()


def test_a_run_still_in_progress_is_not_recorded(status: Status) -> None:
    status(SU_INVOCATION="g1", SU_ACTIVE="activating", SU_EXIT="", SU_RESULT="success")
    assert not (status.state / "state").exists()
    assert "Last update check: never" in status.issue_lines()


def test_a_staged_update_is_shown_with_its_version(status: Status) -> None:
    status.uki("bluefin-server-1.1+3.efi")
    status(SU_INVOCATION="h1", SU_EXIT="@1700000000", SU_RESULT="success")
    assert "Last update check: 2023-11-14 22:13 UTC; 1.1 staged, it boots at the next reboot" in status.issue_lines()


def test_an_update_that_used_up_its_boot_tries_is_not_shown_as_staged(status: Status) -> None:
    status.uki("bluefin-server-1.1+0-3.efi")
    status()
    assert "Last update check: never; 1.1 failed its boot tries, staying on 1.0" in status.issue_lines()
    assert "staged" not in status.issue.read_text(encoding="utf-8")


def test_an_older_uki_kept_for_rollback_is_neither_staged_nor_failed(status: Status) -> None:
    status.uki("bluefin-server-0.9.efi")
    status()
    assert "Last update check: never" in status.issue_lines()


def test_disabled_automatic_updates_say_so(status: Status) -> None:
    status(TIMER="disabled")
    assert "Bluefin Server 1.0, automatic updates off (systemd-sysupdate.timer is disabled)" in status.issue_lines()


def test_agetty_escapes_are_neutralised_in_the_issue_file_only(status: Status) -> None:
    status(SU_INVOCATION="k1", SU_EXIT="@1700000000", SU_RESULT="exit-code", JOURNAL_ERR="bad path C:\\x")
    assert "bad path C:\\\\x" in status.issue.read_text(encoding="utf-8")
    motd = status.motd.read_text(encoding="utf-8")
    assert "bad path C:\\x" in motd and "C:\\\\x" not in motd


def test_control_characters_in_an_error_never_reach_the_banner(status: Status) -> None:
    status(SU_INVOCATION="m1", SU_EXIT="@1700000000", SU_RESULT="exit-code", JOURNAL_ERR="boom\x1b[2J")
    text = status.issue.read_text(encoding="utf-8")
    assert "\x1b" not in text
    assert "Last update check FAILED 2023-11-14 22:13 UTC: boom[2J" in text.splitlines()


MIGRATE_SYSTEMCTL = """#!/usr/bin/env bash
echo "systemctl $*" >>"${LOG}"
case "$1" in
    is-enabled) [ -e "${ENABLED}" ] ;;
    preset)
        case "${PRESET_RESULT:-enable}" in
            enable) : >"${ENABLED}" ;;
            disable) : ;;
            error) exit 1 ;;
        esac
        ;;
    *) exit 0 ;;
esac
"""


class Migrate:
    def __init__(self, tmp: Path, host_bin: Path) -> None:
        self.helper = host_bin / "bluefin-update-status-migrate"
        self.systemctl = tmp / "systemctl"
        stub(self.systemctl, MIGRATE_SYSTEMCTL)
        self.log = tmp / "calls.log"
        self.log.touch()
        self.enabled = tmp / "enabled"
        self.stamp = tmp / "var" / "lib" / "bluefin" / "update-status-migrate.stamp"

    def __call__(self, **env: str) -> subprocess.CompletedProcess[str]:
        full = dict(
            os.environ,
            LOG=str(self.log),
            ENABLED=str(self.enabled),
            BLUEFIN_SYSTEMCTL=str(self.systemctl),
            BLUEFIN_UPDATE_STATUS_MIGRATE_STAMP=str(self.stamp),
            **env,
        )
        return subprocess.run([str(self.helper)], capture_output=True, text=True, env=full, timeout=30)

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines()


@pytest.fixture()
def migrate(tmp_path: Path, host_bin: Path) -> Migrate:
    return Migrate(tmp_path, host_bin)


def test_migrate_enables_and_starts_the_banner_unit_on_a_node_that_updated_into_it(migrate: Migrate) -> None:
    result = migrate()
    assert result.returncode == 0, result.stderr
    assert result.stdout == "bluefin-update-status-migrate: enabled bluefin-update-status.service\n"
    assert migrate.calls() == [
        "systemctl is-enabled --quiet bluefin-update-status.service",
        "systemctl preset bluefin-update-status.service",
        "systemctl is-enabled --quiet bluefin-update-status.service",
        "systemctl start --no-block bluefin-update-status.service",
    ]
    assert migrate.stamp.exists()


def test_migrate_touches_only_the_banner_unit_never_the_update_timers(migrate: Migrate) -> None:
    assert migrate().returncode == 0
    assert all(call.endswith("bluefin-update-status.service") for call in migrate.calls())


def test_migrate_leaves_an_already_enabled_unit_alone(migrate: Migrate) -> None:
    migrate.enabled.touch()
    result = migrate()
    assert result.returncode == 0
    assert result.stdout == "bluefin-update-status-migrate: bluefin-update-status.service already enabled\n"
    assert migrate.calls() == ["systemctl is-enabled --quiet bluefin-update-status.service"]
    assert migrate.stamp.exists()


def test_migrate_does_not_start_the_unit_when_a_preset_disables_it(migrate: Migrate) -> None:
    result = migrate(PRESET_RESULT="disable")
    assert result.returncode == 0
    assert result.stdout == "bluefin-update-status-migrate: bluefin-update-status.service left disabled by preset\n"
    assert "systemctl preset bluefin-update-status.service" in migrate.calls()
    assert not [c for c in migrate.calls() if " start " in c]
    assert migrate.stamp.exists()


def test_a_failing_preset_does_not_fail_the_boot_and_still_stamps(migrate: Migrate) -> None:
    assert migrate(PRESET_RESULT="error").returncode == 0
    assert not [c for c in migrate.calls() if " start " in c]
    assert migrate.stamp.exists()
