"""Executed coverage for the bluefin-sysinstall inst.creds_url archive handling.

The wrapper is carved out of the installer element's heredoc and run under bash
with a stand-in curl, so the fetch/verify/validate/unpack block is exercised
against real tar archives without a network or a BuildStream build.

Not executed here: the stand-in curl copies the "URL" path and ignores
--max-filesize, so the curl-side 16 MiB cap is only pinned as a string by
test_installer_contract.py (the stat re-check after the checksum *is*
executed), and finalize_target_esp (ESP lookup by GPT type, mount, copy,
fail-closed) needs a block device and is covered by string assertions only.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER_ELEMENT = REPO_ROOT / "elements" / "oci" / "bluefin-server-installer.bst"

def _gnu_tar_available() -> bool:
    if shutil.which("bash") is None or shutil.which("tar") is None:
        return False
    version = subprocess.run(["tar", "--version"], capture_output=True, text=True)
    return "GNU tar" in version.stdout


pytestmark = pytest.mark.skipif(
    not _gnu_tar_available(),
    reason="bash and GNU tar (the initrd's tar, whose -tv listing format the wrapper parses) are required",
)


def _creds_block(script: str) -> str:
    lines = script.splitlines()
    anchor = next(i for i, line in enumerate(lines) if "Fetching first-boot credentials" in line)
    start = next(i for i in range(anchor, -1, -1) if lines[i] == 'if [ -n "${CREDS_URL}" ]; then')
    end = next(i for i in range(anchor, len(lines)) if lines[i] == "fi")
    return "\n".join(lines[start : end + 1]) + "\n"


def _write_tar(path: Path, members: dict[str, bytes | None], *, symlink: str | None = None) -> str:
    with tarfile.open(path, "w") as tar:
        for name, payload in members.items():
            if payload is None:
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            else:
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                tar.addfile(info, fileobj=io.BytesIO(payload))
        if symlink:
            info = tarfile.TarInfo(symlink)
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
    return hashlib.sha256(path.read_bytes()).hexdigest()



def _write_tar_members(path: Path, members: list[tuple[tarfile.TarInfo, bytes | None]]) -> str:
    with tarfile.open(path, "w") as tar:
        for info, payload in members:
            if payload is None:
                tar.addfile(info)
            else:
                info.size = len(payload)
                tar.addfile(info, fileobj=io.BytesIO(payload))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _regular(name: str, payload: bytes = b"x", **attrs: object) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    for key, value in attrs.items():
        setattr(info, key, value)
    return info, payload


def _special(name: str, tar_type: bytes, **attrs: object) -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type = tar_type
    for key, value in attrs.items():
        setattr(info, key, value)
    return info, None


def _run_creds_block(tmp_path: Path, archive: Path, sha256: str, wrapper: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    run_dir = tmp_path / "run-installer"
    run_dir.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "curl").write_text(
        "#!/bin/bash\n"
        "out=''\n"
        'while [ $# -gt 1 ]; do [ "$1" = --output ] && out="$2"; shift; done\n'
        'cp -- "$1" "$out"\n',
        encoding="utf-8",
    )
    os.chmod(fake_bin / "curl", 0o755)

    block = _creds_block(wrapper).replace("/dev/shm/installer", str(run_dir))
    script = (
        "set -euo pipefail\n"
        f'CREDS_URL="{archive}"\nCREDS_SHA256="{sha256}"\nCREDS_DIR=""\nCREDS_NAMES=()\n'
        f"{block}"
        'echo "CREDS_DIR=${CREDS_DIR}"\n'
        'printf \'CREDS_NAME=%s\\n\' "${CREDS_NAMES[@]}"\n'
    )
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}
    return (
        subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env),
        run_dir,
    )


def test_wrapper_script_parses_under_bash(installer_wrapper: str) -> None:
    result = subprocess.run(["bash", "-n", "-c", installer_wrapper], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_wrapper_script_is_shellcheck_clean_at_warning_level(installer_wrapper: str) -> None:
    result = subprocess.run(
        ["shellcheck", "--shell=bash", "-S", "warning", "-"],
        input=installer_wrapper,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout


def test_flat_cred_archive_is_verified_and_unpacked_into_tmpfs(tmp_path: Path, installer_wrapper: str) -> None:
    archive = tmp_path / "creds.tar"
    sha256 = _write_tar_members(
        archive,
        [
            _regular("firstboot.hostname.cred", b"node-01\n", mode=0o600, uname="root", gname="root"),
            _regular("tmpfiles.extra.cred", b"d /var/home/core 0700 core core -\n", mode=0o4777, uid=1000),
        ],
    )

    result, run_dir = _run_creds_block(tmp_path, archive, sha256, installer_wrapper)

    assert result.returncode == 0, result.stderr
    assert f"CREDS_DIR={run_dir}/credentials" in result.stdout
    assert result.stdout.count("CREDS_NAME=") == 2
    assert "CREDS_NAME=firstboot.hostname.cred" in result.stdout
    assert "CREDS_NAME=tmpfiles.extra.cred" in result.stdout
    extracted = sorted((run_dir / "credentials").iterdir())
    assert [p.name for p in extracted] == ["firstboot.hostname.cred", "tmpfiles.extra.cred"]
    # Archive modes (0600, setuid 4777) and ownership are not honoured: our own
    # copies are pinned to 0644.
    assert [oct(p.stat().st_mode & 0o7777) for p in extracted] == ["0o644", "0o644"]
    assert (run_dir / "credentials" / "firstboot.hostname.cred").read_bytes() == b"node-01\n"
    assert not (run_dir / "credentials.tar").exists()


def test_caps_are_inclusive_at_64_members_and_1_mib_each(tmp_path: Path, installer_wrapper: str) -> None:
    archive = tmp_path / "creds.tar"
    members = [_regular(f"cred-{index:02d}.cred") for index in range(63)]
    members.append(_regular("big.cred", b"\0" * 1048576))
    sha256 = _write_tar_members(archive, members)

    result, run_dir = _run_creds_block(tmp_path, archive, sha256, installer_wrapper)

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("CREDS_NAME=") == 64
    assert len(list((run_dir / "credentials").iterdir())) == 64


def test_checksum_mismatch_fails_closed_before_unpacking(tmp_path: Path, installer_wrapper: str) -> None:
    archive = tmp_path / "creds.tar"
    _write_tar(archive, {"firstboot.hostname.cred": b"node-01\n"})

    result, run_dir = _run_creds_block(tmp_path, archive, "0" * 64, installer_wrapper)

    assert result.returncode == 1
    assert "downloaded credentials SHA256 verification failed" in result.stderr
    assert not (run_dir / "credentials").exists()


@pytest.mark.parametrize(
    ("members", "symlink", "rejected"),
    [
        ({"firstboot.hostname.cred": b"x", "README.txt": b"y"}, None, "README.txt"),
        ({"sub/": None, "sub/nested.cred": b"x"}, None, "sub/"),
        ({"./": None, "./firstboot.hostname.cred": b"x"}, None, "./"),
        ({"firstboot.hostname.cred": b"x"}, "link.cred", "link.cred"),
        ({".cred": b"x"}, None, ".cred"),
    ],
)
def test_non_flat_or_non_cred_members_reject_the_whole_archive(
    tmp_path: Path, installer_wrapper: str, members: dict[str, bytes | None], symlink: str | None, rejected: str
) -> None:
    archive = tmp_path / "creds.tar"
    sha256 = _write_tar(archive, members, symlink=symlink)

    result, run_dir = _run_creds_block(tmp_path, archive, sha256, installer_wrapper)

    assert result.returncode == 1
    assert f"credentials archive member '{rejected}" in result.stderr
    assert "refusing the archive" in result.stderr
    assert not (run_dir / "credentials").exists()


def test_garbage_or_empty_download_is_rejected(tmp_path: Path, installer_wrapper: str) -> None:
    # Neither carries the ustar magic at offset 257, so both stop at the
    # format check before tar is even asked to read them.
    for payload in (b"", b"not a tar archive\n", b"\0" * 512 + b"garbage" * 100):
        blob = tmp_path / "creds.tar"
        blob.write_bytes(payload)
        sha256 = hashlib.sha256(payload).hexdigest()

        result, run_dir = _run_creds_block(tmp_path, blob, sha256, installer_wrapper)

        assert result.returncode == 1
        assert "not an uncompressed ustar/pax tar archive" in result.stderr
        assert not (run_dir / "credentials").exists()
        shutil.rmtree(run_dir)
        shutil.rmtree(tmp_path / "bin")


@pytest.mark.skipif(shutil.which("zstd") is None, reason="zstd not installed")
def test_compressed_archive_is_rejected_without_being_decompressed(tmp_path: Path, installer_wrapper: str) -> None:
    # GNU tar would transparently decompress a .tar.zst named on -f, letting a
    # 16 MiB download expand into an unbounded listing held in bash variables.
    # The wrapper checks the ustar magic and feeds tar on stdin, where it
    # refuses compressed input; a valid archive that is merely compressed must
    # be rejected before any member is listed.
    plain = tmp_path / "plain.tar"
    _write_tar(plain, {"firstboot.hostname.cred": b"node-01\n"})
    compressed = tmp_path / "creds.tar"
    subprocess.run(["zstd", "-q", "-f", str(plain), "-o", str(compressed)], check=True)
    sha256 = hashlib.sha256(compressed.read_bytes()).hexdigest()

    result, run_dir = _run_creds_block(tmp_path, compressed, sha256, installer_wrapper)

    assert result.returncode == 1, result.stdout
    assert "not an uncompressed ustar/pax tar archive" in result.stderr
    assert "CREDS_NAME=" not in result.stdout
    assert not (run_dir / "credentials").exists()

    # Belt and braces: even with the magic check bypassed, tar on stdin refuses
    # to decompress (GNU tar only auto-detects compression for a named file).
    listing = subprocess.run(
        ["bash", "-c", f"LC_ALL=C tar -tvf - < {compressed}"], capture_output=True, text=True
    )
    assert listing.returncode != 0
    assert "compressed" in listing.stderr


def test_tilde_names_from_systemd_dropin_namespace_are_accepted(tmp_path: Path, installer_wrapper: str) -> None:
    # systemd.unit-dropin.<unit>~<name> is systemd's own credential namespace
    # (systemd.system-credentials(7)); ~ is a legal vfat long-filename byte.
    archive = tmp_path / "creds.tar"
    name = "systemd.unit-dropin.multi-user.target~booty.cred"
    sha256 = _write_tar(archive, {name: b"[Unit]\n", "firstboot.hostname.cred": b"node-01\n"})

    result, run_dir = _run_creds_block(tmp_path, archive, sha256, installer_wrapper)

    assert result.returncode == 0, result.stderr
    assert f"CREDS_NAME={name}" in result.stdout
    assert (run_dir / "credentials" / name).read_bytes() == b"[Unit]\n"


def test_member_name_length_is_capped_at_250_bytes(tmp_path: Path, installer_wrapper: str) -> None:
    # A 250-byte name passes; 251 is rejected by the wrapper, with its own
    # message, before tar (ENAMETOOLONG at 256) or vfat (255) would fail it.
    ok_name = "n" * (250 - len(".cred")) + ".cred"
    long_name = "n" * (251 - len(".cred")) + ".cred"
    assert len(ok_name) == 250 and len(long_name) == 251

    archive = tmp_path / "ok.tar"
    sha256 = _write_tar(archive, {ok_name: b"x"})
    (tmp_path / "ok").mkdir()
    ok, _ = _run_creds_block(tmp_path / "ok", archive, sha256, installer_wrapper)
    assert ok.returncode == 0, ok.stderr
    assert f"CREDS_NAME={ok_name}" in ok.stdout

    archive = tmp_path / "long.tar"
    sha256 = _write_tar(archive, {long_name: b"x"})
    (tmp_path / "long").mkdir()
    rejected, run_dir = _run_creds_block(tmp_path / "long", archive, sha256, installer_wrapper)
    assert rejected.returncode == 1, rejected.stdout
    assert f"member '{long_name}' has a 251-byte name, above the 250-byte limit" in rejected.stderr
    assert not (run_dir / "credentials").exists()


@pytest.mark.parametrize(
    ("names", "rejected"),
    [
        pytest.param(["a.cred", "a.cred"], "member 'a.cred' repeats 'a.cred'", id="duplicate"),
        pytest.param(["Host.cred", "host.cred"], "member 'host.cred' repeats 'Host.cred'", id="case-collision-on-vfat"),
    ],
)
def test_repeated_or_case_colliding_names_reject_the_whole_archive(
    tmp_path: Path, installer_wrapper: str, names: list[str], rejected: str
) -> None:
    # tar -x with a repeated name fails half-way through with tar's own error;
    # two names that differ only by case both extract in tmpfs and then
    # silently overwrite each other on the vfat ESP. Both are refused up front.
    archive = tmp_path / "creds.tar"
    sha256 = _write_tar_members(archive, [_regular(name, name.encode()) for name in names])

    result, run_dir = _run_creds_block(tmp_path, archive, sha256, installer_wrapper)

    assert result.returncode == 1, result.stdout
    assert rejected in result.stderr
    assert "refusing the archive" in result.stderr
    assert not (run_dir / "credentials").exists()


@pytest.mark.parametrize(
    ("members", "rejected"),
    [
        pytest.param(
            [_regular("firstboot.hostname.cred"), _special("copy.cred", tarfile.LNKTYPE, linkname="firstboot.hostname.cred")],
            "member 'copy.cred",
            id="hardlink",
        ),
        pytest.param([_special("tty.cred", tarfile.CHRTYPE, devmajor=5, devminor=0)], "member 'tty.cred", id="char-device"),
        pytest.param([_special("sda.cred", tarfile.BLKTYPE, devmajor=8, devminor=0)], "member 'sda.cred", id="block-device"),
        pytest.param([_special("pipe.cred", tarfile.FIFOTYPE)], "member 'pipe.cred", id="fifo"),
        pytest.param([_regular("host name.cred")], "member 'host name.cred", id="space-in-name"),
        pytest.param([_regular("host\nname.cred")], "member 'host\\nname.cred", id="newline-in-name"),
        pytest.param([_regular("-rf.cred")], "member '-rf.cred", id="leading-dash"),
        pytest.param([_regular("..cred")], "member '..cred", id="leading-dot"),
        pytest.param([_regular("host:name.cred")], "member 'host:name.cred", id="colon-in-name"),
        pytest.param([_regular("ok.cred", uname="a b", gname="c")], "is not a top-level regular *.cred file", id="space-in-owner-shifts-columns"),
        pytest.param([_regular("big.cred", b"\0" * (1048576 + 1))], "member 'big.cred' is 1048577 bytes, above the 1 MiB limit", id="member-over-1-mib"),
        pytest.param([_regular(f"cred-{index:02d}.cred") for index in range(65)], "more than 64 members", id="65-members"),
    ],
)
def test_unsafe_members_reject_the_whole_archive(
    tmp_path: Path, installer_wrapper: str, members: list[tuple[tarfile.TarInfo, bytes | None]], rejected: str
) -> None:
    archive = tmp_path / "creds.tar"
    sha256 = _write_tar_members(archive, members)

    result, run_dir = _run_creds_block(tmp_path, archive, sha256, installer_wrapper)

    assert result.returncode == 1, result.stdout
    assert rejected in result.stderr
    assert "refusing the archive" in result.stderr
    assert not (run_dir / "credentials").exists()


def test_archive_over_16_mib_is_rejected_after_the_checksum(tmp_path: Path, installer_wrapper: str) -> None:
    archive = tmp_path / "creds.tar"
    sha256 = _write_tar_members(
        archive, [_regular(f"pad-{index:02d}.cred", b"\0" * 1048576) for index in range(17)]
    )
    assert archive.stat().st_size > 16777216

    result, run_dir = _run_creds_block(tmp_path, archive, sha256, installer_wrapper)

    assert result.returncode == 1, result.stdout
    assert "above the 16 MiB limit; refusing the archive" in result.stderr
    assert not (run_dir / "credentials").exists()
