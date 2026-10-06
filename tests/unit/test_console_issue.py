"""Tests for the console issue banner."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ISSUE_FILE = REPO_ROOT / "files" / "os" / "issue.d" / "30-bluefin.issue"
ISSUE_BST = REPO_ROOT / "elements" / "bluefin-server" / "os-issue.bst"
STACK_BST = REPO_ROOT / "elements" / "bluefin-server" / "os-stack.bst"


def test_issue_file_exists_without_kubestellar() -> None:
    assert ISSUE_FILE.is_file(), f"{ISSUE_FILE} must exist"
    content = ISSUE_FILE.read_text(encoding="utf-8")
    assert "Bluefin Server" in content
    assert "KubeStellar" not in content, "the base image does not ship KubeStellar"


def test_os_issue_element_target_usr_lib_issue_d() -> None:
    assert ISSUE_BST.is_file(), f"{ISSUE_BST} must exist"
    data = yaml.safe_load(ISSUE_BST.read_text(encoding="utf-8"))
    assert data.get("kind") == "import"
    assert data.get("config", {}).get("target") == "/usr/lib/issue.d"


def test_os_stack_includes_os_issue() -> None:
    assert STACK_BST.is_file(), f"{STACK_BST} must exist"
    data = yaml.safe_load(STACK_BST.read_text(encoding="utf-8"))
    depends = data.get("depends", [])
    assert "bluefin-server/os-issue.bst" in depends


def test_banner_shows_hostname_addresses_and_how_to_reach_the_node() -> None:
    lines = ISSUE_FILE.read_text(encoding="utf-8").splitlines()
    # agetty escapes (util-linux 2.42): \n the hostname, \l the tty, \a the
    # usable addresses of every interface, \4 the best IPv4 address. agetty
    # reprints the banner when an address changes, so DHCP late is fine.
    assert lines[0] == r"Bluefin Server \n (\l)"
    assert lines[1] == r"\a"
    assert any(line.startswith("SSH") and line.endswith(r"ssh root@\4") for line in lines)
    assert not any(c.isdigit() for c in "".join(lines[:3]).replace(r"\4", ""))
