"""The systemd parsing helpers model systemd, so tests built on them mean something."""

from __future__ import annotations

from pathlib import Path

import pytest

from _systemd import SystemdFile, Tmpfile, preset, tmpfiles


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_repeated_keys_accumulate_and_the_last_single_value_wins(tmp_path: Path) -> None:
    unit = SystemdFile(
        write(
            tmp_path,
            "a.service",
            "[Unit]\nAfter=a.target b.target\nAfter = c.target\n"
            "[Service]\nRestart=no\nRestart=on-failure\n",
        )
    )
    assert unit.words("Unit", "After") == ["a.target", "b.target", "c.target"]
    assert unit.value("Service", "Restart") == "on-failure"
    assert unit.value("Service", "Type") is None


def test_comments_and_continuations_follow_systemd_syntax(tmp_path: Path) -> None:
    unit = SystemdFile(
        write(
            tmp_path,
            "a.service",
            "# comment\n; comment\n[Service]\nExecStart=/usr/bin/foo \\\n"
            "# comment inside a continuation\n  --bar\nEnvironment=A=\\\\\n",
        )
    )
    assert unit.commands() == [["/usr/bin/foo", "--bar"]]
    assert unit.values("Service", "Environment") == ["A=\\\\"]


def test_dropins_reset_keys_but_not_dependencies(tmp_path: Path) -> None:
    unit = write(
        tmp_path,
        "a.service",
        "[Unit]\nWants=x.service\nConditionPathExists=/a\nConditionHost=h\n"
        "[Service]\nExecStart=/usr/bin/old\n",
    )
    dropin = write(
        tmp_path,
        "10-override.conf",
        "[Unit]\nWants=\nConditionPathExists=\nConditionPathExists=/b\n"
        "[Service]\nExecStart=\nExecStart=/usr/bin/new\n",
    )
    merged = SystemdFile(unit, dropin)
    assert merged.words("Unit", "Wants") == ["x.service"]
    assert merged.sections["Unit"]["ConditionPathExists"] == ["/b"]
    assert "ConditionHost" not in merged.sections["Unit"]
    assert merged.commands() == [["/usr/bin/new"]]


def test_commands_expand_environment_like_systemd(tmp_path: Path) -> None:
    unit = SystemdFile(
        write(
            tmp_path,
            "a.service",
            '[Service]\nEnvironment="ARGS=--one --two" ONE=x\n'
            "ExecStart=-/usr/bin/foo $ARGS ${ARGS} pre${ONE} $$HOME $MISSING\n",
        )
    )
    assert unit.commands() == [
        ["/usr/bin/foo", "--one", "--two", "--one --two", "prex", "$HOME"]
    ]


def test_malformed_lines_are_errors_not_silently_dropped(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SystemdFile(write(tmp_path, "a.service", "[Unit]\nAfter\n"))
    with pytest.raises(ValueError):
        SystemdFile(write(tmp_path, "b.service", "After=a.target\n"))


def test_first_matching_preset_wins_across_files_in_name_order(tmp_path: Path) -> None:
    late = write(tmp_path, "90-late.preset", "enable *\n")
    early = write(tmp_path, "20-early.preset", "# comment\ndisable foo*.service\n")
    assert preset("foo.service", [late, early]) == "disable"
    assert preset("bar.service", [late, early]) == "enable"
    assert preset("bar.service", [early]) is None


def test_tmpfiles_fields_default_to_dash(tmp_path: Path) -> None:
    conf = write(
        tmp_path,
        "a.conf",
        "# comment\nd /var/lib/a 0755 root root\nL /etc/b - - - - ../run/b c\n",
    )
    assert tmpfiles(conf) == [
        Tmpfile("d", "/var/lib/a", "0755", "root", "root"),
        Tmpfile("L", "/etc/b", argument="../run/b c"),
    ]
