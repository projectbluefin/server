"""The offline-installer QEMU check ends its key enrollment boot on the marker.

``scripts/dogfood-installer.sh`` boots the stick once so systemd-boot enrolls
the Secure Boot keys. systemd-boot says "successfully enrolled" on the
firmware console (ttyS0) once db, KEK and PK are written and then resets,
which ``-no-reboot`` turns into a QEMU exit. OVMF sometimes hangs in that
reset instead, and a step that waited only for the exit then failed after the
full per-boot timeout with the keys already in place.

These tests run the script's own ``boot_wait`` against a stand-in QEMU that
never exits, without booting anything.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "dogfood-installer.sh"
TEXT = SCRIPT.read_text(encoding="utf-8")
# The firmware console of the hung enrollment boot in CI, as QEMU writes it.
HUNG_ENROLLMENT = (
    '\x1b[=3hBdsDxe: loading Boot0002 "UEFI Misc Device" from PciRoot(0x0)/Pci(0x2,0x0)\r\n'
    'BdsDxe: starting Boot0002 "UEFI Misc Device" from PciRoot(0x0)/Pci(0x2,0x0)\r\n'
    "Enrolling secure boot keys from directory: \\loader\\keys\\auto\r\n"
    "Custom Secure Boot keys successfully enrolled, rebooting the system now!\r\n"
)


def function(name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", TEXT, re.M | re.S)
    assert match, f"no {name}() in {SCRIPT.name}"
    return match[0]


def enroll_step() -> str:
    start = TEXT.index('echo "==> 1/${steps} enroll Secure Boot keys')
    return TEXT[start:TEXT.index("\nfi\n", start)]


def enroll_wait() -> tuple[int, list[str]]:
    """The timeout and the arguments the enrollment step hands boot_wait."""
    call = re.search(r"^ *timeout_s=(\d+) boot_wait (.+)$", enroll_step(), re.M)
    assert call, enroll_step()
    return int(call[1]), shlex.split(call[2])


def boot_wait(tmp_path: Path, args: list[str], timeout: int) -> subprocess.CompletedProcess:
    """boot_wait <args> on the serial logs of a hung enrollment boot; prints
    whether the stand-in QEMU still runs once it returns."""
    for serial, text in (("ttyS0", HUNG_ENROLLMENT), ("ttyS1", ""), ("ttyS2", "")):
        (tmp_path / f"{args[0]}.{serial}").write_text(text, encoding="utf-8")
    script = (
        'set -euo pipefail; state="$1" timeout_s="$2"; shift 2\n'
        'fail() { echo "FAIL: $* (logs: ${state})" >&2; exit 1; }\n'
        + function("boot_wait")
        + "sleep 300 </dev/null >/dev/null 2>&1 &\n"
        "qemu_pid=$! qemu_deadline=$(( $(date +%s) + timeout_s ))\n"
        "trap 'kill \"${qemu_pid}\" 2>/dev/null || true' EXIT\n"
        'boot_wait "$@"\n'
        'if kill -0 "${qemu_pid}" 2>/dev/null; then echo "qemu running"; else echo "qemu stopped"; fi\n'
    )
    return subprocess.run(
        ["bash", "-c", script, "boot_wait", str(tmp_path), str(timeout), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_enrollment_marker_ends_a_boot_whose_reset_hangs(tmp_path: Path) -> None:
    _, args = enroll_wait()
    result = boot_wait(tmp_path, args, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "qemu stopped"
    # The cleaned log the step's post-check reads.
    assert "successfully enrolled" in (tmp_path / f"{args[0]}.{args[2]}.log").read_text(encoding="utf-8")


def test_without_a_serial_only_the_probe_console_ends_a_boot(tmp_path: Path) -> None:
    # Every other step ends on its probe's ttyS1 line; text on the firmware
    # console must not end those boots early.
    _, args = enroll_wait()
    result = boot_wait(tmp_path, args[:2], timeout=2)
    assert result.returncode != 0
    assert f"FAIL: {args[0]}: no result within 2s" in result.stderr


def test_the_enrollment_step_checks_the_marker_it_waits_for_on_the_firmware_console() -> None:
    timeout, (name, marker, serial) = enroll_wait()
    step = enroll_step()
    assert serial == "ttyS0"
    assert f"grep -aq '{marker}' \"${{state}}/{name}.{serial}.log\" || fail" in step
    # boot_start sets the deadline, boot_wait reports it: both get the same.
    start = re.search(rf"^ *timeout_s=(\d+) boot_start {name} ", step, re.M)
    assert start and int(start[1]) == timeout
    default = re.search(r'^timeout_s="\$\{DOGFOOD_TIMEOUT:-(\d+)\}"$', TEXT, re.M)
    assert default and timeout < int(default[1])
