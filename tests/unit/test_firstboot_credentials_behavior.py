"""Executed coverage for files/os/libexec/bluefin-firstboot-credentials.

The helper replaces `systemd-firstboot --force --welcome=no` in
bluefin-firstboot-credentials.service because Flatcar's /usr is built without
systemd-firstboot. These tests drive it under bash against a scratch --root
with credentials laid out the way ImportCredential= presents them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "files" / "os" / "libexec" / "bluefin-firstboot-credentials"


def _run(tmp_path: Path, creds: dict[str, str], zoneinfo: tuple[str, ...] = ("Europe/Berlin", "UTC")):
    root = tmp_path / "root"
    creds_dir = tmp_path / "creds"
    creds_dir.mkdir(parents=True)
    for name, value in creds.items():
        (creds_dir / name).write_text(value, encoding="utf-8")
    for tz in zoneinfo:
        target = root / "usr" / "share" / "zoneinfo" / tz
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"TZif2")
    (root / "etc").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, CREDENTIALS_DIRECTORY=str(creds_dir))
    result = subprocess.run(
        ["bash", str(HELPER), f"--root={root}"],
        capture_output=True,
        text=True,
        env=env,
    )
    return root, result


def test_helper_is_bash_that_passes_syntax() -> None:
    # /usr/bin/bash, not /bin/bash: /bin is a tmpfiles-created symlink on
    # Flatcar and the unit runs before sysinit.target.
    assert HELPER.read_text(encoding="utf-8").startswith("#!/usr/bin/bash\n")
    subprocess.run(["bash", "-n", str(HELPER)], check=True)


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_helper_is_shellcheck_clean_at_warning_level() -> None:
    subprocess.run(["shellcheck", "-S", "warning", str(HELPER)], check=True)


def test_all_five_credentials_write_what_systemd_firstboot_would(tmp_path: Path) -> None:
    root, result = _run(
        tmp_path,
        {
            "firstboot.locale": "de_DE.UTF-8\n",
            "firstboot.locale-messages": "en_US.UTF-8",
            "firstboot.keymap": "de-latin1\n",
            "firstboot.timezone": "Europe/Berlin\n",
            "firstboot.hostname": "node-01.lab.example\n",
        },
    )
    assert result.returncode == 0, result.stderr
    assert (root / "etc" / "locale.conf").read_text() == "LANG=de_DE.UTF-8\nLC_MESSAGES=en_US.UTF-8\n"
    assert (root / "etc" / "vconsole.conf").read_text() == "KEYMAP=de-latin1\n"
    localtime = root / "etc" / "localtime"
    assert localtime.is_symlink()
    assert os.readlink(localtime) == "../usr/share/zoneinfo/Europe/Berlin"
    assert (root / "etc" / "hostname").read_text() == "node-01.lab.example\n"


def test_only_supplied_credentials_are_applied(tmp_path: Path) -> None:
    root, result = _run(tmp_path, {"firstboot.hostname": "pxe-client"})
    assert result.returncode == 0, result.stderr
    assert (root / "etc" / "hostname").read_text() == "pxe-client\n"
    assert not (root / "etc" / "locale.conf").exists()
    assert not (root / "etc" / "vconsole.conf").exists()
    assert not (root / "etc" / "localtime").exists()


def test_existing_files_are_overwritten_like_force(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "etc").mkdir(parents=True)
    (root / "etc" / "hostname").write_text("localhost\n")
    (root / "etc" / "localtime").symlink_to("../usr/share/zoneinfo/UTC")
    _, result = _run(
        tmp_path, {"firstboot.hostname": "renamed", "firstboot.timezone": "Europe/Berlin"}
    )
    assert result.returncode == 0, result.stderr
    assert (root / "etc" / "hostname").read_text() == "renamed\n"
    assert os.readlink(root / "etc" / "localtime") == "../usr/share/zoneinfo/Europe/Berlin"


@pytest.mark.parametrize(
    ("creds", "message"),
    [
        ({"firstboot.hostname": "bad host"}, "invalid hostname"),
        ({"firstboot.hostname": "-leading"}, "invalid hostname"),
        ({"firstboot.hostname": "trailing-"}, "invalid hostname"),
        ({"firstboot.hostname": "foo-.bar"}, "invalid hostname"),
        ({"firstboot.hostname": "foo..bar"}, "invalid hostname"),
        ({"firstboot.hostname": "h\u00f4te"}, "invalid hostname"),
        ({"firstboot.hostname": "host\r"}, "invalid hostname"),
        ({"firstboot.hostname": "a" * 65}, "invalid hostname"),
        ({"firstboot.timezone": "../../etc/passwd"}, "invalid or unknown timezone"),
        ({"firstboot.timezone": "Mars/Olympus"}, "invalid or unknown timezone"),
        ({"firstboot.locale": "en_US.UTF-8; rm -rf /"}, "invalid locale"),
        ({"firstboot.keymap": "us/../../x"}, "invalid keymap"),
    ],
)
def test_invalid_values_fail_without_writing(tmp_path: Path, creds: dict[str, str], message: str) -> None:
    root, result = _run(tmp_path, {"firstboot.hostname": "good", **creds})
    assert result.returncode == 1
    assert message in result.stderr
    assert sorted(p.name for p in (root / "etc").iterdir()) == []


def test_non_ascii_keymap_is_rejected_under_a_utf8_locale(tmp_path: Path) -> None:
    # PID 1 exports LANG from the locale.conf this helper writes; systemd's
    # validators are ASCII-only, so [[:alnum:]] must not widen with the locale.
    # The keymap regex uses [[:alnum:]] (the hostname one is literal
    # [A-Za-z0-9], which does not widen under C.UTF-8), so this test fails if
    # the helper's `export LC_ALL=C` is removed: "hôte" would then be written
    # to vconsole.conf as a valid keymap.
    root = tmp_path / "root"
    creds_dir = tmp_path / "creds"
    creds_dir.mkdir()
    (creds_dir / "firstboot.keymap").write_text("h\u00f4te", encoding="utf-8")
    (creds_dir / "firstboot.locale").write_text("h\u00f4te", encoding="utf-8")
    (root / "etc").mkdir(parents=True)
    env = dict(os.environ, CREDENTIALS_DIRECTORY=str(creds_dir), LC_ALL="C.UTF-8", LANG="C.UTF-8")
    result = subprocess.run(["bash", str(HELPER), f"--root={root}"], capture_output=True, text=True, env=env)
    assert result.returncode == 1
    assert "invalid locale" in result.stderr or "invalid keymap" in result.stderr
    assert sorted(p.name for p in (root / "etc").iterdir()) == []


def test_keymap_length_is_capped_like_systemd(tmp_path: Path) -> None:
    # keymap_is_valid() requires strlen < 128.
    root, result = _run(tmp_path, {"firstboot.keymap": "k" * 127})
    assert result.returncode == 0, result.stderr
    assert (root / "etc" / "vconsole.conf").read_text() == "KEYMAP=" + "k" * 127 + "\n"
    root, result = _run(tmp_path / "long", {"firstboot.keymap": "k" * 128})
    assert result.returncode == 1
    assert "invalid keymap" in result.stderr


def test_locale_only_and_messages_only_write_a_single_line(tmp_path: Path) -> None:
    # The `{ [ -n ] && printf; ... } > file` group must not trip errexit when
    # one of the two values is empty.
    root, result = _run(tmp_path / "lang", {"firstboot.locale": "de_DE.UTF-8"})
    assert result.returncode == 0, result.stderr
    assert (root / "etc" / "locale.conf").read_text() == "LANG=de_DE.UTF-8\n"
    root, result = _run(tmp_path / "msgs", {"firstboot.locale-messages": "en_US.UTF-8"})
    assert result.returncode == 0, result.stderr
    assert (root / "etc" / "locale.conf").read_text() == "LC_MESSAGES=en_US.UTF-8\n"
    _, result = _run(tmp_path / "bad", {"firstboot.locale-messages": "en_US; rm -rf /"})
    assert result.returncode == 1
    assert "invalid locale" in result.stderr


def test_control_characters_in_a_rejected_value_are_made_visible(tmp_path: Path) -> None:
    _, result = _run(tmp_path, {"firstboot.hostname": "host\r"})
    assert result.returncode == 1
    assert "invalid hostname in credential: $'host\\r'" in result.stderr


def test_hostname_labels_may_contain_interior_hyphens_and_digits(tmp_path: Path) -> None:
    root, result = _run(tmp_path, {"firstboot.hostname": "a-1.b-2-c.example"})
    assert result.returncode == 0, result.stderr
    assert (root / "etc" / "hostname").read_text() == "a-1.b-2-c.example\n"


def test_nul_byte_in_a_credential_is_rejected(tmp_path: Path) -> None:
    # $(<file) would silently drop the NUL and accept "hostname".
    root = tmp_path / "root"
    creds_dir = tmp_path / "creds"
    creds_dir.mkdir()
    (creds_dir / "firstboot.hostname").write_bytes(b"host\0name")
    (root / "etc").mkdir(parents=True)
    env = dict(os.environ, CREDENTIALS_DIRECTORY=str(creds_dir))
    result = subprocess.run(["bash", str(HELPER), f"--root={root}"], capture_output=True, text=True, env=env)
    assert result.returncode == 1
    assert "NUL byte in credential firstboot.hostname" in result.stderr
    assert sorted(p.name for p in (root / "etc").iterdir()) == []


def test_nonexistent_credentials_directory_is_an_error(tmp_path: Path) -> None:
    env = dict(os.environ, CREDENTIALS_DIRECTORY=str(tmp_path / "missing"))
    result = subprocess.run(
        ["bash", str(HELPER), f"--root={tmp_path}"], capture_output=True, text=True, env=env
    )
    assert result.returncode == 1
    assert "is not a directory" in result.stderr


def test_missing_credentials_directory_is_an_error(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k != "CREDENTIALS_DIRECTORY"}
    result = subprocess.run(
        ["bash", str(HELPER), f"--root={tmp_path}"], capture_output=True, text=True, env=env
    )
    assert result.returncode == 1
    assert "CREDENTIALS_DIRECTORY is not set" in result.stderr


def test_empty_credential_is_treated_as_absent(tmp_path: Path) -> None:
    root, result = _run(tmp_path, {"firstboot.hostname": "ok", "firstboot.keymap": "\n"})
    assert result.returncode == 0, result.stderr
    assert not (root / "etc" / "vconsole.conf").exists()
    assert (root / "etc" / "hostname").read_text() == "ok\n"
