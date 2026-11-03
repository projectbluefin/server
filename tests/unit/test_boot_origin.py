"""Executed coverage for bluefin-boot-origin: the initrd's shell copy
(files/boot-origin/usr/libexec/bluefin-boot-origin) and the booted OS's
(bluefin-host, elements/bluefin-server/os-host.bst) run the same cases.

The helper prints the URL a network-booted node was booted from. Ignition in
the initrd looks for bluefin-node.ign next to it, and the diskless update check
fetches the signed SHA256SUMS from its directory.
"""


import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = ROOT / "files" / "boot-origin" / "usr" / "libexec" / "bluefin-boot-origin"
PULL = "raw,machine,verify=signature,blockdev:rootdisk:{url}"


@pytest.fixture(params=["initrd", "bluefin-host"])
def helper(request: pytest.FixtureRequest) -> Path:
    if request.param == "initrd":
        return ORIGIN
    return request.getfixturevalue("host_bin") / "bluefin-boot-origin"


def origin(helper: Path, tmp_path: Path, *, stub: str | None = None, cmdline: str = "", cred: str | None = None):
    stub_var = tmp_path / "StubDeviceURL"
    if stub is not None:
        stub_var.write_bytes(b"\x06\x00\x00\x00" + stub.encode("utf-16-le") + b"\x00\x00")
    (tmp_path / "cmdline").write_text(cmdline + "\n", encoding="utf-8")
    env = dict(os.environ, BLUEFIN_STUB_URL_VAR=str(stub_var), BLUEFIN_CMDLINE=str(tmp_path / "cmdline"))
    env.pop("CREDENTIALS_DIRECTORY", None)
    if cred is not None:
        creds = tmp_path / "creds"
        creds.mkdir()
        (creds / "import.pull").write_text(cred + "\n", encoding="utf-8")
        env["CREDENTIALS_DIRECTORY"] = str(creds)
    return subprocess.run([str(helper)], capture_output=True, text=True, env=env)


def test_origin_prefers_the_uefi_http_boot_url(helper: Path, tmp_path: Path) -> None:
    result = origin(
        helper,
        tmp_path,
        stub="http://booty/bluefin/52-54-00-aa-00-02/bluefin-server-netboot.efi",
        cmdline="rd.systemd.pull=" + PULL.format(url="http://other/x.raw"),
    )
    assert result.returncode == 0
    assert result.stdout == "http://booty/bluefin/52-54-00-aa-00-02/bluefin-server-netboot.efi\n"


def test_origin_uses_the_explicit_pull_url_on_the_cmdline(helper: Path, tmp_path: Path) -> None:
    result = origin(helper, tmp_path, cmdline="root=tmpfs rd.systemd.pull=" + PULL.format(url="https://srv/r/bluefin-server_1.raw") + " quiet")
    assert (result.returncode, result.stdout) == (0, "https://srv/r/bluefin-server_1.raw\n")


def test_origin_falls_back_to_the_import_pull_credential(helper: Path, tmp_path: Path) -> None:
    result = origin(
        helper,
        tmp_path,
        cmdline="rd.systemd.pull=raw,machine,verify=signature,blockdev,bootorigin:rootdisk:bluefin-server_1.raw",
        cred=PULL.format(url="http://10.0.2.2:8765/bluefin-server_1.raw"),
    )
    assert (result.returncode, result.stdout) == (0, "http://10.0.2.2:8765/bluefin-server_1.raw\n")


def test_origin_fails_quietly_when_not_network_booted(helper: Path, tmp_path: Path) -> None:
    result = origin(helper, tmp_path, cmdline="rd.systemd.pull=raw,machine,blockdev,bootorigin:rootdisk:x.raw")
    assert (result.returncode, result.stdout) == (1, "")


def test_ignition_uses_the_shared_origin_helper() -> None:
    helper = (ROOT / "files" / "initrd-ignition" / "usr" / "libexec" / "bluefin-ignition-credentials").read_text(encoding="utf-8")
    assert 'BOOT_ORIGIN="${BLUEFIN_BOOT_ORIGIN:-/usr/libexec/bluefin-boot-origin}"' in helper
    assert "efivars" not in helper and "/proc/cmdline" not in helper, "one copy of the origin logic"


def test_helper_ships_in_the_initrd_and_is_executable_bash() -> None:
    elements = ROOT / "elements" / "bluefin-server"
    doc = yaml.safe_load((elements / "boot-origin.bst").read_text(encoding="utf-8"))
    assert doc["kind"] == "import"
    assert doc["sources"] == [{"kind": "local", "path": "files/boot-origin"}]
    assert "target" not in (doc.get("config") or {}), "the tree mirrors /usr"
    ign = yaml.safe_load((elements / "initrd" / "initrd-ignition-stack.bst").read_text(encoding="utf-8"))
    assert "bluefin-server/boot-origin.bst" in ign["depends"]
    stack = yaml.safe_load((elements / "os-stack.bst").read_text(encoding="utf-8"))
    assert "bluefin-server/boot-origin.bst" not in stack["depends"], "bluefin-host links it in /usr"
    assert ORIGIN.read_text(encoding="utf-8").startswith("#!/usr/bin/bash\n")
    assert ORIGIN.stat().st_mode & stat.S_IXUSR
    subprocess.run(["bash", "-n", str(ORIGIN)], check=True)
