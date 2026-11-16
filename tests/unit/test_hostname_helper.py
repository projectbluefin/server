"""Executed coverage for bluefin-hostname (bluefin-host): a node without a
static hostname gets a provisioned or a bluefin-<machine-id[:8]> one; a set
name is kept; an invalid one fails without anything being written (#82)."""


import os
import subprocess
from pathlib import Path

import pytest


class Helper:
    def __init__(self, tmp: Path, host_bin: Path) -> None:
        self.helper = host_bin / "bluefin-hostname"
        self.root = tmp / "root"
        (self.root / "etc").mkdir(parents=True)
        self.creds = tmp / "creds"
        self.creds.mkdir()
        self.machine_id("0123abcd456789ef0123456789abcdef\n")
        self.env = dict(os.environ, CREDENTIALS_DIRECTORY=str(self.creds))

    def machine_id(self, text: str) -> None:
        (self.root / "etc" / "machine-id").write_text(text, encoding="utf-8")

    def hostname(self, text: str) -> None:
        (self.root / "etc" / "hostname").write_text(text, encoding="utf-8")

    def credential(self, name: str, text: str) -> None:
        (self.creds / name).write_text(text, encoding="utf-8")

    def __call__(self, *args: str) -> subprocess.CompletedProcess[str]:
        argv = args or (f"--root={self.root}",)
        return subprocess.run([str(self.helper), *argv], capture_output=True, text=True, env=self.env, timeout=30)

    @property
    def static(self) -> str:
        return (self.root / "etc" / "hostname").read_text(encoding="utf-8")


@pytest.fixture()
def helper(tmp_path: Path, host_bin: Path) -> Helper:
    return Helper(tmp_path, host_bin)


def test_no_static_hostname_gets_bluefin_and_the_first_8_of_the_machine_id(helper: Helper) -> None:
    result = helper()
    assert result.returncode == 0, result.stderr
    assert helper.static == "bluefin-0123abcd\n"
    assert result.stderr == "bluefin-hostname: set hostname bluefin-0123abcd (from machine ID)\n"
    assert (helper.root / "etc" / "hostname").stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize(
    "name", ["localhost", "LOCALHOST", "localhost.", "localhost.localdomain", "node.localhost", "# comment"]
)
def test_localhost_and_its_variants_count_as_unset(helper: Helper, name: str) -> None:
    helper.hostname(name + "\n")
    assert helper().returncode == 0
    assert helper.static == "bluefin-0123abcd\n"


def test_an_empty_etc_hostname_counts_as_unset(helper: Helper) -> None:
    helper.hostname("")
    assert helper().returncode == 0
    assert helper.static == "bluefin-0123abcd\n"


def test_a_static_hostname_is_kept(helper: Helper) -> None:
    helper.hostname("# set by hostnamectl\n  blueserver-1  \n")
    helper.credential("system.hostname", "other\n")
    result = helper()
    assert result.returncode == 0, result.stderr
    assert helper.static == "# set by hostnamectl\n  blueserver-1  \n"
    assert "keeping static hostname blueserver-1" in result.stderr


def test_an_invalid_static_hostname_fails_and_is_not_replaced(helper: Helper) -> None:
    helper.hostname("bad_name\n")
    result = helper()
    assert result.returncode == 1
    assert helper.static == "bad_name\n"
    assert result.stderr == (
        "bluefin-hostname: invalid static hostname in /etc/hostname: bad_name; set one with hostnamectl set-hostname\n"
    )


def test_firstboot_hostname_wins_over_system_hostname_and_the_machine_id(helper: Helper) -> None:
    helper.credential("firstboot.hostname", "blueserver-0\n")
    helper.credential("system.hostname", "transient\n")
    result = helper()
    assert result.returncode == 0, result.stderr
    assert helper.static == "blueserver-0\n"
    assert "(from credential firstboot.hostname)" in result.stderr


def test_system_hostname_becomes_the_static_hostname(helper: Helper) -> None:
    helper.credential("system.hostname", "rack1-node4.example.com")
    assert helper().returncode == 0
    assert helper.static == "rack1-node4.example.com\n"


@pytest.mark.parametrize(
    "value", ["bad name", "-lead", "trail-", "a..b", "under_score", "x" * 64, "a" * 60 + ".example"]
)
def test_an_invalid_hostname_credential_fails_with_nothing_written_and_no_fallback(helper: Helper, value: str) -> None:
    helper.credential("system.hostname", value)
    result = helper()
    assert result.returncode == 1
    assert not (helper.root / "etc" / "hostname").exists()
    assert "invalid hostname in credential system.hostname" in result.stderr


def test_rejected_values_are_shell_quoted(helper: Helper) -> None:
    helper.credential("system.hostname", "bad name")
    assert "invalid hostname in credential system.hostname: bad\\ name\n" in helper().stderr


def test_an_invalid_firstboot_hostname_is_not_replaced_by_system_hostname(helper: Helper) -> None:
    helper.credential("firstboot.hostname", "bad_name")
    helper.credential("system.hostname", "good")
    assert helper().returncode == 1
    assert not (helper.root / "etc" / "hostname").exists()


def test_the_longest_valid_label_is_accepted(helper: Helper) -> None:
    helper.credential("system.hostname", "a" * 63)
    assert helper().returncode == 0
    assert helper.static == "a" * 63 + "\n"


@pytest.mark.parametrize("machine_id", ["", "uninitialized", "0123"])
def test_no_machine_id_and_no_credential_fails_with_nothing_written(helper: Helper, machine_id: str) -> None:
    helper.machine_id(machine_id + "\n")
    result = helper()
    assert result.returncode == 1
    assert not (helper.root / "etc" / "hostname").exists()
    assert "no machine ID" in result.stderr


def test_without_a_credentials_directory_it_still_names_the_node(helper: Helper) -> None:
    del helper.env["CREDENTIALS_DIRECTORY"]
    assert helper().returncode == 0
    assert helper.static == "bluefin-0123abcd\n"


def test_a_second_run_keeps_the_name_it_gave(helper: Helper) -> None:
    helper()
    helper.machine_id("fedcba98765432100123456789abcdef\n")
    assert helper().returncode == 0
    assert helper.static == "bluefin-0123abcd\n"


def test_unknown_arguments_are_refused(helper: Helper) -> None:
    result = helper("--bogus")
    assert result.returncode == 2
    assert result.stderr == "bluefin-hostname: unknown argument: --bogus\n"
