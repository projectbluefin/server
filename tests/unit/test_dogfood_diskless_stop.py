"""dogfood-diskless.sh --check ends a doomed boot early and tolerates a unit that retries.

The weekly opt-in e2e (#692) boots a guest per scenario with this script. Two
harness behaviours turned short failures into long ones, or good boots into
failures:

- a guest whose boot fails prints the initrd's failure summary and reboots,
  and the script waited out its whole deadline (15 to 90 minutes) for a probe
  that could never run; and
- any ``[FAILED]`` console line failed the run, even from a unit with
  ``Restart=on-failure`` that recovered (bluefin-homelab-apply on the control
  plane), after the probe had reported ``failed=0``.

QEMU is a stub that writes what a guest would put on its two serial ports, so
the script's own stop and verdict logic runs for real.
"""


import os
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "dogfood-diskless.sh"

STUB = """#!/bin/bash
# Stand-in for qemu-system-x86_64: the first -serial file is the console, the
# second the probe's port. Write the scenario's text, then idle until killed.
files=()
while [ $# -gt 0 ]; do
    if [ "$1" = -serial ] && [[ "$2" == file:* ]]; then files+=("${2#file:}"); fi
    shift
done
# QEMU creates both files whatever the guest prints.
printf '%b' "${FAKE_CONSOLE:-}" > "${files[0]}"
printf '%b' "${FAKE_PROBE:-}" > "${files[1]}"
exec sleep 300
"""

SUMMARY = "BLUEFIN: BOOT FAILED\\nLast errors (journalctl -b -p err):\\nRebooting in 60 s\\n"
GOOD_PROBE = (
    "PROBE secureboot=enabled (user)\\n"
    "PROBE updatectl-features=ok zfs \\n"
    "PROBE etc-writable=0 \\n"
    "PROBE identity=ok hostname=bluefin-1234abcd\\n"
    "PROBE prompt=root^A^[[34m^B@^A^[[0m^Bbluefin-1234abcd:/#  hook=1\\n"
)


def run(tmp_path: Path, console: str, probe: str, **env: str) -> tuple[subprocess.CompletedProcess[str], float]:
    image = tmp_path / "set"
    image.mkdir()
    (image / "bluefin-server-netboot_1.2.3.esp.raw").touch()
    (image / "bluefin-server_1.2.3.raw").touch()
    firmware = tmp_path / "ovmf.fd"
    firmware.touch()
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "qemu-system-x86_64"
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(0o755)
    started = time.monotonic()
    result = subprocess.run(
        ["bash", str(SCRIPT), str(image), "--check"],
        env={
            **os.environ,
            "PATH": f"{stub_dir}:{os.environ['PATH']}",
            "OVMF_CODE": str(firmware),
            "OVMF_VARS": str(firmware),
            "DOGFOOD_PORT": "0",
            "DOGFOOD_TIMEOUT": "60",
            "FAKE_CONSOLE": console,
            "FAKE_PROBE": probe,
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    return result, time.monotonic() - started


@pytest.fixture(autouse=True)
def _need_python_http() -> None:
    # The script serves the image with python3 -m http.server.
    assert subprocess.run(["python3", "-c", "import http.server"], check=False).returncode == 0


def test_a_boot_that_fails_twice_stops_the_check_well_before_the_deadline(tmp_path: Path) -> None:
    result, seconds = run(tmp_path, SUMMARY * 2, "")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "the boot failed twice" in result.stderr
    assert "boot probe did not report" not in result.stderr
    assert seconds < 30, f"waited {seconds:.0f}s of a 60 s deadline"


def test_one_failure_summary_is_a_retry_not_a_failure(tmp_path: Path) -> None:
    # A first attempt that fails and a retry that boots is a pass, as before.
    result, _ = run(tmp_path, SUMMARY, GOOD_PROBE + "PROBE failed=0 \\n")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_a_console_failure_still_fails_the_run_by_default(tmp_path: Path) -> None:
    console = "[FAILED] Failed to start Apply the Bluefin … components to this node's cluster.\\n"
    result, _ = run(tmp_path, console, GOOD_PROBE + "PROBE failed=0 \\n")

    assert result.returncode == 1
    assert "booted, but units failed" in result.stderr


def test_a_failure_of_a_unit_that_retries_can_be_allowed_by_name(tmp_path: Path) -> None:
    console = "[FAILED] Failed to start Apply the Bluefin … components to this node's cluster.\\n"
    result, _ = run(tmp_path, console, GOOD_PROBE + "PROBE failed=0 \\n", DOGFOOD_RETRY_OK="Apply the Bluefin")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_an_allowed_unit_that_never_recovers_still_fails_the_run(tmp_path: Path) -> None:
    # The probe's own count is the backstop: it still lists the failed unit.
    console = "[FAILED] Failed to start Apply the Bluefin … components to this node's cluster.\\n"
    result, _ = run(tmp_path, console, GOOD_PROBE + "PROBE failed=1 bluefin-homelab-apply.service \\n", DOGFOOD_RETRY_OK="Apply the Bluefin")

    assert result.returncode == 1
    assert "PASS" not in result.stdout


def test_allowing_one_unit_does_not_hide_another(tmp_path: Path) -> None:
    console = (
        "[FAILED] Failed to start Apply the Bluefin … components to this node's cluster.\\n"
        "[FAILED] Failed to start Some Other Unit.\\n"
    )
    result, _ = run(tmp_path, console, GOOD_PROBE + "PROBE failed=0 \\n", DOGFOOD_RETRY_OK="Apply the Bluefin")

    assert result.returncode == 1
    assert "Some Other Unit" in result.stderr
