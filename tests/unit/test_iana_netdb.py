"""Contracts for /etc/protocols and /etc/services in the base image (#316).

glibc's getprotobyname()/getservbyname() read them through the "files" NSS
module, and libtirpc needs "tcp"/"udp" and "sunrpc" to reach a portmapper:
without them mount.nfs fails every NFSv3 mount with "Failed to find 'tcp'
protocol". FSDK 26.08 ships both in components/iana-config.bst.

/etc holds no image content: oci/bluefin-server-usr.bst moves the staged /etc
into /usr/share/factory/etc and generates one tmpfiles.d line per entry. These
tests run that generator on a fake sysroot.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
OS_BASE = ROOT / "elements" / "bluefin-server" / "os-base.bst"
USR = ROOT / "elements" / "oci" / "bluefin-server-usr.bst"
COMPONENT = "freedesktop-sdk.bst:components/iana-config.bst"
CONF = "usr/lib/tmpfiles.d/00-bluefin-factory-etc.conf"


def factory_step() -> str:
    commands = yaml.safe_load(USR.read_text(encoding="utf-8"))["config"]["commands"]
    (step,) = [c for c in commands if "00-bluefin-factory-etc.conf" in c]
    return step


def run_factory_step(sysroot: Path) -> subprocess.CompletedProcess[str]:
    script = factory_step().replace("/sysroot", str(sysroot))
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=False)


def fake_sysroot(tmp_path: Path, etc_files: tuple[str, ...]) -> Path:
    sysroot = tmp_path / "sysroot"
    etc = sysroot / "etc"
    (etc / "iscsi").mkdir(parents=True)
    (sysroot / CONF).parent.mkdir(parents=True)
    for name in etc_files:
        (etc / name).write_text(f"{name}\n", encoding="utf-8")
    (etc / "localtime").symlink_to("../usr/share/zoneinfo/UTC")
    return sysroot


def test_iana_config_is_in_the_base_stack() -> None:
    depends = yaml.safe_load(OS_BASE.read_text(encoding="utf-8"))["depends"]
    assert COMPONENT in depends
    for sysext in (ROOT / "elements").rglob("*sysext*.bst"):
        assert "iana-config" not in sysext.read_text(encoding="utf-8"), sysext


def test_fsdk_element_installs_both_files_into_etc() -> None:
    fsdk = next((ROOT / ".bst" / "staged-junctions").glob(
        "freedesktop-sdk.bst/*/elements/components/iana-config.bst"), None)
    if fsdk is None:
        pytest.skip("freedesktop-sdk junction not staged (run just validate)")
    install = "\n".join(yaml.safe_load(fsdk.read_text(encoding="utf-8"))["config"]["install-commands"])
    assert '"%{install-root}%{sysconfdir}" protocols services' in install


def test_protocols_and_services_are_linked_like_other_read_only_defaults(tmp_path: Path) -> None:
    sysroot = fake_sysroot(tmp_path, ("netconfig", "rpc", "protocols", "services", "hosts"))
    result = run_factory_step(sysroot)
    assert result.returncode == 0, result.stderr

    factory = sysroot / "usr" / "share" / "factory" / "etc"
    for name in ("netconfig", "rpc", "protocols", "services"):
        assert (factory / name).is_file(), name
    assert not any((sysroot / "etc").iterdir())

    rules = (sysroot / CONF).read_text(encoding="utf-8").splitlines()
    # Tunable config (libtirpc's netconfig/rpc, hosts) is copied once and then
    # belongs to the node.
    for name in ("netconfig", "rpc", "hosts", "iscsi"):
        assert f"C /etc/{name} - - - - /usr/share/factory/etc/{name}" in rules
    # IANA reference data follows /usr, so an A/B update refreshes it on a
    # disk install; L never replaces a file an operator put there.
    assert "L /etc/protocols - - - - ../usr/share/factory/etc/protocols" in rules
    assert "L /etc/services - - - - ../usr/share/factory/etc/services" in rules
    assert "L /etc/localtime - - - - ../usr/share/zoneinfo/UTC" in rules
    assert not [r for r in rules if r.startswith("C ") and r.split()[1] in ("/etc/protocols", "/etc/services")]


@pytest.mark.parametrize("missing", ["protocols", "services"])
def test_image_build_fails_without_the_iana_files(tmp_path: Path, missing: str) -> None:
    present = tuple(n for n in ("netconfig", "rpc", "protocols", "services") if n != missing)
    sysroot = fake_sysroot(tmp_path, present)
    result = run_factory_step(sysroot)
    assert result.returncode != 0
    assert not (sysroot / CONF).exists()
