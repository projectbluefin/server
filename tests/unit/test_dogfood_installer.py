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


import re
import shlex
import socket
import subprocess
import threading
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


# DOGFOOD_INSTALL=diskless-console (#450) types the documented install at a
# diskless node's console and answers systemd-sysinstall's questions.

def diskless_commands() -> str:
    script = (
        f'here={shlex.quote(str(SCRIPT.parent))}\n'
        + function("diskless_install_command")
        + "diskless_install_command\n"
    )
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    return out.stdout


def test_the_documented_diskless_install_leaves_the_disk_question_to_sysinstall() -> None:
    commands = diskless_commands()
    joined = commands.replace("\\\n", " ")
    install = next((line for line in joined.splitlines() if line.startswith("systemd-sysinstall ")), None)
    assert install, commands
    # A disk named on the command line skips the question the harness answers.
    args = shlex.split(install)[1:]
    assert args and all(arg.startswith("--") for arg in args), install


# QEMU key names for a US layout, read back into the characters they type.
UNSHIFTED = {"spc": " ", "ret": "\n", "ctrl-u": "\x15", "minus": "-", "dot": ".", "slash": "/", "equal": "=",
             "comma": ",", "semicolon": ";", "apostrophe": "'", "grave_accent": "`", "backslash": "\\",
             "bracket_left": "[", "bracket_right": "]"}
SHIFTED = {"1": "!", "2": "@", "3": "#", "4": "$", "5": "%", "6": "^", "7": "&", "8": "*", "9": "(", "0": ")",
           "minus": "_", "equal": "+", "semicolon": ":", "apostrophe": '"', "grave_accent": "~",
           "backslash": "|", "bracket_left": "{", "bracket_right": "}", "comma": "<", "dot": ">", "slash": "?"}


def typed(key: str) -> str:
    if key.startswith("shift-"):
        base = key.removeprefix("shift-")
        return SHIFTED.get(base, base.upper() if len(base) == 1 and base.isalpha() else f"<{key}>")
    return UNSHIFTED.get(key, key if len(key) == 1 and key.isalnum() and not key.isupper() else f"<{key}>")


def type_keys(tmp_path: Path, text: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    """type_keys on a stand-in QEMU monitor; the sendkey commands it received."""
    received: list[bytes] = []
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(tmp_path / "t.mon"))
        server.listen(1)
        server.settimeout(60)

        def serve() -> None:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                while data := conn.recv(4096):
                    received.append(data)

        thread = threading.Thread(target=serve)
        thread.start()
        script = 'state="$1"\n' + function("type_keys") + 'type_keys t "$2"\n'
        result = subprocess.run(["bash", "-c", script, "type_keys", str(tmp_path), text],
                                capture_output=True, text=True, timeout=120)
        server.close()
        thread.join()
    lines = b"".join(received).decode().splitlines()
    assert all(line.startswith("sendkey ") for line in lines), lines
    return result, [line.removeprefix("sendkey ") for line in lines]


def test_every_character_of_the_documented_install_is_typed_as_itself(tmp_path: Path) -> None:
    # Each distinct character once (typing is paced like a person), plus the
    # Ctrl-U that clears a question's preselected answer.
    text = "".join(sorted(set(diskless_commands()))) + "\x15yes\n"
    result, keys = type_keys(tmp_path, text)
    assert result.returncode == 0, result.stderr
    assert "".join(typed(k) for k in keys) == text


def test_a_character_without_a_key_types_nothing(tmp_path: Path) -> None:
    result, keys = type_keys(tmp_path, "ls\u00e9\n")
    assert result.returncode != 0
    assert "no key for" in result.stderr
    assert keys == []


def wait_question(tmp_path: Path, screen: str, question: str) -> subprocess.CompletedProcess:
    (tmp_path / "q.screen.log").write_text(screen, encoding="utf-8")
    last_screen = re.search(r"^last_screen\(\) \{.*\}$", TEXT, re.M)
    assert last_screen
    script = (
        'set -euo pipefail; state="$1"\n'
        'fail() { echo "FAIL: $*" >&2; exit 1; }\n'
        + last_screen[0] + "\n" + function("wait_question")
        + "sleep 300 </dev/null >/dev/null 2>&1 &\nqemu_pid=$!\n"
        "trap 'kill \"${qemu_pid}\" 2>/dev/null || true' EXIT\n"
        'wait_question q "$2" 2\n'
    )
    return subprocess.run(["bash", "-c", script, "wait_question", str(tmp_path), question],
                          capture_output=True, text=True, timeout=60)


ERASE = ("Please type 'keep' to install the OS in addition to what the disk already contains, "
         "or 'erase' to erase all data on the disk")


def snapshot(text: str, width: int = 40) -> str:
    """A screen snapshot as the mirror writes it: folded at the screen width, trailing blanks cut."""
    rows = [text[i:i + width].rstrip() for i in range(0, len(text), width)]
    return f"=== screen 1.0 cursor {len(rows) - 1}\n" + "\n".join(rows) + "\n"


def test_a_question_wider_than_the_screen_is_found(tmp_path: Path) -> None:
    screen = snapshot("Required minimal installation disk size is 2.1G.") + snapshot(f"? {ERASE}: ")
    result = wait_question(tmp_path, screen, ERASE)
    assert result.returncode == 0, result.stderr


def test_a_question_no_longer_on_the_screen_is_not_found(tmp_path: Path) -> None:
    screen = snapshot(f"? {ERASE}: erase") + snapshot("Summary: Selected Disk: /dev/vdb")
    result = wait_question(tmp_path, screen, ERASE)
    assert result.returncode != 0
    assert "the monitor never showed" in result.stderr
