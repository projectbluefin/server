"""Executed coverage for the diskless update signal.

bluefin-boot-origin finds the URL a node booted from; bluefin-diskless-update-check
fetches the signed SHA256SUMS from that directory and flags /run/reboot-required
when it offers a newer release that the next boot would pull, i.e. unless the
origin names a versioned file (a pinned node only logs it). Both run here against a local http.server and a
throwaway GnuPG key; no files/boot-keys are needed.
"""

from __future__ import annotations

import configparser
import functools
import os
import shutil
import stat
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = ROOT / "files" / "boot-origin" / "usr" / "libexec" / "bluefin-boot-origin"
CHECK = ROOT / "files" / "os" / "update-check" / "usr" / "libexec" / "bluefin-diskless-update-check"
RUNNING = "26.09.2"
PULL = "raw,machine,verify=signature,blockdev:rootdisk:{url}"

UNITS = ROOT / "files" / "os" / "systemd" / "system"
ELEMENTS = ROOT / "elements" / "bluefin-server"
needs_tools = pytest.mark.skipif(
    not all(shutil.which(t) for t in ("curl", "gpg", "gpgv", "systemd-analyze")),
    reason="needs curl, gpg, gpgv and systemd-analyze",
)


def ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def test_check_runs_only_on_diskless_boots() -> None:
    service = ini(UNITS / "bluefin-diskless-update-check.service")
    timer = ini(UNITS / "bluefin-diskless-update-check.timer")
    for unit in (service, timer):
        assert unit["Unit"]["ConditionPathExists"] == "/run/machines/rootdisk.raw"
    assert service["Service"]["Type"] == "oneshot"
    assert service["Service"]["ImportCredential"] == "import.pull"
    assert service["Service"]["ExecStart"] == "/usr/libexec/bluefin-diskless-update-check"
    assert service["Unit"]["After"] == "network-online.target"
    assert timer["Install"]["WantedBy"] == "timers.target"


def test_check_ships_in_the_os_and_is_executable_bash() -> None:
    stack = yaml.safe_load((ELEMENTS / "os-stack.bst").read_text(encoding="utf-8"))["depends"]
    assert "bluefin-server/os-update-check.bst" in stack
    assert "bluefin-server/boot-origin.bst" in stack
    doc = yaml.safe_load((ELEMENTS / "os-update-check.bst").read_text(encoding="utf-8"))
    assert doc["kind"] == "import"
    assert doc["sources"] == [{"kind": "local", "path": "files/os/update-check"}]
    assert "target" not in (doc.get("config") or {}), "the tree mirrors /usr"
    assert CHECK.read_text(encoding="utf-8").startswith("#!/usr/bin/bash\n")
    assert CHECK.stat().st_mode & stat.S_IXUSR
    subprocess.run(["bash", "-n", str(CHECK)], check=True)


@pytest.fixture(scope="module")
def keys(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("gpg")
    out = {}
    for name in ("release", "stranger"):
        home = base / name
        home.mkdir(mode=0o700)
        env = dict(os.environ, GNUPGHOME=str(home))
        subprocess.run(
            ["gpg", "--batch", "--quiet", "--passphrase", "", "--quick-gen-key", f"{name} <{name}@example.invalid>", "ed25519", "sign", "never"],
            check=True, env=env, capture_output=True,
        )
        ring = base / f"{name}.pgp"
        subprocess.run(["gpg", "--batch", "--export", "--output", str(ring)], check=True, env=env)
        out[name] = home
        out[f"{name}-ring"] = ring
    return out


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


@pytest.fixture()
def server(tmp_path: Path):
    root = tmp_path / "srv"
    (root / "rel").mkdir(parents=True)
    handler = functools.partial(QuietHandler, directory=str(root))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield root / "rel", f"http://127.0.0.1:{httpd.server_address[1]}/rel"
    httpd.shutdown()
    httpd.server_close()


def publish(
    directory: Path, version: str, gnupghome: Path, *, tamper: bool = False, sign: bool = True, also: tuple[str, ...] = ()
) -> None:
    names = [
        name
        for v in [*also, version]
        for name in (
            f"bluefin-server_{v}.raw",
            f"bluefin-server_{v}_d3107d37-a9da-32cf-3c19-49fa3b0cb1df.usr.raw",
            f"bluefin-server-{v}.efi",
            f"bluefin-server-netboot_{v}.efi",
            f"bluefin-server-installer_{v}.raw",
            f"zfs_{v}.raw.zst",
        )
    ]
    sums = "".join(f"{i:064x}  {name}\n" for i, name in enumerate(names))
    (directory / "SHA256SUMS").write_text(sums, encoding="utf-8")
    if sign:
        subprocess.run(
            ["gpg", "--batch", "--yes", "--detach-sign", "--output", str(directory / "SHA256SUMS.gpg"), str(directory / "SHA256SUMS")],
            check=True, env=dict(os.environ, GNUPGHOME=str(gnupghome)), capture_output=True,
        )
    if tamper:
        (directory / "SHA256SUMS").write_text(sums.replace(version, "99.99.99"), encoding="utf-8")


PINNED_RAW = f"bluefin-server_{RUNNING}.raw"
NETBOOT_UKI = "bluefin-server-netboot.efi"


def check(tmp_path: Path, url: str | None, keyring: Path, *, via: str = "stub", file: str = NETBOOT_UKI):
    """Run the check with the boot origin <url>/<file> handed over <via>:
    "cmdline" (rd.systemd.pull=), "cred" (the import.pull credential) or
    "stub" (the StubDeviceURL EFI variable of a UEFI HTTP boot)."""
    os_release = tmp_path / "os-release"
    os_release.write_text(f'ID=bluefin-server\nIMAGE_ID=bluefin-server\nIMAGE_VERSION="{RUNNING}"\n', encoding="utf-8")
    sentinel = tmp_path / "run" / "reboot-required"
    pull = PULL.format(url=f"{url}/{file}") if url else ""
    env = dict(
        os.environ,
        BLUEFIN_BOOT_ORIGIN=str(ORIGIN),
        BLUEFIN_IMPORT_KEYRING=str(keyring),
        BLUEFIN_REBOOT_SENTINEL=str(sentinel),
        BLUEFIN_OS_RELEASE=str(os_release),
        BLUEFIN_STUB_URL_VAR=str(tmp_path / "no-efivar"),
        BLUEFIN_CMDLINE=str(tmp_path / "cmdline"),
    )
    env.pop("CREDENTIALS_DIRECTORY", None)
    cmdline = "root=tmpfs"
    if url and via == "cred":
        (tmp_path / "creds").mkdir()
        (tmp_path / "creds" / "import.pull").write_text(pull + "\n", encoding="utf-8")
        env["CREDENTIALS_DIRECTORY"] = str(tmp_path / "creds")
    elif url and via == "stub":
        # efivarfs: 4 attribute bytes, then a NUL-terminated UTF-16LE string.
        stub = tmp_path / "StubDeviceURL"
        stub.write_bytes(b"\x06\x00\x00\x00" + f"{url}/{file}\0".encode("utf-16-le"))
        env["BLUEFIN_STUB_URL_VAR"] = str(stub)
    elif url:
        cmdline = "rd.systemd.pull=" + pull
    (tmp_path / "cmdline").write_text(cmdline + "\n", encoding="utf-8")
    result = subprocess.run([str(CHECK)], capture_output=True, text=True, env=env, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return sentinel.exists(), result.stdout + result.stderr


@needs_tools
@pytest.mark.parametrize(
    "via,file",
    [
        # Booty's HTTP boot URL: the served UKI changes, and the next boot
        # pulls the image next to it.
        ("stub", NETBOOT_UKI),
        # An unversioned name the boot server repoints at each release.
        ("cmdline", "bluefin-server.raw"),
    ],
)
def test_newer_release_sets_the_flag(tmp_path: Path, server, keys, via: str, file: str) -> None:
    directory, url = server
    # 26.09.10 sorts after 26.09.2 as a version, not as a string.
    publish(directory, "26.09.10", keys["release"])
    flagged, log = check(tmp_path, url, keys["release-ring"], via=via, file=file)
    assert flagged, log
    assert f"<5>Bluefin Server 26.09.10 is available from {url}/ (running {RUNNING}); flagged" in log


@needs_tools
@pytest.mark.parametrize(
    "via,file",
    [
        ("cmdline", PINNED_RAW),
        ("cred", PINNED_RAW),
        ("stub", f"bluefin-server-netboot_{RUNNING}.efi"),
    ],
)
def test_newer_release_on_a_pinned_origin_sets_no_flag(tmp_path: Path, server, keys, via: str, file: str) -> None:
    # The directory holds both releases; the origin names the running one, so
    # a reboot would pull it again and kured would drain the node every check.
    directory, url = server
    publish(directory, "26.09.10", keys["release"], also=(RUNNING,))
    flagged, log = check(tmp_path, url, keys["release-ring"], via=via, file=file)
    assert not flagged, log
    assert (
        f"<5>Bluefin Server 26.09.10 is available from {url}/ (running {RUNNING}), "
        f"but this node is pinned to {file}; not flagging"
    ) in log


@needs_tools
@pytest.mark.parametrize("version", [RUNNING, "26.09.1", "26.08.30"])
def test_same_or_older_release_sets_no_flag(tmp_path: Path, server, keys, version: str) -> None:
    directory, url = server
    publish(directory, version, keys["release"])
    flagged, log = check(tmp_path, url, keys["release-ring"])
    assert not flagged, log
    assert f"up to date: {url}/ offers {version}, running {RUNNING}" in log


@needs_tools
def test_signature_from_another_key_sets_no_flag(tmp_path: Path, server, keys) -> None:
    directory, url = server
    publish(directory, "26.09.10", keys["stranger"])
    flagged, log = check(tmp_path, url, keys["release-ring"])
    assert not flagged, log
    assert "does not verify" in log


@needs_tools
def test_manifest_changed_after_signing_sets_no_flag(tmp_path: Path, server, keys) -> None:
    directory, url = server
    publish(directory, "26.09.10", keys["release"], tamper=True)
    flagged, log = check(tmp_path, url, keys["release-ring"])
    assert not flagged, log
    assert "does not verify" in log


@needs_tools
def test_unsigned_manifest_sets_no_flag(tmp_path: Path, server, keys) -> None:
    directory, url = server
    publish(directory, "26.09.10", keys["release"], sign=False)
    flagged, log = check(tmp_path, url, keys["release-ring"])
    assert not flagged, log
    assert "cannot fetch" in log


@needs_tools
def test_unreachable_boot_server_sets_no_flag(tmp_path: Path, keys) -> None:
    with ThreadingHTTPServer(("127.0.0.1", 0), SimpleHTTPRequestHandler) as probe:
        port = probe.server_address[1]
    flagged, log = check(tmp_path, f"http://127.0.0.1:{port}/rel", keys["release-ring"])
    assert not flagged, log
    assert "cannot fetch" in log


@needs_tools
def test_not_network_booted_is_a_no_op(tmp_path: Path, keys) -> None:
    flagged, log = check(tmp_path, None, keys["release-ring"])
    assert not flagged, log
    assert "not network booted" in log
