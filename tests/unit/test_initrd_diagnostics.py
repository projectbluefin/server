"""Initrd boot-failure diagnostics: units, drop-ins and the libexec helper.

files/initrd/usr/libexec/bluefin-boot-diagnostics runs in the initrd only, so
these tests drive it under bash on the host with systemctl, journalctl, stat
and sleep stubbed on $PATH, a fake /proc/meminfo, fake consoles, and a local
http.server answering the HEAD request the RAM check makes.
"""


import http.server
import os
import re
import socket
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "files" / "initrd" / "usr" / "lib" / "systemd" / "system"
IGN_UNITS = ROOT / "files" / "initrd-ignition" / "usr" / "lib" / "systemd" / "system"
HELPER = ROOT / "files" / "initrd" / "usr" / "libexec" / "bluefin-boot-diagnostics"
BOOT = ROOT / "elements" / "oci" / "bluefin-server-boot.bst"
MIB = 1024 * 1024
IMPORT_UNIT = "systemd-import@run-machines-rootdisk.raw.service"


def unit(path: Path) -> dict[str, dict[str, list[str]]]:
    """Parse a unit file keeping every value of repeated keys."""
    sections: dict[str, dict[str, list[str]]] = {}
    current = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            current = sections.setdefault(line.strip("[]"), {})
            continue
        key, _, value = line.partition("=")
        current.setdefault(key, []).append(value)
    return sections


def test_emergency_prints_the_summary_then_reboots() -> None:
    u = unit(UNITS / "emergency.service.d" / "10-reboot.conf")
    assert u["Unit"]["SuccessAction"] == ["reboot-force"]
    assert u["Unit"]["FailureAction"] == ["reboot-force"]
    # Reset the stock sulogin ExecStart, then run the summary (never fatal).
    assert u["Service"]["ExecStart"] == ["", "-/usr/libexec/bluefin-boot-diagnostics failure-summary"]
    assert u["Service"]["ImportCredential"] == ["bluefin.failure_delay"]
    assert u["Service"]["Type"] == ["idle"]


def test_every_download_is_preceded_by_the_ram_check() -> None:
    u = unit(UNITS / "systemd-import@.service.d" / "10-bluefin-pull-check.conf")
    # Only the check's own OnFailure= may stop the boot; its failure never fails the download.
    assert u["Unit"]["Wants"] == ["bluefin-pull-check@%i.service"]
    assert "Requires" not in u["Unit"]
    assert u["Unit"]["After"] == ["bluefin-pull-check@%i.service"]
    # A failed download goes straight to the summary, not a 300 s device timeout.
    assert u["Unit"]["OnFailure"] == ["emergency.target"]
    assert u["Unit"]["OnFailureJobMode"] == ["isolate"]


def test_ram_check_unit_checks_its_import_instance() -> None:
    u = unit(UNITS / "bluefin-pull-check@.service")
    assert u["Unit"]["ConditionPathExists"] == ["/etc/initrd-release"]
    assert u["Unit"]["DefaultDependencies"] == ["no"]
    assert "network-online.target" in u["Unit"]["After"]
    assert u["Unit"]["OnFailure"] == ["emergency.target"]
    assert u["Unit"]["OnFailureJobMode"] == ["isolate"]
    assert u["Service"]["ExecStart"] == [
        "/usr/libexec/bluefin-boot-diagnostics check-pull systemd-import@%i.service"
    ]


def test_ignition_karg_warning_runs_in_every_initrd() -> None:
    u = unit(UNITS / "bluefin-ignition-kargs.service")
    assert u["Unit"]["ConditionPathExists"] == ["/etc/initrd-release"]
    assert "bluefin-ignition-credentials.service" in " ".join(u["Unit"]["Before"])
    assert u["Service"]["ExecStart"] == ["/usr/libexec/bluefin-boot-diagnostics ignition-kargs"]
    boot = BOOT.read_text(encoding="utf-8")
    assert 'ln -sf ../bluefin-ignition-kargs.service "${wants}/initrd.target.wants/bluefin-ignition-kargs.service"' in boot
    assert "libexec/bluefin-boot-diagnostics" in boot, "the UKI build checks the helper is in the initrd"


@pytest.mark.parametrize("stage", ["fetch-offline", "fetch", "disks", "mount", "files"])
def test_ignition_failures_reach_the_summary(stage: str) -> None:
    u = unit(IGN_UNITS / f"ignition-{stage}.service")
    assert u["Unit"]["OnFailure"] == ["emergency.target"]


def test_helper_is_executable_bash_without_sed_or_awk() -> None:
    text = HELPER.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/bash\n")
    assert os.access(HELPER, os.X_OK)
    subprocess.run(["bash", "-n", str(HELPER)], check=True)
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"\b(sed|awk|gawk)\b", code), "the initrd has no sed or awk"


class _Handler(http.server.BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, dict[str, str]]] = {}

    def do_HEAD(self) -> None:  # noqa: N802 (http.server API)
        status, headers = self.routes.get(self.path, (404, {"Content-Length": "0"}))
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()

    def log_message(self, *args) -> None:
        pass


@pytest.fixture(scope="module")
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", _Handler.routes
    httpd.shutdown()


STUBS = {
    "systemctl": """#!/bin/bash
case "$1" in
  show) printf '%s\\n' "${FAKE_DESCRIPTION}" ;;
  list-units) for u in ${FAKE_FAILED:-}; do printf '%s loaded failed failed Fake unit\\n' "$u"; done ;;
esac
""",
    "journalctl": """#!/bin/bash
printf 'journal-line args: %s\\n' "$*"
""",
    "stat": """#!/bin/bash
printf '%s\\n' "${FAKE_STATFS}"
""",
    "sleep": """#!/bin/bash
printf '%s\\n' "$1" >> "${FAKE_SLEEP_LOG}"
""",
}


class Env:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.bin.mkdir()
        for name, body in STUBS.items():
            (self.bin / name).write_text(body, encoding="utf-8")
            (self.bin / name).chmod(0o755)
        self.dev = tmp / "dev"
        self.dev.mkdir()
        (tmp / "consoles").write_text("tty0 ttyS0\n", encoding="utf-8")
        self.net = tmp / "net"
        nic = self.net / "enp1s0"
        (nic / "device").mkdir(parents=True)
        (nic / "operstate").write_text("down\n", encoding="utf-8")
        (nic / "carrier").write_text("0\n", encoding="utf-8")
        (self.net / "lo").mkdir()  # virtual: no device link, not listed
        self.cmdline("root=tmpfs")
        self.meminfo(total_kib=4_000_000, avail_kib=3_600_000)
        self.statfs(free_mib=800, size_mib=800)
        self.creds = tmp / "creds"
        self.creds.mkdir()
        self.env = dict(
            os.environ,
            PATH=f"{self.bin}:{os.environ['PATH']}",
            BLUEFIN_DIAG_MEMINFO=str(tmp / "meminfo"),
            BLUEFIN_DIAG_CMDLINE=str(tmp / "cmdline"),
            BLUEFIN_DIAG_CONSOLES=str(tmp / "consoles"),
            BLUEFIN_DIAG_DEVDIR=str(self.dev),
            BLUEFIN_DIAG_NETDIR=str(self.net),
            CREDENTIALS_DIRECTORY=str(self.creds),
            FAKE_SLEEP_LOG=str(tmp / "sleep.log"),
            FAKE_DESCRIPTION="",
            FAKE_FAILED="",
        )

    def cmdline(self, text: str) -> None:
        (self.tmp / "cmdline").write_text(text + "\n", encoding="utf-8")

    def meminfo(self, total_kib: int, avail_kib: int) -> None:
        self.total_kib = total_kib
        self.avail_kib = avail_kib
        (self.tmp / "meminfo").write_text(
            f"MemTotal:       {total_kib} kB\nMemFree:        {avail_kib} kB\n"
            f"MemAvailable:   {avail_kib} kB\nBuffers:        0 kB\n",
            encoding="utf-8",
        )

    def statfs(self, free_mib: int, size_mib: int) -> None:
        self.run_free = free_mib * MIB
        self.run_size = size_mib * MIB
        self.fake_statfs = f"{free_mib * 256} 4096 {size_mib * 256}"

    def run(self, *args: str, **extra: str) -> subprocess.CompletedProcess:
        env = dict(self.env, FAKE_STATFS=self.fake_statfs, **extra)
        return subprocess.run(
            ["bash", str(HELPER), *args], capture_output=True, text=True, env=env, timeout=60
        )

    def console(self, name: str = "ttyS0") -> str:
        path = self.dev / name
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def sleeps(self) -> list[str]:
        log = self.tmp / "sleep.log"
        return log.read_text(encoding="utf-8").split() if log.exists() else []


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def check_pull(env: Env, url: str, **extra: str) -> subprocess.CompletedProcess:
    return env.run("check-pull", IMPORT_UNIT, FAKE_DESCRIPTION=f"Download of {url}", **extra)


def cannot_check(reason: str) -> str:
    return f"BLUEFIN: cannot check that the OS image fits in RAM ({reason}); downloading it anyway"


def assert_download_goes_ahead(env: Env, result: subprocess.CompletedProcess, reason: str) -> None:
    note = cannot_check(reason)
    assert result.returncode == 0, result.stderr
    for tty in ("tty0", "ttyS0"):
        assert env.console(tty) == f"{note}\n"
    assert f"<4>bluefin-boot-diagnostics: {note}\n" in result.stderr


def test_image_that_fits_passes_quietly(env: Env, server) -> None:
    base, routes = server
    routes["/fits.raw"] = (200, {"Content-Length": str(540 * MIB)})
    result = check_pull(env, f"{base}/fits.raw")
    assert result.returncode == 0, result.stderr
    assert "540 MiB fits" in result.stderr
    assert env.console() == ""


def _expected_mib(env: Env, size: int) -> int:
    """Mirror of the helper's estimate, rounded up to 64 MiB."""
    need = size + 64 * MIB
    used_kib = (env.run_size - env.run_free) // 1024
    want_run = (used_kib + need // 1024) * env.total_kib // (env.run_size // 1024) * 1024
    want_mem = env.total_kib * 1024 - env.avail_kib * 1024 + need
    want = max(want_run, want_mem)
    return -(-want // (64 * MIB)) * 64


def test_image_larger_than_run_fails_with_the_ram_it_needs(env: Env, server) -> None:
    base, routes = server
    size = 540 * MIB
    routes["/bluefin-server_1.raw"] = (200, {"Content-Length": str(size)})
    # 2 GB machine: /run is 20% of it.
    env.meminfo(total_kib=2_000_000, avail_kib=1_800_000)
    env.statfs(free_mib=380, size_mib=390)
    result = check_pull(env, f"{base}/bluefin-server_1.raw")
    assert result.returncode == 1
    want = _expected_mib(env, size)
    assert 2900 < want < 3200
    for tty in ("tty0", "ttyS0"):
        text = env.console(tty)
        assert "NOT ENOUGH RAM FOR A DISKLESS BOOT" in text
        assert f"needs ~{want} MiB RAM, have 1954 MiB" in text
        assert "bluefin-server_1.raw (540 MiB)" in text
        assert "capped at 19% of RAM: 380 MiB free" in text
    assert f"<2>bluefin-boot-diagnostics: This machine needs ~{want} MiB RAM" in result.stderr


def test_low_memavailable_fails_even_when_run_has_room(env: Env, server) -> None:
    base, routes = server
    size = 300 * MIB
    routes["/small.raw"] = (200, {"Content-Length": str(size)})
    env.meminfo(total_kib=4_000_000, avail_kib=200_000)
    env.statfs(free_mib=780, size_mib=800)
    result = check_pull(env, f"{base}/small.raw")
    assert result.returncode == 1
    assert f"needs ~{_expected_mib(env, size)} MiB RAM, have 3907 MiB" in env.console()


def test_redirects_are_followed_to_the_final_size(env: Env, server) -> None:
    base, routes = server
    routes["/redirect.raw"] = (302, {"Location": "/huge.raw", "Content-Length": "0"})
    routes["/huge.raw"] = (200, {"Content-Length": str(4000 * MIB)})
    result = check_pull(env, f"{base}/redirect.raw")
    assert result.returncode == 1
    assert "redirect.raw (4000 MiB)" in env.console()


@pytest.mark.slow
@pytest.mark.parametrize("status", [403, 404, 405, 500, 501])
def test_head_errors_do_not_block_the_download(env: Env, server, status: int) -> None:
    # A signed object-store URL covers the method: GET works, HEAD gets 403.
    base, routes = server
    routes[f"/head{status}.raw"] = (status, {"Content-Length": "0"})
    result = check_pull(env, f"{base}/head{status}.raw")
    assert_download_goes_ahead(env, result, f"HEAD answered HTTP {status}")


def test_missing_content_length_skips_the_check(env: Env, server) -> None:
    base, routes = server
    routes["/chunked.raw"] = (200, {"Transfer-Encoding": "chunked"})
    result = check_pull(env, f"{base}/chunked.raw")
    assert_download_goes_ahead(env, result, "HEAD answered HTTP 200 with no Content-Length")


def test_unreachable_server_does_not_block_the_download(env: Env) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    result = check_pull(env, f"http://127.0.0.1:{port}/img.raw")
    assert result.returncode == 0, result.stderr
    text = env.console()
    assert text.startswith("BLUEFIN: cannot check that the OS image fits in RAM (HEAD failed: curl: (7) ")
    assert text.endswith("); downloading it anyway\n")
    assert text.count("\n") == 1
    assert env.console("tty0") == text
    assert f"<4>bluefin-boot-diagnostics: {text}" in result.stderr


def test_a_broken_check_does_not_block_the_download(env: Env, server) -> None:
    base, routes = server
    routes["/broken.raw"] = (200, {"Content-Length": str(540 * MIB)})
    # A value the check does not expect makes bash abort it (unbound variable).
    (env.tmp / "meminfo").write_text("MemTotal: 4000000 kB\nMemAvailable: n/a kB\n", encoding="utf-8")
    result = check_pull(env, f"{base}/broken.raw")
    assert "unbound variable" in result.stderr
    assert result.returncode == 0
    assert env.console() == ""


def test_non_http_sources_are_not_checked(env: Env) -> None:
    result = env.run("check-pull", IMPORT_UNIT, FAKE_DESCRIPTION="Download of file:///run/img.raw")
    assert result.returncode == 0
    assert env.console() == ""


def test_ignition_kargs_are_named_without_their_values(env: Env) -> None:
    env.cmdline("root=tmpfs ignition.config.url=http://10.0.0.1/secret-token.ign ignition.platform.id=metal quiet")
    result = env.run("ignition-kargs")
    assert result.returncode == 0
    text = env.console("tty0")
    assert "IGNORED KERNEL ARGUMENTS: ignition.config.url ignition.platform.id" in text
    assert "ignition.config or ignition.config.url system credential" in text
    assert "secret-token" not in text + result.stderr
    assert "<4>bluefin-boot-diagnostics: BLUEFIN: IGNORED KERNEL ARGUMENTS" in result.stderr


def test_no_ignition_kargs_no_warning(env: Env) -> None:
    env.cmdline("root=tmpfs rd.systemd.pull=raw,machine:rootdisk:http://x/y.raw")
    result = env.run("ignition-kargs")
    assert result.returncode == 0
    assert result.stderr == ""
    assert env.console() == ""


def test_failure_summary_explains_each_failed_unit(env: Env) -> None:
    result = env.run(
        "failure-summary",
        FAKE_FAILED=f"ignition-disks.service {IMPORT_UNIT} systemd-networkd-wait-online.service",
    )
    assert result.returncode == 0
    text = env.console("tty0")
    assert text == env.console("ttyS0")
    assert "BLUEFIN: BOOT FAILED" in text
    assert "FAILED: ignition-disks.service" in text
    assert "Ignition stage 'disks' failed" in text
    assert "must be idempotent" in text
    assert f"FAILED: {IMPORT_UNIT}" in text
    assert "SHA256SUMS signed by a key this image trusts" in text
    assert "no network link became routable within 300 s" in text
    assert "enp1s0 down (no carrier)" in text
    assert (
        f"| journal-line args: -b _SYSTEMD_UNIT={IMPORT_UNIT} _SYSTEMD_UNIT=systemd-importd.service -n 6 -o cat --no-pager"
        in text
    ), "a failed download shows systemd-importd's reason"
    assert "| journal-line args: -b _SYSTEMD_UNIT=ignition-disks.service -n 6" in text
    assert "Last errors (journalctl -b -p err):" in text
    assert "docs/skills/diskless-troubleshooting.md\n" in text
    assert "Rebooting in 60 s" in text
    assert env.sleeps() == ["60"]


def test_failure_summary_blames_ram_for_a_failed_check(env: Env) -> None:
    env.run("failure-summary", FAKE_FAILED="bluefin-pull-check@run-machines-rootdisk.raw.service")
    text = env.console()
    assert "-> the OS image is too big for the RAM of this machine" in text
    assert "network links:" not in text


def test_failure_summary_without_failed_units_points_at_timeouts(env: Env) -> None:
    env.cmdline("root=tmpfs ignition.config.url=http://x/y.ign")
    env.run("failure-summary")
    text = env.console()
    assert "No unit failed: a device or job timed out" in text
    assert "Ignored kernel arguments: ignition.config.url" in text


@pytest.mark.parametrize(
    "credential,karg,expected",
    [
        (None, None, "60"),
        ("120\n", None, "120"),
        ("3", None, "10"),  # floor: no hot reboot loop
        ("0600", None, "600"),  # decimal, not octal
        ("999999999", None, "60"),  # not a sane number
        ("soon", None, "60"),
        ("120", "30", "30"),  # the kernel argument wins where it can be set
        (None, "100000", "86400"),
    ],
)
def test_failure_delay(env: Env, credential: str | None, karg: str | None, expected: str) -> None:
    if credential is not None:
        (env.creds / "bluefin.failure_delay").write_text(credential, encoding="utf-8")
    if karg is not None:
        env.cmdline(f"root=tmpfs bluefin.failure_delay={karg}")
    env.run("failure-summary")
    assert env.sleeps() == [expected]
    assert f"Rebooting in {expected} s" in env.console()


def test_unknown_mode_is_a_usage_error(env: Env) -> None:
    result = env.run("bogus")
    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_console_links_point_at_existing_doc_sections() -> None:
    text = HELPER.read_text(encoding="utf-8")
    base = re.search(r"^DOCS=https://github\.com/projectbluefin/server/blob/main/(\S+)$", text, re.M)
    assert base, "DOCS must link the repository's main branch"
    doc = (ROOT / base.group(1)).read_text(encoding="utf-8")
    slugs = {
        re.sub(r"[^a-z0-9 -]", "", line.lstrip("#").strip().lower()).replace(" ", "-")
        for line in doc.splitlines()
        if line.startswith("## ")
    }
    anchors = set(re.findall(r"\$\{DOCS\}#([a-z0-9-]+)", text))
    assert anchors == {"minimum-ram", "ignition"}
    assert anchors <= slugs
