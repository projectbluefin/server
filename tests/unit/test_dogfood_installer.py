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


import os
import re
import shlex
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

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




@pytest.mark.parametrize("script", ["dogfood-installer.sh", "dogfood-homelab-installer.sh"])
def test_the_journal_mirror_opens_after_the_flush(script: str) -> None:
    # A `journalctl -f` opened before /var/log/journal exists never watches
    # it and goes silent, still running, when journald flushes and drops the
    # runtime journal; correct installs failed on the empty ttyS2 log (#550).
    text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
    unit = re.search(r"""^cat > "\$\{state\}/journal\.service" <<'EOF'\n(.*?)^EOF$""", text, re.M | re.S)
    assert unit, f"no journal.service in {script}"
    lines = unit[1].splitlines()
    assert "ExecStart=journalctl -b -f --no-pager -o short-monotonic" in lines
    assert "After=systemd-journal-flush.service" in lines


class _FakeMonitor:
    """A stand-in QEMU monitor: a Unix socket that accepts and drains the
    sendkeys type_keys types on, so the script never blocks sending. Under
    console noise type_keys widens its per-key gap, so typing the whole
    string takes longer (#600)."""

    def __init__(self, path: Path) -> None:
        if path.exists():
            path.unlink()
        self._srv = socket.socket(socket.AF_UNIX)
        self._srv.bind(str(path))
        self._srv.listen(1)
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> "_FakeMonitor":
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        try:
            self._srv.close()
        except OSError:
            pass

    def _serve(self) -> None:
        try:
            conn, _ = self._srv.accept()
        except OSError:
            return
        while conn.recv(4096):
            pass
        conn.close()


def type_keys_elapsed(tmp_path: Path, text: str, console_noise: str) -> float:
    """Seconds type_keys takes to type <text>; the noise-widened gap is
    roughly twice the quiet one over the same string."""
    with _FakeMonitor(tmp_path / "t.mon"):
        script = (
            "set -euo pipefail\n"
            f'state="{tmp_path}"\n'
            + function("type_keys")
            + 'console_noise="$TK_NOISE"\n'
            + 'type_keys "t" "$TK_TEXT"\n'
        )
        env = os.environ.copy()
        env["TK_TEXT"] = text
        env["TK_NOISE"] = console_noise
        env.pop("COVERAGE_PROCESS_CONFIG", None)
        start = time.monotonic()
        result = subprocess.run(
            ["bash", "-c", script, "type_keys"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        elapsed = time.monotonic() - start
    assert result.returncode == 0, result.stderr
    return elapsed


def test_type_keys_widens_its_gap_under_console_noise(tmp_path: Path) -> None:
    text = "1234567890\n"
    quiet = type_keys_elapsed(tmp_path, text, "0")
    noisy = type_keys_elapsed(tmp_path, text, "1")
    # Eleven keys at 0.15s vs 0.35s are about 2.2s apart; this separates the
    # two without depending on per-key scheduling jitter.
    assert quiet < 3.0, f"quiet gap unexpectedly large: {quiet:.2f}s"
    assert noisy > 3.5, f"noise gap unexpectedly small: {noisy:.2f}s"
