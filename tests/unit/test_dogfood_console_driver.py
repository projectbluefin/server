"""Exercise the optional driver handoff, not native firmware/UI coverage."""
from __future__ import annotations

import json
import os
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


def executable(path: Path, content: str) -> Path:
    path.write_text(content)
    path.chmod(0o755)
    return path


def handoff(tmp_path: Path, driver_body: str, seconds: int = 10) -> tuple[subprocess.CompletedProcess, Path]:
    # Well beyond sun_path's limit: only the monitor, not evidence, belongs
    # in the short private socket directory.
    state = tmp_path / ("long-state-" * 15)
    state.mkdir()
    qemu = executable(tmp_path / "qemu", """#!/usr/bin/env python3
import json, socket, sys
from pathlib import Path
args = sys.argv[1:]
monitor = args[args.index('-monitor') + 1].split(',')[0].removeprefix('unix:')
state = Path(args[args.index('-serial') + 1].removeprefix('file:')).parent
(state / 'qemu-args.json').write_text(json.dumps(args))
with socket.socket(socket.AF_UNIX) as server:
    server.bind(monitor)
    server.listen(1)
    conn, _ = server.accept()
    with conn, (state / 'commands').open('wb') as commands:
        while data := conn.recv(4096):
            commands.write(data)
""")
    driver = executable(tmp_path / "driver with spaces", "#!/usr/bin/env python3\n" + driver_body)
    script = (
        'set -euo pipefail\nstate="$1"; console_driver="$2"; timeout_s="$3"\n'
        'profile=minimal; target_dev=/dev/disk/by-id/virtio-bluefin-target; ver=0.450\n'
        'fail() { echo "FAIL: $*" >&2; exit 1; }\n'
        + function("cleanup")
        + function("boot_start")
        + function("run_console_driver")
        + f'qemu=({shlex.quote(str(qemu))}); trap cleanup EXIT\n'
        + 'boot_with_driver=1 boot_start 2-install -nic none\n'
        + 'run_console_driver 2-install\n'
        + 'wait "${qemu_pid}"\n'
    )
    result = subprocess.run(
        ["bash", "-c", script, "handoff", str(state), str(driver), str(seconds)],
        capture_output=True, text=True, timeout=20,
    )
    return result, state


DRIVER = """import json, socket, sys, time
from pathlib import Path
manifest = json.loads(Path(sys.argv[1]).read_text())
assert manifest['version'] == 1 and manifest['paused'] is True
assert manifest['profile'] == 'minimal'
assert manifest['target_device'] == '/dev/disk/by-id/virtio-bluefin-target'
assert manifest['image_version'] == '0.450'
assert manifest['qemu_pid'] > 0
assert manifest['deadline_unix'] > time.time()
assert Path(manifest['screen_log']).parent == Path(manifest['state_dir'])
assert set(manifest['serial_logs']) == {'ttyS0', 'ttyS1', 'ttyS2'}
assert len(manifest['monitor'].encode()) < 108
with socket.socket(socket.AF_UNIX) as monitor:
    for attempt in range(100):
        try:
            monitor.connect(manifest['monitor'])
            break
        except (FileNotFoundError, ConnectionRefusedError):
            time.sleep(0.01)
    else:
        raise RuntimeError('monitor never ready')
    monitor.sendall(b'cont\\nsendkey down\\nsendkey ret\\n')
"""


def test_driver_receives_actual_short_monitor_and_paused_guest(tmp_path: Path) -> None:
    result, state = handoff(tmp_path, DRIVER)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((state / "2-install.driver.json").read_text())
    args = json.loads((state / "qemu-args.json").read_text())
    assert args.count("-monitor") == 1
    assert "-S" in args
    assert args[args.index("-monitor") + 1] == f"unix:{manifest['monitor']},server=on,wait=off"
    assert (state / "commands").read_text() == "cont\nsendkey down\nsendkey ret\n"
    assert not Path(manifest["monitor"]).parent.exists(), "socket directory leaked"
    assert "password" not in (state / "2-install.driver.json").read_text()


@pytest.mark.parametrize("body,seconds", [("import sys; sys.exit(7)\n", 10), ("import time; time.sleep(30)\n", 3)])
def test_driver_error_or_timeout_fails_and_cleans_up(tmp_path: Path, body: str, seconds: int) -> None:
    result, state = handoff(tmp_path, body, seconds)
    assert result.returncode != 0
    assert "console driver failed or exceeded the boot deadline" in result.stderr
    manifest = json.loads((state / "2-install.driver.json").read_text())
    assert not Path(manifest["monitor"]).parent.exists()
    assert not Path(f"/proc/{manifest['qemu_pid']}").exists(), "guest leaked"


def test_successful_driver_cannot_replace_install_probes(tmp_path: Path) -> None:
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


def test_builtin_and_external_paths_share_postconditions() -> None:
    install = function("console_install")
    assert install.count('check_console_install "${name}"') == 2
    assert 'boot_with_driver="${console_driver:+1}" boot_start' in install
    # No driver means the historical default selection, not a new UI path.
    loader = TEXT[TEXT.index("# Built-in runs reuse"):TEXT.index("\nfail()")]
    assert 'if [ -z "${console_driver}" ]; then' in loader
    assert "mcopy -o" in loader


@pytest.mark.parametrize("mode,extra", [
    ("unattended", {}), ("diskless-console", {}),
    ("console", {"DOGFOOD_CONSOLE_NOISE": "1"}),
    ("console", {"DOGFOOD_CONSOLE_FAILURE": "kernel"}),
])
def test_unsupported_driver_combinations_fail_before_disk_creation(tmp_path: Path, mode: str, extra: dict) -> None:
    script = ROOT / "scripts/dogfood-installer.sh"
    driver = executable(tmp_path / "driver", "#!/bin/sh\nexit 0\n")
    result = subprocess.run(
        ["bash", str(script), str(tmp_path)], capture_output=True, text=True,
        env=os.environ | {"DOGFOOD_INSTALL": mode, "DOGFOOD_CONSOLE_DRIVER": str(driver)} | extra,
    )
    assert result.returncode != 0
    assert "requires console mode without noise/failure injection" in result.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["driver"]


def test_console_frames_expose_geometry_without_changing_cursor_field() -> None:
    assert 'read -r rows cols x y < <(od -An -tu1 -N4 /dev/vcsa)' in TEXT
    assert 'screen="rows ${rows} cols ${cols} x ${x} cursor ${y}' in TEXT
    assert 'printf \'=== console %s printk=%s mute=%s noise=%s\\n\'' in TEXT
