"""bluefin-sysext-fetch: installs the sysexts of the enabled sysupdate
features for the booted version, from the installer's seed, the boot server
or the release, and merges them. Runs bluefin-host's bluefin-sysext-fetch
against stub systemd tools."""


import os
import subprocess
from pathlib import Path

import pytest

from _systemd import SystemdFile, preset

ROOT = Path(__file__).resolve().parents[2]
UNIT = ROOT / "files" / "os" / "systemd" / "system" / "bluefin-sysext-fetch.service"
SYSUPDATE = ROOT / "files" / "os" / "sysupdate.d"
PRESETS = sorted((ROOT / "files" / "os" / "systemd" / "system-preset").glob("*.preset"))
VERSION = "26.10.3"

# The stub sysupdate installs what the transfers it was given name (or, for
# the plain release run, $RELEASE_INSTALLS) into the test's extension dir.
STUB_SYSUPDATE = r"""#!/bin/bash
echo "systemd-sysupdate $*" >> "$LOG"
defs=""
for a in "$@"; do case "$a" in --definitions=*) defs="${a#--definitions=}" ;; esac; done
if [ -n "$defs" ]; then
  for t in "$defs"/*.transfer; do
    cp "$t" "$CAPTURE/"
    m="$(sed -n '/^\[Target\]/,/^\[/s/^MatchPattern=//p' "$t")"
    [ -n "${FAIL_SYSUPDATE:-}" ] || : > "$EXT/${m//@v/$VER}"
  done
else
  for f in ${RELEASE_INSTALLS:-}; do : > "$EXT/$f"; done
fi
[ -z "${FAIL_SYSUPDATE:-}" ]
"""
STUB_LOG = '#!/bin/bash\necho "$(basename "$0") $*" >> "$LOG"\n'


def write(path: Path, text: str, mode: int = 0o644) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


class Node:
    def __init__(self, tmp: Path, host_bin: Path) -> None:
        self.tmp = tmp
        self.helper = host_bin / "bluefin-sysext-fetch"
        self.etc = tmp / "etc-sysupdate.d"
        self.usr = tmp / "usr-sysupdate.d"
        self.ext = tmp / "var-lib-extensions"
        self.ext.mkdir()
        self.esp = tmp / "esp"
        self.esp.mkdir()
        self.capture = tmp / "capture"
        self.capture.mkdir()
        self.log = tmp / "log"
        self.log.touch()
        self.rootdisk = tmp / "rootdisk.raw"
        bin_ = tmp / "bin"
        write(bin_ / "systemd-sysupdate", STUB_SYSUPDATE, 0o755)
        for tool in ("systemd-sysext", "systemctl"):
            write(bin_ / tool, STUB_LOG, 0o755)
        write(bin_ / "bootctl", '#!/bin/bash\nexit 1\n', 0o755)
        self.origin = write(tmp / "origin", f'#!/bin/bash\necho http://192.0.2.10:8765/bluefin-server_{VERSION}.raw\n', 0o755)
        self.pending = write(tmp / "pending", "#!/bin/bash\nexit 1\n", 0o755)
        for f in SYSUPDATE.iterdir():
            write(self.usr / f.name, f.read_text(encoding="utf-8").replace("Path=/var/lib/extensions", f"Path={self.ext}"))
        write(tmp / "os-release", f'ID=bluefin-server\nIMAGE_VERSION="{VERSION}"\n')
        self.env = {
            **os.environ,
            "PATH": f"{bin_}:{os.environ['PATH']}",
            "LOG": str(self.log),
            "CAPTURE": str(self.capture),
            "EXT": str(self.ext),
            "VER": VERSION,
            "BLUEFIN_SYSUPDATE_DIRS": f"{self.etc} {self.usr}",
            "BLUEFIN_OS_RELEASE": str(tmp / "os-release"),
            "BLUEFIN_ESP": str(self.esp),
            "BLUEFIN_ROOTDISK": str(self.rootdisk),
            "BLUEFIN_BOOT_ORIGIN": str(self.origin),
            "BLUEFIN_UPDATE_PENDING": str(self.pending),
            "BLUEFIN_SYSEXT_FETCH_RUN": str(tmp / "run"),
        }

    def enable(self, *features: str, value: str = "true") -> None:
        for f in features:
            write(self.etc / f"{f}.feature.d" / "50-homelab.conf", f"[Feature]\nEnabled={value}\n")

    def seed(self, *names: str) -> Path:
        seed = self.esp / "bluefin" / "extensions"
        lines = []
        for n in names:
            write(seed / n, "sysext\n")
            lines.append(f"{'0' * 64} *{n}\n")
        write(seed / "SHA256SUMS", "".join(lines))
        return seed

    def run(self, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.helper)], env={**self.env, **env}, capture_output=True, text=True, check=False
        )

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines()

    def installed(self) -> list[str]:
        return sorted(p.name for p in self.ext.iterdir())


@pytest.fixture
def node(tmp_path: Path, host_bin: Path) -> Node:
    return Node(tmp_path, host_bin)


MERGED = [
    "systemd-sysext refresh",
    "systemctl daemon-reload",
    "systemctl start --no-block bluefin-sysext-activate.service",
]


def test_nothing_enabled_fetches_nothing(node: Node) -> None:
    node.enable("kubeadm", value="false")
    result = node.run()
    assert result.returncode == 0, result.stderr
    assert node.calls() == []


def test_already_installed_is_left_alone(node: Node) -> None:
    node.enable("kubeadm", "homelab")
    (node.ext / f"kubeadm_{VERSION}.raw").touch()
    (node.ext / f"homelab_{VERSION}.raw").touch()
    result = node.run()
    assert result.returncode == 0, result.stderr
    assert node.calls() == []


def test_installer_seed_installs_offline_and_is_removed(node: Node) -> None:
    node.enable("kubeadm", "homelab")
    seed = node.seed(f"kubeadm_{VERSION}.raw.zst", f"homelab_{VERSION}.raw.zst")
    result = node.run()
    assert result.returncode == 0, result.stderr
    assert node.installed() == [f"homelab_{VERSION}.raw", f"kubeadm_{VERSION}.raw"]
    assert node.calls() == [f"systemd-sysupdate --definitions={node.tmp}/run/seed update", *MERGED]
    # scripts/dogfood-homelab-*.sh read the last line from the journal.
    assert result.stdout.splitlines() == [
        f"bluefin-sysext-fetch: fetching for {VERSION}: kubeadm_{VERSION}.raw homelab_{VERSION}.raw ",
        f"bluefin-sysext-fetch: installing from the installer's copy in {seed}/",
        f"bluefin-sysext-fetch: merged the homelab kubeadm sysext(s) for {VERSION} (seed)",
    ]
    assert not seed.exists()
    for name in ("32-kubeadm.transfer", "35-homelab.transfer"):
        transfer = SystemdFile(node.capture / name)
        assert transfer.value("Source", "Path") == f"file://{seed}/"
        assert transfer.value("Transfer", "Verify") == "no"
        assert transfer.value("Transfer", "Features") is None
        assert transfer.value("Target", "Path") == str(node.ext)


def test_seed_without_a_needed_sysext_falls_back_to_the_network(node: Node) -> None:
    node.enable("kubeadm", "homelab", "zfs")
    node.seed(f"kubeadm_{VERSION}.raw.zst", f"homelab_{VERSION}.raw.zst")
    result = node.run(RELEASE_INSTALLS=f"zfs_{VERSION}.raw")
    assert result.returncode == 0, result.stderr
    assert node.calls()[:2] == [
        f"systemd-sysupdate --definitions={node.tmp}/run/seed update",
        "systemd-sysupdate update",
    ]
    assert node.installed() == [f"homelab_{VERSION}.raw", f"kubeadm_{VERSION}.raw", f"zfs_{VERSION}.raw"]


def test_diskless_node_fetches_from_its_boot_server_with_signature_checks(node: Node) -> None:
    node.enable("homelab")
    node.rootdisk.touch()
    result = node.run()
    assert result.returncode == 0, result.stderr
    assert node.calls() == [f"systemd-sysupdate --definitions={node.tmp}/run/origin update", *MERGED]
    transfer = SystemdFile(node.capture / "35-homelab.transfer")
    assert transfer.value("Source", "Path") == "http://192.0.2.10:8765/"
    assert transfer.value("Transfer", "Verify") == "yes"
    assert sorted(p.name for p in node.capture.iterdir()) == ["35-homelab.transfer"]


def test_installed_node_repairs_the_booted_version_through_sysupdate(node: Node) -> None:
    node.enable("kubeadm", "homelab")
    result = node.run(RELEASE_INSTALLS=f"kubeadm_{VERSION}.raw homelab_{VERSION}.raw")
    assert result.returncode == 0, result.stderr
    assert node.calls() == ["systemd-sysupdate update", *MERGED]


def test_installed_node_reboots_into_a_newer_release(node: Node) -> None:
    node.enable("kubeadm")
    node.pending.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    result = node.run(RELEASE_INSTALLS="kubeadm_26.10.4.raw")
    assert result.returncode == 0, result.stderr
    assert node.calls() == ["systemd-sysupdate update", "systemctl reboot"]


def test_a_failed_fetch_fails_the_unit_so_it_retries(node: Node) -> None:
    node.enable("kubeadm")
    node.rootdisk.touch()
    result = node.run(FAIL_SYSUPDATE="1")
    assert result.returncode != 0
    assert "systemd-sysext refresh" not in node.calls()


def test_nothing_installed_and_nothing_pending_is_an_error(node: Node) -> None:
    node.enable("kubeadm")
    result = node.run()
    assert result.returncode != 0
    assert f"kubeadm_{VERSION}.raw" in result.stderr


def test_unit_runs_once_per_version_before_activation() -> None:
    unit = SystemdFile(UNIT)
    assert unit.value("Unit", "ConditionPathExists") == "!/var/lib/bluefin-sysext-fetch/%A"
    assert unit.commands("ExecStartPost") == [["/usr/bin/touch", "/var/lib/bluefin-sysext-fetch/%A"]]
    assert unit.commands() == [["/usr/libexec/bluefin-sysext-fetch"]]
    before = unit.words("Unit", "Before")
    assert {"bluefin-sysext-activate.service", "kubeadm-init.service", "k0s-first-boot.service"} <= set(before)
    assert "network-online.target" in unit.words("Unit", "After")
    assert unit.value("Service", "RemainAfterExit") == "yes"
    assert unit.value("Service", "Restart") == "on-failure"
    assert "import.pull" in unit.values("Service", "ImportCredential")


def test_unit_is_opt_in() -> None:
    assert preset("bluefin-sysext-fetch.service", PRESETS) == "disable"
