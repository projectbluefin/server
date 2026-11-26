"""countme: the image's declared identity and the reporter it ships.

os-image-info.bst writes /usr/share/ublue-os/image-info.json, which the
reporter (files/os/libexec/projectbluefin-countme) reads. os-countme.bst
installs that reporter from this repository — Bluefin Server is a standalone
DDI and does not consume projectbluefin/common. The reporter's service, timer,
and preset ship with the other base-OS units and presets (os-k0s-first-boot.bst,
os-sshd-preset.bst).
"""


import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ELEMENTS = REPO_ROOT / "elements" / "bluefin-server"
FILES = REPO_ROOT / "files" / "os"
TRANSFERS = FILES / "sysupdate.d"
SYSTEM_UNITS = FILES / "systemd" / "system"
PRESETS = FILES / "systemd" / "system-preset"
REPORTER = FILES / "libexec" / "projectbluefin-countme"


def _element(name: str) -> dict:
    return yaml.safe_load((ELEMENTS / name).read_text(encoding="utf-8"))


def _image_info() -> dict:
    commands = "\n".join(_element("os-image-info.bst")["config"]["install-commands"])
    body = re.search(r"<<'JSON'\n(.*?)\n\s*JSON\s*$", commands, re.S | re.M)
    assert body, "os-image-info.bst must write image-info.json from a JSON heredoc"
    return json.loads(body.group(1))


def _transfer_channels() -> set[str]:
    channels = set()
    for transfer in TRANSFERS.glob("*.transfer"):
        for path in re.findall(r"^Path=(https://\S+)$", transfer.read_text(encoding="utf-8"), re.M):
            match = re.fullmatch(r"https://github\.com/[^/]+/[^/]+/releases/(.+)/download/", path)
            assert match, f"{transfer.name}: unexpected source Path={path}"
            channels.add(match.group(1))
    return channels


def test_image_info_declares_name_and_stream_only():
    # No image-flavor: a DDI has no flavors, and a guessed one would be counted
    # as a real population (projectbluefin/server#97).
    assert _image_info() == {"image-name": "server", "image-tag": "latest"}


def test_image_tag_is_the_channel_sysupdate_follows():
    # The tag is the stream, not the version: it must name the one GitHub
    # Releases channel every transfer pulls from, and change with it.
    channels = _transfer_channels()
    assert channels == {"latest"}, f"transfers follow {sorted(channels)}"
    assert _image_info()["image-tag"] in channels


def test_countme_is_server_native_not_common():
    # Server is a standalone DDI: the reporter is installed from this repository,
    # not a projectbluefin/common checkout.
    element = _element("os-countme.bst")
    assert element["kind"] == "manual"
    assert element["sources"] == [
        {"kind": "local", "path": "files/os/libexec", "directory": "libexec-src"}
    ]
    commands = " ".join(element["config"]["install-commands"])
    assert "system_files/shared" not in commands
    assert "github:projectbluefin/common.git" not in commands
    assert "install -Dm0755 libexec-src/projectbluefin-countme" in commands
    assert '"%{install-root}/usr/libexec/projectbluefin-countme"' in commands


def test_countme_units_and_preset_ship_with_base_os():
    # the service and timer ship through os-k0s-first-boot.bst (import of
    # files/os/systemd/system); the preset ships through os-sshd-preset.bst
    # (import of files/os/systemd/system-preset).
    stack = _element("os-stack.bst")["depends"]
    assert "bluefin-server/os-k0s-first-boot.bst" in stack
    assert "bluefin-server/os-sshd-preset.bst" in stack

    for name in (
        "projectbluefin-countme.service",
        "projectbluefin-countme.timer",
    ):
        assert (SYSTEM_UNITS / name).is_file(), name
    assert (PRESETS / "80-bluefin-countme.preset").is_file()

    service = (SYSTEM_UNITS / "projectbluefin-countme.service").read_text(encoding="utf-8")
    assert "/usr/libexec/projectbluefin-countme" in service
    assert "StateDirectory=projectbluefin-countme" in service

    timer = (SYSTEM_UNITS / "projectbluefin-countme.timer").read_text(encoding="utf-8")
    assert "WantedBy=timers.target" in timer

    preset = (PRESETS / "80-bluefin-countme.preset").read_text(encoding="utf-8")
    assert "enable projectbluefin-countme.timer" in preset


def _unit_section(text: str, section: str) -> list[str]:
    lines, current = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
        elif current == section and line and not line.startswith("#"):
            lines.append(line)
    return lines


def test_disabled_file_opt_out_gates_the_service():
    # os-countme.bst documents creating /etc/projectbluefin/countme/disabled as
    # an opt-out next to masking the timer. Only this [Unit] condition makes
    # that file work: without it the reporter still pings.
    service = (SYSTEM_UNITS / "projectbluefin-countme.service").read_text(encoding="utf-8")
    unit = _unit_section(service, "Unit")
    assert "ConditionPathExists=!/etc/projectbluefin/countme/disabled" in unit
    assert "/etc/projectbluefin/countme/disabled" in _element("os-countme.bst")["description"]


def test_reporter_reads_image_info_and_reports_server():
    script = REPORTER.read_text(encoding="utf-8")
    assert "/usr/share/ublue-os/image-info.json" in script
    # Exact image-name gate: only Bluefin Server reports, anything else exits.
    assert "[[ $name == server ]]" in script
    assert 'image="server/main:$tag"' in script
    # A DDI has no bootc ref and no /run/ostree-booted: the reporter must not
    # run bootc or gate on the ostree boot marker.
    assert "bootc status" not in script
    assert "/run/ostree-booted" not in script
    # Server-owned, not pulled from the shared common reporter.
    assert "projectbluefin/common" not in script


def _utc_day(offset_seconds: float = 0) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + offset_seconds))


def _run_reporter(
    tmp_path: Path,
    image_info: dict,
    *,
    curl_rc: int = 0,
    last_date: str | None = None,
) -> tuple[subprocess.CompletedProcess, list[str], Path]:
    """Run the real reporter with a stub curl, temp identity, and temp state."""
    if shutil.which("jq") is None:
        pytest.skip("jq is required for the reporter behavior tests")
    state = tmp_path / "state"
    state.mkdir()
    info = tmp_path / "image-info.json"
    info.write_text(json.dumps(image_info), encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "curl-calls"
    stub = bin_dir / "curl"
    stub.write_text(
        "#!/usr/bin/bash\n"
        f'printf "%s\\n" "$*" >> "{calls}"\n'
        f"exit {curl_rc}\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    if last_date is not None:
        (state / "last").write_text(f"{last_date}\n", encoding="utf-8")
    env = {
        **os.environ,
        "IMAGE_INFO": str(info),
        "STATE_DIRECTORY": str(state),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }
    result = subprocess.run(
        ["/usr/bin/bash", str(REPORTER)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    logged = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return result, logged, state


def test_first_launch_reports_server_latest(tmp_path):
    result, calls, state = _run_reporter(
        tmp_path, {"image-name": "server", "image-tag": "latest"}
    )
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1, calls
    assert "https://countme.projectbluefin.io/v1/ping" in calls[0]
    assert '{"image":"server/main:latest"}' in calls[0]
    assert (state / "last").read_text(encoding="utf-8").strip() == _utc_day()


def test_same_utc_day_is_suppressed(tmp_path):
    result, calls, _ = _run_reporter(
        tmp_path,
        {"image-name": "server", "image-tag": "latest"},
        last_date=_utc_day(),
    )
    assert result.returncode == 0
    assert calls == [], "the recorded UTC day suppresses a second ping"


def test_a_new_utc_day_reports_again(tmp_path):
    _, calls, _ = _run_reporter(
        tmp_path,
        {"image-name": "server", "image-tag": "latest"},
        last_date=_utc_day(-86400),
    )
    assert len(calls) == 1, "the next UTC day reports even under 24h later"


def test_failed_send_does_not_record_the_day(tmp_path):
    result, calls, state = _run_reporter(
        tmp_path,
        {"image-name": "server", "image-tag": "latest"},
        curl_rc=1,
    )
    assert result.returncode == 0, "a failed send exits 0 so the timer retries"
    assert len(calls) == 1
    assert not (state / "last").exists(), "no stamp means the next run retries"


@pytest.mark.parametrize(
    "image_info",
    [
        {"image-name": "dakota", "image-tag": "latest"},
        {"image-name": "server", "image-tag": ""},
        {},
    ],
)
def test_unreportable_images_never_call_curl(tmp_path, image_info):
    result, calls, _ = _run_reporter(tmp_path, image_info)
    assert result.returncode == 0
    assert calls == []


def test_an_invalid_tag_reports_unknown(tmp_path):
    _, calls, _ = _run_reporter(
        tmp_path, {"image-name": "server", "image-tag": "2026.11.19"}
    )
    assert len(calls) == 1
    assert '{"image":"server/main:unknown"}' in calls[0]
