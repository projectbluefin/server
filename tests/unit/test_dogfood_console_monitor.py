"""Exercise in-script monitor plumbing, not native firmware/UI coverage."""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEXT = (ROOT / "scripts/dogfood-installer.sh").read_text()


def function(name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", TEXT, re.M | re.S)
    assert match, name
    return match[0]


@pytest.mark.parametrize("abort", [False, True])
def test_short_monitor_input_and_cleanup(tmp_path: Path, abort: bool) -> None:
    state = tmp_path / ("long-state-" * 15)
    state.mkdir()
    qemu = tmp_path / "qemu"
    qemu.write_text("""#!/usr/bin/env python3
import json, socket, sys
from pathlib import Path
args = sys.argv[1:]
monitor = args[args.index('-monitor') + 1].split(',')[0].removeprefix('unix:')
state = Path(args[args.index('-serial') + 1].removeprefix('file:')).parent
(state / 'qemu-args.json').write_text(json.dumps(args))
with socket.socket(socket.AF_UNIX) as server:
    server.bind(monitor)
    server.listen(1)
    (state / 'ready').touch()
    conn, _ = server.accept()
    with conn, (state / 'commands').open('wb') as commands:
        while data := conn.recv(4096):
            commands.write(data)
""")
    qemu.chmod(0o755)
    script = (
        'set -euo pipefail\nstate="$1"; timeout_s=10\n'
        + function("cleanup")
        + function("boot_start")
        + function("type_keys")
        + f'qemu=({shlex.quote(str(qemu))}); trap cleanup EXIT\n'
        + 'boot_start 2-install -nic none\n'
        + 'printf "%s\\n%s\\n" "${monitor_path}" "${qemu_pid}" > "${state}/identity"\n'
        + 'for ((n=0; n<100; n++)); do [ ! -f "${state}/ready" ] || break; sleep 0.02; done\n'
        + 'test -f "${state}/ready"\n'
        + ('exit 7\n' if abort else 'type_keys 2-install $\'a\\n\'\nwait "${qemu_pid}"\n')
    )
    result = subprocess.run(
        ["bash", "-c", script, "monitor", str(state)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == (7 if abort else 0), result.stderr
    monitor, pid = (state / "identity").read_text().splitlines()
    args = json.loads((state / "qemu-args.json").read_text())
    assert args.count("-monitor") == 1
    assert "-S" not in args
    assert len(monitor.encode()) < 108
    assert args[args.index("-monitor") + 1] == f"unix:{monitor},server=on,wait=off"
    assert not Path(monitor).parent.exists(), "socket directory leaked"
    assert not Path(f"/proc/{pid}").exists(), "guest leaked"
    if not abort:
        commands = (state / "commands").read_text()
        assert "sendkey a" in commands
        assert "sendkey ret" in commands


def test_install_stays_in_script_with_native_postconditions(tmp_path: Path) -> None:
    assert "DOGFOOD_CONSOLE_DRIVER" not in TEXT
    assert "run_console_driver" not in TEXT
    install = function("console_install")
    assert install.count('check_console_install "${name}"') == 1
    assert 'type_keys "${name}"' in install
    assert "mcopy -o" in TEXT
    (tmp_path / "2-install.ttyS1.log").write_text("")
    script = (
        'state="$1"; target_dev=/dev/disk/by-id/virtio-bluefin-target\n'
        'fail() { echo "$*" >&2; exit 1; }\n'
        'check_done_screen() { echo "unexpected done check"; }\n'
        + function("check_console_install")
        + 'check_console_install 2-install\n'
    )
    result = subprocess.run(["bash", "-c", script, "probes", str(tmp_path)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "expected the ESP and usr slot A" in result.stderr
    assert "unexpected done check" not in result.stdout


def test_console_frames_expose_geometry_without_changing_cursor_field() -> None:
    assert 'read -r rows cols x y < <(od -An -tu1 -N4 /dev/vcsa)' in TEXT
    assert 'screen="rows ${rows} cols ${cols} x ${x} cursor ${y}' in TEXT
    assert 'printf \'=== console %s printk=%s mute=%s noise=%s\\n\'' in TEXT
