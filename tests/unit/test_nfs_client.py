"""Contracts for the NFS client (nfs-utils + rpcbind) shipped in the base image.

Without /sbin/mount.nfs, util-linux mount(8) passes "-t nfs" to the new
mount API and the kernel rejects it ("fsconfig() failed: NFS: mount program
didn't pass remote address"), so every kubelet NFS volume fails. The client
is built from source: FSDK 26.08 has libtirpc and keyutils but no nfs-utils
or rpcbind element.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ELEMENTS = ROOT / "elements" / "bluefin-server"
OS_BASE = ELEMENTS / "os-base.bst"
NFS_UTILS = ELEMENTS / "nfs-utils.bst"
RPCBIND = ELEMENTS / "rpcbind.bst"
PRESET = ROOT / "files" / "os" / "systemd" / "system-preset" / "80-bluefin-nfs.preset"
ALIASES = ROOT / "include" / "aliases.yml"


def element(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def configure_flags(path: Path) -> set[str]:
    script = element(path)["config"]["configure-commands"][0]
    return {token.rstrip("\\").strip() for token in script.split() if token.startswith("--")}


def preset_lines() -> list[list[str]]:
    return [line.split() for line in PRESET.read_text().splitlines() if line and not line.startswith("#")]


def test_nfs_client_is_in_the_base_stack_only() -> None:
    depends = element(OS_BASE)["depends"]
    assert "bluefin-server/nfs-utils.bst" in depends
    assert "bluefin-server/rpcbind.bst" in depends
    for sysext in (ROOT / "elements").rglob("*sysext*.bst"):
        assert "nfs-utils" not in sysext.read_text(encoding="utf-8"), sysext
    assert "bluefin-server/rpcbind.bst" in element(NFS_UTILS)["depends"]


def test_sources_are_upstream_tarballs_pinned_by_sha256() -> None:
    aliases = yaml.safe_load(ALIASES.read_text(encoding="utf-8"))["aliases"]
    assert aliases["kernel_pub"] == "https://www.kernel.org/pub/"
    for path, prefix in ((NFS_UTILS, "kernel_pub:linux/utils/nfs-utils/"), (RPCBIND, "sourceforge_download:project/rpcbind/")):
        (source,) = element(path)["sources"]
        assert source["kind"] == "tar"
        assert source["url"].startswith(prefix), source["url"]
        assert re.fullmatch(r"[0-9a-f]{64}", source["ref"]), path


def test_manual_elements_build_in_the_fsdk_autotools_sandbox() -> None:
    for path in (NFS_UTILS, RPCBIND):
        data = element(path)
        assert data["kind"] == "manual"
        assert "freedesktop-sdk.bst:public-stacks/buildsystem-autotools.bst" in data["build-depends"]
        assert "freedesktop-sdk.bst:components/libtirpc.bst" in data["depends"]


def test_nfs_utils_is_a_client_only_build() -> None:
    flags = configure_flags(NFS_UTILS)
    # No mount helper without these: /usr/sbin is a symlink to bin in FSDK,
    # and the default "sbin override" would install into a literal /sbin.
    assert "--disable-sbin-override" in flags
    assert "--enable-libmount-mount" in flags
    assert '--with-systemd="%{indep-libdir}/systemd/system"' in flags
    assert "--with-rpcgen=internal" in flags
    # Server and Kerberos pieces stay out (no krb5, libxml2, libnl in the image).
    for flag in ("--disable-gss", "--disable-svcgss", "--disable-nfsv4server", "--disable-nfsdcld",
                 "--disable-nfsdcltrack", "--disable-nfsdctl", "--disable-junction", "--disable-ldap"):
        assert flag in flags, flag
    install = "\n".join(element(NFS_UTILS)["config"]["install-commands"])
    for server_bit in ("rpc.mountd", "rpc.nfsd", "exportfs", "nfs-server.service", "system-generators"):
        assert server_bit in install, server_bit
    for kept in ("mount.nfs", "rpc.statd", "sm-notify", "nfsidmap", "nfsstat", "nfs-client.target", "rpc-statd.service"):
        assert kept in install, kept


def test_statd_state_and_user_come_from_tmpfiles_and_sysusers() -> None:
    install = "\n".join(element(NFS_UTILS)["config"]["install-commands"])
    flags = configure_flags(NFS_UTILS)
    assert '--with-statdpath="%{statd-statedir}"' in flags
    assert "--with-statduser=rpcuser" in flags
    assert 'u rpcuser 29 "RPC Service User"' in install
    assert "d %{statd-statedir}/sm 0700 rpcuser rpcuser -" in install
    assert "d %{statd-statedir}/sm.bak 0700 rpcuser rpcuser -" in install
    assert "After=systemd-tmpfiles-setup.service" in install
    # /usr is read-only and /var starts empty: nothing may ship under /var.
    assert 'rm -rf "${root}%{localstatedir}"' in install
    # NFSv4 id mapping upcall (request-key -> nfsidmap).
    assert "request-key.d/id_resolver.conf" in install


def test_rpcbind_is_socket_activated_and_unprivileged() -> None:
    flags = configure_flags(RPCBIND)
    assert "--with-rpcuser=rpc" in flags
    assert "--with-statedir=/run/rpcbind" in flags
    assert '--with-systemdsystemunitdir="%{indep-libdir}/systemd/system"' in flags
    assert 'u rpc 32 "Rpcbind Daemon" -' in "\n".join(element(RPCBIND)["config"]["install-commands"])
    lines = preset_lines()
    assert ["enable", "rpcbind.socket"] in lines
    assert ["disable", "rpcbind.service"] in lines


def test_preset_enables_the_client_target_and_nothing_else() -> None:
    lines = preset_lines()
    assert ["enable", "nfs-client.target"] in lines
    enabled = {unit for verb, unit in lines if verb == "enable"}
    assert enabled == {"nfs-client.target", "rpcbind.socket"}
