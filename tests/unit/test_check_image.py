"""Unit coverage for .github/scripts/check-image.py and files/prune/prune.sh."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "check-image.py"
PRUNE = ROOT / "files" / "prune" / "prune.sh"

_spec = importlib.util.spec_from_file_location("check_image", SCRIPT)
check_image = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_image)


def write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_lookup_resolves_symlinks_inside_the_image(tmp_path):
    write(tmp_path / "usr/bin/real")
    (tmp_path / "usr/bin/abs").symlink_to("/usr/bin/real")
    (tmp_path / "usr/bin/rel").symlink_to("real")
    (tmp_path / "usr/bin/host").symlink_to("/etc/hostname")

    assert check_image.lookup([tmp_path], "/usr/bin/abs") == tmp_path / "usr/bin/real"
    assert check_image.lookup([tmp_path], "/usr/bin/rel") == tmp_path / "usr/bin/real"
    assert check_image.lookup([tmp_path], "/sbin/real") == tmp_path / "usr/bin/real"
    assert check_image.lookup([tmp_path], "/usr/bin/host") is None


def test_lookup_prefers_the_upper_layer(tmp_path):
    upper, lower = tmp_path / "sysext", tmp_path / "usr-root"
    write(lower / "usr/bin/tool", "lower")
    write(lower / "usr/bin/base-only")
    write(upper / "usr/bin/tool", "upper")

    assert check_image.lookup([upper, lower], "/usr/bin/tool").read_text() == "upper"
    assert check_image.lookup([upper, lower], "/usr/bin/base-only") is not None


@pytest.mark.parametrize(
    ("command", "program"),
    [
        ("/usr/bin/foo --flag", "/usr/bin/foo"),
        ("@/usr/bin/foo foo", "/usr/bin/foo"),
        ("+!bar", "bar"),
        ("-plymouth quit", None),
        ("@-/usr/bin/foo", None),
        ("${CMD} x", None),
        ("%h/bin/x", None),
        ("", None),
    ],
)
def test_first_program(command, program):
    assert check_image.first_program(command) == program


def test_check_programs_flags_missing_unit_and_udev_programs(tmp_path):
    write(tmp_path / "usr/bin/present")
    write(tmp_path / "usr/lib/udev/helper_id")
    write(
        tmp_path / "usr/lib/systemd/system/a.service",
        "[Service]\nExecStart=/usr/bin/present\nExecStop=/usr/bin/gone\nExecStartPre=-/usr/bin/optional\n",
    )
    write(
        tmp_path / "usr/lib/systemd/system/b.service",
        "[Unit]\nConditionPathExists=/usr/bin/guarded\n[Service]\nExecStart=/usr/bin/guarded\n",
    )
    write(
        tmp_path / "usr/lib/udev/rules.d/60-x.rules",
        'IMPORT{program}="helper_id x"\nRUN+="missing_id"\nRUN{builtin}+="kmod load"\n',
    )

    errors = check_image.check_programs("usr", [tmp_path], tmp_path)

    assert errors == [
        "usr: /usr/lib/systemd/system/a.service runs missing /usr/bin/gone",
        "usr: /usr/lib/udev/rules.d/60-x.rules runs missing missing_id",
    ]


@pytest.mark.skipif(shutil.which("readelf") is None, reason="needs binutils")
def test_check_libraries_requires_every_needed_soname(tmp_path):
    binary = tmp_path / "usr/bin/true"
    binary.parent.mkdir(parents=True)
    shutil.copy(shutil.which("true"), binary)

    errors = check_image.check_libraries("usr", [tmp_path], tmp_path)
    assert any("needs missing libc.so.6" in e for e in errors)

    needed = check_image.elf_needed([binary])[0][binary]
    for soname in needed:
        write(tmp_path / "usr/lib/x86_64-linux-gnu" / soname)
    assert check_image.check_libraries("usr", [tmp_path], tmp_path) == []


def dlopen_note(*entries: str) -> bytes:
    """ELF bytes carrying a systemd-style .note.dlopen JSON payload."""
    return b"\x7fELF\x00\x00" + b"\x00".join(e.encode() for e in entries) + b"\x00"


def test_check_libraries_flags_a_missing_required_dlopen(tmp_path, monkeypatch):
    # readelf sees no DT_NEEDED here, so only the .note.dlopen path can fail.
    monkeypatch.setattr(check_image, "elf_needed", lambda paths: ({}, {}))
    binary = tmp_path / "usr/lib/systemd/systemd-x"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(
        dlopen_note(
            '[{"feature":"a","priority":"required","soname":["liba.so.2","liba.so.1"]}]',
            '[{"feature":"b","priority":"recommended","soname":["libb.so.1"]}]',
        )
    )

    assert check_image.dlopen_required(binary) == [["liba.so.2", "liba.so.1"]]
    assert check_image.check_libraries("usr", [tmp_path], tmp_path) == [
        "usr: /usr/lib/systemd/systemd-x requires dlopen of missing liba.so.2 or liba.so.1"
    ]

    # Any one alternative satisfies the entry; a recommended entry stays optional.
    write(tmp_path / "usr/lib/x86_64-linux-gnu/liba.so.1")
    assert check_image.check_libraries("usr", [tmp_path], tmp_path) == []


def test_dlopen_required_skips_malformed_notes(tmp_path):
    binary = tmp_path / "x"
    binary.write_bytes(
        dlopen_note(
            '[{"soname" broken}]',
            '[{"feature":"a","priority":"required","soname":["liba.so.1"]}]',
        )
    )

    assert check_image.dlopen_required(binary) == [["liba.so.1"]]
    assert check_image.dlopen_required(tmp_path / "missing") == []


def test_elf_needed_parses_multi_file_readelf_output(monkeypatch):
    # Images hold many ELF files, so readelf always runs on a batch and prints
    # a "File:" header before each file's dynamic section.
    out = """
File: /img/usr/bin/a

Dynamic section at offset 0x2d00 contains 3 entries:
  Tag        Type                         Name/Value
 0x0000000000000001 (NEEDED)             Shared library: [libx.so.1]
 0x000000000000001d (RUNPATH)            Library runpath: [$ORIGIN/../lib/a:/opt/a]

File: /img/usr/bin/b

Dynamic section at offset 0x2d00 contains 2 entries:
 0x0000000000000001 (NEEDED)             Shared library: [liby.so.2]
 0x000000000000000f (RPATH)              Library rpath: [/usr/lib/b]
"""
    monkeypatch.setattr(
        check_image.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr=""),
    )
    a, b = Path("/img/usr/bin/a"), Path("/img/usr/bin/b")

    needed, runpaths = check_image.elf_needed([a, b])

    assert needed == {a: ["libx.so.1"], b: ["liby.so.2"]}
    assert runpaths == {a: ["$ORIGIN/../lib/a", "/opt/a"], b: ["/usr/lib/b"]}


def test_waivers_are_arch_neutral_and_shrink_only(monkeypatch):
    monkeypatch.setattr(
        check_image,
        "KNOWN_BROKEN",
        {"/usr/lib/*-linux-gnu/x.so needs missing liby.so.1", "/usr/bin/fixed runs missing z"},
    )
    errors = [
        "usr: /usr/lib/aarch64-linux-gnu/x.so needs missing liby.so.1",
        "initrd: /usr/lib/x86_64-linux-gnu/x.so needs missing liby.so.1",
        "usr: /usr/bin/new runs missing q",
    ]

    assert check_image.apply_waivers(errors) == [
        "usr: /usr/bin/new runs missing q",
        "stale KNOWN_BROKEN entry, delete it: /usr/bin/fixed runs missing z",
    ]


def test_waivers_ignore_library_version_numbers(monkeypatch):
    monkeypatch.setattr(
        check_image, "KNOWN_BROKEN", {"/usr/lib/*-linux-gnu/libv.so.* needs missing libz.so.1"}
    )
    errors = ["nv: /usr/lib/x86_64-linux-gnu/libv.so.595.104.02 needs missing libz.so.1"]

    assert check_image.apply_waivers(errors) == []


def test_diff_report_lists_removed_and_added_paths():
    report = check_image.diff_report({"/bin", "/bin/a", "/bin/b"}, {"/bin", "/bin/b", "/bin/c"})

    assert "1 removed, 1 added" in report
    assert "/bin/a" in report.split("Removed")[1].split("</details>")[0]
    assert "/bin/c" in report.split("Added")[1]


def run_prune(root: Path, *lists: Path):
    return subprocess.run(
        ["sh", str(PRUNE), str(root), *map(str, lists)], capture_output=True, text=True
    )


def test_prune_removes_globs_and_ignores_comments(tmp_path):
    root = tmp_path / "root"
    write(root / "usr/lib/x86_64-linux-gnu/libicuuc.so.78")
    write(root / "usr/lib/x86_64-linux-gnu/libicudata.so.78.3")
    write(root / "usr/lib/x86_64-linux-gnu/libc.so.6")
    write(root / "usr/share/icu/78.3/data")
    lst = write(
        tmp_path / "a.list",
        "# comment\n\nusr/lib/*-linux-gnu/libicu*.so*   # trailing\nusr/share/icu\n",
    )

    result = run_prune(root, lst)

    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in (root / "usr/lib/x86_64-linux-gnu").iterdir()) == ["libc.so.6"]
    assert not (root / "usr/share/icu").exists()


def test_prune_fails_on_a_stale_pattern(tmp_path):
    root = tmp_path / "root"
    write(root / "usr/bin/keep")
    lst = write(tmp_path / "a.list", "usr/bin/gone\n")

    result = run_prune(root, lst)

    assert result.returncode != 0
    assert "matches nothing: usr/bin/gone" in result.stderr
    assert (root / "usr/bin/keep").exists()


@pytest.mark.parametrize("name", ["common.list", "usr.list", "initrd.list"])
def test_prune_lists_never_touch_load_bearing_paths(name):
    patterns = [
        line.split("#", 1)[0].strip()
        for line in (PRUNE.parent / name).read_text().splitlines()
    ]
    patterns = [p for p in patterns if p]
    protected = [
        "usr/bin/gpg",
        "usr/bin/gpgv",
        "usr/bin/gpg-agent",
        "usr/libexec/keyboxd",
        "usr/lib/locale",
        "usr/lib/systemd",
    ]
    if name != "initrd.list":
        # /usr: libarchive links libxml2, which links these. The initrd has neither.
        protected += [
            "usr/lib/x86_64-linux-gnu/libicuuc.so.78",
            "usr/lib/x86_64-linux-gnu/libicudata.so.78",
        ]
    for pattern in patterns:
        assert pattern.startswith("usr/"), pattern
        assert ".." not in pattern, pattern
        for path in protected:
            assert not Path(path).match(pattern), (pattern, path)


def test_installer_image_rejects_oversized_sparse_file_before_extraction(tmp_path):
    image = tmp_path / "bluefin-server-installer_26.10.1.raw"
    with image.open("wb") as handle:
        handle.truncate(4 * 2**30)
    with pytest.raises(SystemExit, match="installer image.*4 GiB"):
        check_image.main([str(tmp_path)])
