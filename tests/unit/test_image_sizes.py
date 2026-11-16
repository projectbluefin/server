"""Unit coverage for scripts/ci/image-sizes.py, the size report image-check
writes for every build and releases publish next to the set."""


import importlib.util
import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci" / "image-sizes.py"

_spec = importlib.util.spec_from_file_location("image_sizes", SCRIPT)
image_sizes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(image_sizes)

VERSION = "26.10.7"
UUID = "d3107d37-a9da-32cf-3c19-49fa3b0cb1df"
MiB = 2**20
# File name -> (metric, size); None for files the report does not measure.
SET = {
    f"bluefin-server_{VERSION}.raw": ("os_ddi_raw", 900 * MiB),
    f"bluefin-server_{VERSION}_{UUID}.usr.raw": ("usr_raw", 200 * MiB),
    f"bluefin-server_{VERSION}_{UUID}.usr-verity.raw": ("usr_verity_raw", 2 * MiB),
    f"bluefin-server-{VERSION}.efi": ("disk_uki", 90 * MiB),
    f"bluefin-server-netboot_{VERSION}.efi": ("netboot_uki", 80 * MiB),
    f"bluefin-server-netboot_{VERSION}.esp.raw": ("netboot_esp_raw", 100 * MiB),
    f"bluefin-server-installer_{VERSION}.raw": ("installer_raw", 2048 * MiB),
    f"zfs_{VERSION}.raw.zst": ("zfs_sysext_raw_zst", 3 * MiB),
    f"nvidia-open-595_{VERSION}.raw.zst": ("nvidia_open_595_sysext_raw_zst", 180 * MiB),
    f"homebrew-integration_{VERSION}.raw.zst": ("homebrew_integration_sysext_raw_zst", 4096),
    "k0s-1.36.4-k0s.0.raw.zst": ("k0s_sysext_raw_zst", 70 * MiB),
    "nvidia-container-toolkit-1.20.1.raw.zst": ("nvidia_container_toolkit_sysext_raw_zst", 9 * MiB),
    f"bluefin-server_{VERSION}.spdx.json": (None, 100),
    "homelab-node.ign": (None, 100),
    "SHA256SUMS": (None, 100),
}


def make_set(dist: Path) -> Path:
    """Sparse files of the sizes in SET, plus a subdirectory nothing measures."""
    (dist / "efi-keys").mkdir(parents=True)
    for name, (_, size) in SET.items():
        with (dist / name).open("wb") as handle:
            handle.truncate(size)
    return dist


@pytest.fixture
def summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "step-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(path))
    return path


def run(capsys: pytest.CaptureFixture[str], *args: object) -> tuple[dict, str, str]:
    assert image_sizes.main([str(a) for a in args]) == 0
    out = capsys.readouterr()
    return json.loads(out.out), out.out, out.err


def newc(*files: tuple[str, bytes]) -> bytes:
    """A newc cpio archive of regular files, trailer included."""
    out = b""
    for ino, (name, data) in enumerate([*files, ("TRAILER!!!", b"")], 1):
        encoded = name.encode() + b"\0"
        fields = (ino, 0o100644, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0)
        out += b"070701" + b"".join(b"%08X" % f for f in fields) + encoded
        out += b"\0" * (-len(out) % 4) + data + b"\0" * (-len(data) % 4)
    return out


def pe(sections: dict[str, bytes]) -> bytes:
    """A PE file with no optional header and just these sections."""
    dos = bytearray(0x40)
    dos[:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, len(dos))
    coff = b"PE\0\0" + struct.pack("<HHIIIHH", 0x8664, len(sections), 0, 0, 0, 0, 0)
    offset = len(dos) + len(coff) + 40 * len(sections)
    table = body = b""
    for name, data in sections.items():
        table += name.encode().ljust(8, b"\0")
        table += struct.pack("<IIIIIIHHI", len(data), 0, len(data), offset + len(body), 0, 0, 0, 0, 0)
        body += data
    return bytes(dos) + coff + table + body


def test_report_measures_each_release_file_and_sysext(tmp_path: Path, capsys, summary: Path) -> None:
    dist = make_set(tmp_path / "diskless")
    report, out, err = run(capsys, dist, "--commit", "abc")
    # The disk UKI here is no PE file, so it has no section metrics.
    assert report == {
        "baseline": None,
        "commit": "abc",
        "delta": {},
        "image_version": VERSION,
        "metrics": {metric: size for metric, size in SET.values() if metric},
    }
    assert out == json.dumps(report, indent=2, sort_keys=True) + "\n"
    assert "::warning" not in err
    table = summary.read_text()
    assert table.startswith(f"### Image sizes of {VERSION}\n\n| File or section | Size |\n| --- | ---: |\n")
    assert "| `installer_raw` | 2.0 GiB |\n" in table
    assert "| `homebrew_integration_sysext_raw_zst` | 4.0 KiB |\n" in table
    assert "Change since" not in table and "Bold" not in table


def test_growth_over_five_percent_or_five_mib_warns(tmp_path: Path, capsys, summary: Path) -> None:
    dist = make_set(tmp_path / "diskless")
    old = tmp_path / "bluefin-server_26.10.6.size.json"
    old.write_text(json.dumps({"image_version": "26.10.6", "metrics": {
        "usr_raw": 190 * MiB,  # +10 MiB, +5.3 %
        "os_ddi_raw": 894 * MiB,  # +6 MiB, +0.7 %
        "homebrew_integration_sysext_raw_zst": 3900,  # +196 B, +5.0 %
        "installer_raw": 2044 * MiB,  # +4 MiB, +0.2 %
        "netboot_uki": 81 * MiB,
        "zfs_sysext_raw_zst": 3 * MiB,
        "gone_sysext_raw_zst": MiB,
    }}))
    report, _, err = run(capsys, dist, "--baseline-json", old)
    assert report["baseline"] == "26.10.6"
    assert report["delta"] == {
        "usr_raw": 10 * MiB,
        "os_ddi_raw": 6 * MiB,
        "homebrew_integration_sysext_raw_zst": 196,
        "installer_raw": 4 * MiB,
        "netboot_uki": -MiB,
        "zfs_sysext_raw_zst": 0,
    }
    warned = [line.split("::")[2].split()[0] for line in err.splitlines() if line.startswith("::warning")]
    assert warned == ["homebrew_integration_sysext_raw_zst", "os_ddi_raw", "usr_raw"]
    assert "::warning title=Image size grew::usr_raw grew by +10.0 MiB (+5.3%) since 26.10.6, to 200.0 MiB\n" in err
    table = summary.read_text()
    assert "| File or section | Size | Change since 26.10.6 |\n| --- | ---: | ---: |\n" in table
    assert "| `usr_raw` | 200.0 MiB | **+10.0 MiB (+5.3%)** |\n" in table
    assert "| `os_ddi_raw` | 900.0 MiB | **+6.0 MiB (+0.7%)** |\n" in table
    assert "| `installer_raw` | 2.0 GiB | +4.0 MiB (+0.2%) |\n" in table
    assert "| `netboot_uki` | 80.0 MiB | -1.0 MiB (-1.2%) |\n" in table
    # Not in the baseline: no change to show. Gone from the set: no row.
    assert "| `k0s_sysext_raw_zst` | 70.0 MiB |  |\n" in table
    assert "gone" not in table
    assert table.endswith("\nBold: grew by more than 5% or 5.0 MiB.\n")


def test_a_usr_image_alone_compares_usr_raw(tmp_path: Path, capsys, summary: Path) -> None:
    dist = make_set(tmp_path / "diskless")
    usr = tmp_path / f"bluefin-server_26.10.6_{UUID}.usr.raw"
    with usr.open("wb") as handle:
        handle.truncate(199 * MiB)
    report, _, err = run(capsys, dist, "--baseline-usr", usr)
    assert (report["baseline"], report["delta"]) == ("26.10.6", {"usr_raw": MiB})
    assert "::warning" not in err
    # A report, from the same release in CI, gives every metric it holds.
    old = tmp_path / "old.size.json"
    old.write_text(json.dumps({"image_version": "26.10.5", "metrics": {"usr_raw": 100 * MiB}}))
    report, _, err = run(capsys, dist, "--baseline-usr", usr, "--baseline-json", old)
    assert (report["baseline"], report["delta"]) == ("26.10.5", {"usr_raw": 100 * MiB})
    assert "::warning title=Image size grew::usr_raw grew by +100.0 MiB (+100.0%)" in err


def test_render_prints_the_step_summary_table(tmp_path: Path, capsys, summary: Path) -> None:
    dist = make_set(tmp_path / "diskless")
    old = tmp_path / "old.size.json"
    old.write_text(json.dumps({"image_version": "26.10.6", "metrics": {"usr_raw": 190 * MiB}}))
    _, out, _ = run(capsys, dist, "--baseline-json", old)
    saved = tmp_path / "report.json"
    saved.write_text(out)
    assert image_sizes.main(["--render", str(saved)]) == 0
    assert summary.read_text() == f"### Image sizes of {VERSION}\n\n{capsys.readouterr().out}"


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("bluefin-server_26.10.8.raw", "os_ddi_raw: more than one file"),
        ("zfs_26.10.8.raw.zst", "more than one zfs sysext"),
    ],
)
def test_an_ambiguous_set_is_refused(tmp_path: Path, extra: str, message: str) -> None:
    dist = make_set(tmp_path / "diskless")
    (dist / extra).write_bytes(b"")
    with pytest.raises(SystemExit, match=message):
        image_sizes.main([str(dist)])


def test_a_set_of_two_versions_is_refused(tmp_path: Path) -> None:
    dist = make_set(tmp_path / "diskless")
    (dist / f"bluefin-server-netboot_{VERSION}.esp.raw").rename(dist / "bluefin-server-netboot_26.10.8.esp.raw")
    with pytest.raises(SystemExit, match=r"more than one image version: \['26\.10\.7', '26\.10\.8'\]"):
        image_sizes.main([str(dist)])


def test_cpio_size_sums_the_files_of_every_archive() -> None:
    first = newc(("init", b"x" * 1001), ("usr/lib/a.so", b"y" * 3))
    second = newc(("etc/initrd-release", b"z" * 10))
    assert image_sizes.cpio_size(first) == 1004
    assert image_sizes.cpio_size(first + b"\0" * 512 + second) == 1014
    with pytest.raises(ValueError, match="no newc cpio header at offset 0"):
        image_sizes.cpio_size(b"070707" + b"0" * 200)


def test_pe_sections_of_anything_else_is_empty() -> None:
    assert image_sizes.pe_sections(b"") == {}
    assert image_sizes.pe_sections(b"MZ" + b"\0" * 200) == {}
    assert image_sizes.pe_sections(pe({".linux": b"k" * 7})) == {".linux": (0x40 + 24 + 40, 7)}


@pytest.mark.skipif(shutil.which("zstd") is None, reason="needs zstd")
def test_disk_uki_sections_and_unpacked_initrd(tmp_path: Path, capsys, summary: Path) -> None:
    initrd = subprocess.run(
        ["zstd", "-qc"], input=newc(("init", b"x" * 5000), ("etc/os-release", b"y" * 70)), capture_output=True, check=True
    ).stdout
    dist = make_set(tmp_path / "diskless")
    (dist / f"bluefin-server-{VERSION}.efi").write_bytes(pe({".linux": b"k" * 1234, ".initrd": initrd}))
    report, _, _ = run(capsys, dist)
    metrics = report["metrics"]
    assert (metrics["uki_linux_section"], metrics["uki_initrd_section"]) == (1234, len(initrd))
    assert metrics["initrd_unpacked"] == 5070
    rows = [line.split("`")[1] for line in summary.read_text().splitlines() if line.startswith("| `")]
    assert rows[:10] == [*image_sizes.FILES, "uki_linux_section", "uki_initrd_section", "initrd_unpacked"]
    assert rows[10:] == sorted(rows[10:])
