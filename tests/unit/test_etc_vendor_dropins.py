"""Vendor drop-ins ship in /usr, so A/B updates reach installed nodes.

A disk install keeps /etc across A/B updates, and the factory /etc reaches it
through tmpfiles ``C``, which never overwrites. A drop-in shipped there stays
at the version the node first booted. The sshd drop-in is linked in from
/usr instead, and the sysctl and journald ones are read from /usr/lib
directly. ``bluefin-migrate-etc-vendor`` removes the copies older images left,
but only while they are byte-identical to a version an image shipped.
"""


import hashlib
import os
import posixpath
import subprocess
from pathlib import Path

import yaml

from _systemd import SystemdFile

ROOT = Path(__file__).resolve().parents[2]
ELEMENTS = ROOT / "elements"
USR_ELEMENT = (ELEMENTS / "oci" / "bluefin-server-usr.bst").read_text(encoding="utf-8")
SSHD_ELEMENT = yaml.safe_load((ELEMENTS / "bluefin-server" / "os-sshd-config.bst").read_text(encoding="utf-8"))
DROPIN = ROOT / "files" / "os" / "sshd_config.d" / "bluefin-server.conf"
LINK_RULE = ROOT / "files" / "os" / "tmpfiles.d" / "50-bluefin-sshd.conf"
UNIT = ROOT / "files" / "os" / "systemd" / "system" / "bluefin-migrate-etc-vendor.service"
GO_SOURCE = ROOT / "files" / "homelab" / "cluster" / "internal" / "host" / "etcvendor" / "etcvendor.go"


def test_no_vendor_drop_in_is_written_to_the_factory_etc() -> None:
    assert "/sysroot/etc/sysctl.d" not in USR_ELEMENT
    assert "/sysroot/etc/systemd/journald.conf.d" not in USR_ELEMENT
    assert "> /sysroot/usr/lib/sysctl.d/10-console.conf" in USR_ELEMENT
    assert "> /sysroot/usr/lib/systemd/journald.conf.d/10-console.conf" in USR_ELEMENT
    install = "\n".join(SSHD_ELEMENT["config"]["install-commands"])
    assert '"%{install-root}/usr/lib/bluefin/sshd_config.d/"' in install
    # Only the main sshd_config, which just includes sshd_config.d, stays in /etc.
    assert '"%{install-root}/etc/ssh/sshd_config"' in install
    assert "sshd_config.d" not in install.split("/etc/ssh/sshd_config", 1)[1].split("\n", 1)[0]


def test_the_sshd_drop_in_is_linked_from_usr() -> None:
    rules = [line.split() for line in LINK_RULE.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    assert rules == [
        ["L", "/etc/ssh/sshd_config.d/bluefin-server.conf", "-", "-", "-", "-",
         "../../../usr/lib/bluefin/sshd_config.d/bluefin-server.conf"],
    ]
    target = posixpath.normpath(posixpath.join("/etc/ssh/sshd_config.d", rules[0][6]))
    assert target == "/usr/lib/bluefin/sshd_config.d/bluefin-server.conf"


def test_the_migration_runs_once_on_installed_nodes_before_tmpfiles() -> None:
    unit = SystemdFile(UNIT)
    assert unit.value("Service", "ExecStart") == "/usr/libexec/bluefin-migrate-etc-vendor"
    assert unit.value("Service", "RemainAfterExit") == "yes"
    conditions = unit.values("Unit", "ConditionPathExists")
    assert "!/var/lib/bluefin/etc-vendor-migrate.stamp" in conditions
    assert "!/run/machines/rootdisk.raw" in conditions
    assert unit.value("Unit", "ConditionKernelCommandLine") == "!root=tmpfs"
    assert "systemd-tmpfiles-setup.service" in unit.words("Unit", "Before")
    assert "local-fs.target" in unit.words("Unit", "After")
    assert "sysinit.target.wants/bluefin-migrate-etc-vendor.service" in USR_ELEMENT


def test_the_current_drop_ins_are_among_the_shipped_hashes() -> None:
    # A node that first booted this image gets links, never copies, so the
    # current content needs no hash; the sshd one is listed anyway, because
    # the image before this one shipped it as a copy.
    go = GO_SOURCE.read_text(encoding="utf-8")
    assert hashlib.sha256(DROPIN.read_bytes()).hexdigest() in go
    printk = hashlib.sha256(b"kernel.printk = 3 4 1 3\n").hexdigest()
    journald = hashlib.sha256(b"[Journal]\nForwardToConsole=no\nMaxLevelConsole=warning\n").hexdigest()
    assert printk in go and journald in go


def run(host_bin: Path, etc: Path, stamp: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, BLUEFIN_ETC=str(etc), BLUEFIN_ETC_VENDOR_STAMP=str(stamp))
    return subprocess.run([str(host_bin / "bluefin-migrate-etc-vendor")], env=env, capture_output=True, text=True, check=False)


def test_the_helper_removes_unmodified_copies_and_keeps_edits(tmp_path: Path, host_bin: Path) -> None:
    etc = tmp_path / "etc"
    sshd = etc / "ssh" / "sshd_config.d" / "bluefin-server.conf"
    sysctl = etc / "sysctl.d" / "10-console.conf"
    journald = etc / "systemd" / "journald.conf.d" / "10-console.conf"
    for path in (sshd, sysctl, journald):
        path.parent.mkdir(parents=True)
    sshd.write_bytes(DROPIN.read_bytes())
    sysctl.write_text("kernel.printk = 3 4 1 3\n", encoding="utf-8")
    journald.write_text("[Journal]\nForwardToConsole=no\nMaxLevelConsole=debug\n", encoding="utf-8")
    stamp = tmp_path / "var" / "lib" / "bluefin" / "etc-vendor-migrate.stamp"

    result = run(host_bin, etc, stamp)

    assert result.returncode == 0, result.stderr
    assert not sshd.exists()
    assert not sysctl.exists()
    assert journald.exists(), "an operator-edited copy must stay"
    assert stamp.exists()
    assert "ssh/sshd_config.d/bluefin-server.conf" in result.stdout
