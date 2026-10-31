"""The USB installer's preserved Homelab profiles and independent arguments.
Advanced minimal still has no profile-specific provisioning; Home Server
uses a separate argument variable and does not change the Homelab helpers."""


import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from _systemd import SystemdFile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "files" / "os" / "libexec" / "bluefin-homelab-install"
UNIT = ROOT / "files" / "os" / "creds" / "systemd" / "system" / "bluefin-homelab-install.service"
DROPIN = ROOT / "files" / "os" / "systemd" / "system" / "systemd-sysinstall.service.d" / "10-bluefin-installer.conf"
BOOT = ROOT / "elements" / "oci" / "bluefin-server-boot.bst"
CREDS_ELEMENT = ROOT / "elements" / "bluefin-server" / "os-creds-prov.bst"
REPART = ROOT / "files" / "os" / "repart.d"
STICK = "/run/bluefin/installer/bluefin/homelab"
ENV_FILE = "/run/bluefin-homelab-install/sysinstall.env"


class Installer:
    def __init__(self, tmp: Path) -> None:
        self.creds = tmp / "creds"
        self.creds.mkdir()
        self.out = tmp / "run"
        self.out.mkdir()
        self.stick = tmp / "stick"
        (self.stick / "repart.d" / "10-esp.conf.d").mkdir(parents=True)
        for role in ("control-plane", "node"):
            (self.stick / f"homelab-{role}.bu").write_text("variant: fcos\n", encoding="utf-8")

    def run(self, role: str, stdin: str = "", **creds: str) -> subprocess.CompletedProcess[str]:
        (self.creds / "bluefin.install-homelab").write_text(role, encoding="utf-8")
        for name, value in creds.items():
            (self.creds / name.replace("_", "-").replace("--", ".")).write_text(value, encoding="utf-8")
        env = {
            **os.environ,
            "CREDENTIALS_DIRECTORY": str(self.creds),
            "RUNTIME_DIRECTORY": str(self.out),
            "BLUEFIN_INSTALLER_HOMELAB": str(self.stick),
        }
        return subprocess.run(["bash", str(SCRIPT)], env=env, input=stdin, capture_output=True, text=True, check=False)

    def args(self) -> list[str]:
        text = (self.out / "sysinstall.env").read_text(encoding="utf-8")
        assert text.startswith("BLUEFIN_INSTALL_ARGS=") and text.count("\n") == 1
        return text.removeprefix("BLUEFIN_INSTALL_ARGS=").split()


@pytest.fixture
def installer(tmp_path: Path) -> Installer:
    return Installer(tmp_path)


def test_control_plane_install_adds_the_seed_and_the_template(installer: Installer) -> None:
    result = installer.run("control-plane")
    assert result.returncode == 0, result.stderr
    assert installer.args() == [
        f"--definitions={installer.stick}/repart.d",
        f"--load-credential=ignition.config:{installer.stick}/homelab-control-plane.bu",
    ]
    assert not (installer.out / "passphrase").exists()


def test_node_install_takes_the_passphrase_credential_without_asking(installer: Installer) -> None:
    result = installer.run("node", **{"bluefin-cluster--passphrase": "orbit maple candle river"})
    assert result.returncode == 0, result.stderr
    passphrase = installer.out / "passphrase"
    assert installer.args() == [
        f"--definitions={installer.stick}/repart.d",
        f"--load-credential=ignition.config:{installer.stick}/homelab-node.bu",
        f"--load-credential=bluefin-cluster.passphrase:{passphrase}",
    ]
    assert passphrase.read_text(encoding="utf-8") == "orbit maple candle river"
    assert stat.S_IMODE(passphrase.stat().st_mode) == 0o600
    assert "Join passphrase:" not in result.stdout
    assert "orbit" not in result.stdout + result.stderr


def test_node_install_asks_for_the_passphrase_on_the_console(installer: Installer) -> None:
    result = installer.run("node", stdin="orbit-maple-candle-river\n")
    assert result.returncode == 0, result.stderr
    assert "Join passphrase:" in result.stdout
    assert (installer.out / "passphrase").read_text(encoding="utf-8") == "orbit-maple-candle-river"
    assert installer.args()[-1] == f"--load-credential=bluefin-cluster.passphrase:{installer.out}/passphrase"


def test_an_empty_answer_leaves_the_passphrase_to_the_template(installer: Installer) -> None:
    result = installer.run("node", stdin="\n")
    assert result.returncode == 0, result.stderr
    assert not (installer.out / "passphrase").exists()
    assert not [a for a in installer.args() if "passphrase" in a]


def test_an_unknown_role_or_a_stick_without_templates_fails(installer: Installer) -> None:
    assert installer.run("worker").returncode != 0
    (installer.stick / "homelab-node.bu").unlink()
    assert installer.run("node", stdin="\n").returncode != 0


def test_unit_runs_only_from_a_homelab_entry_before_sysinstall() -> None:
    unit = SystemdFile(UNIT)
    assert unit.value("Unit", "ConditionCredential") == "bluefin.install-homelab"
    assert "systemd-sysinstall.service" in unit.words("Unit", "Before")
    assert unit.value("Service", "RemainAfterExit") == "yes"
    assert unit.value("Service", "RuntimeDirectory") == "bluefin-homelab-install"
    assert set(unit.values("Service", "ImportCredential")) == {"bluefin.install-homelab", "bluefin-cluster.passphrase"}
    assert "install -Dm0755 libexec-src/bluefin-homelab-install" in CREDS_ELEMENT.read_text(encoding="utf-8")
    assert SCRIPT.stat().st_mode & stat.S_IXUSR


def test_sysinstall_appends_independent_profile_arguments_before_the_target() -> None:
    dropin = SystemdFile(DROPIN)
    exec_start = dropin.values("Service", "ExecStart")[-1]
    assert exec_start.split()[-3:] == [
        "$BLUEFIN_INSTALL_ARGS", "$BLUEFIN_HOME_SERVER_INSTALL_ARGS", "$BLUEFIN_INSTALL_TARGET"
    ]
    # Empty profile variables add no argv; advanced minimal keeps its root
    # first-boot credential. Home's template alone masks that root prompt.
    [argv] = dropin.commands()
    assert argv[-1] == "--set-credential=bluefin.prompt-root-password:1"
    assert "BLUEFIN_INSTALL_ARGS=" in dropin.words("Service", "Environment")
    assert f"-{ENV_FILE}" in dropin.values("Service", "EnvironmentFile")
    assert "bluefin-homelab-install.service" in dropin.words("Unit", "Wants")
    assert "bluefin-homelab-install.service" in dropin.words("Unit", "After")
    assert "RuntimeDirectory=bluefin-homelab-install" in UNIT.read_text(encoding="utf-8")
    assert ENV_FILE.endswith("/sysinstall.env")


def boot_variable(name: str) -> str:
    return " ".join(yaml.safe_load(BOOT.read_text(encoding="utf-8"))["variables"][name].split())




def test_all_three_installer_profiles_mask_userspace_wait_online() -> None:
    text = BOOT.read_text(encoding="utf-8")
    installer_words = boot_variable("installer-cmdline").split()
    assert "rd.systemd.mask=systemd-networkd-wait-online.service" in installer_words
    assert "systemd.mask=systemd-networkd-wait-online.service" in installer_words
    # Homelab profiles derive directly from %{installer-cmdline}
    assert re.search(
        r'printf \'usrhash=%s %s %s systemd\.set_credential=bluefin\.install-homelab:%s\' \\\n'
        r'\s+"\$\{usrhash\}" "%\{installer-cmdline\}" "%\{common-cmdline\}" "\$\{role\}"',
        text,
    )
    # Netboot and disk UKIs do not have userspace wait-online masked
    netboot_words = boot_variable("netboot-cmdline").split()
    disk_words = boot_variable("disk-cmdline").split()
    assert "systemd.mask=systemd-networkd-wait-online.service" not in netboot_words
    assert "systemd.mask=systemd-networkd-wait-online.service" not in disk_words

