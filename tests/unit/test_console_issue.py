"""Tests for console issue banner and KubeStellar dashboard URL output."""

from __future__ import annotations

from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ISSUE_FILE = REPO_ROOT / "files" / "os" / "issue.d" / "40-kubestellar.issue"
ISSUE_BST = REPO_ROOT / "elements" / "bluefin-server" / "os-issue.bst"
STACK_BST = REPO_ROOT / "elements" / "bluefin-server" / "os-stack.bst"


def test_issue_file_exists_and_contains_kubestellar_url() -> None:
    assert ISSUE_FILE.is_file(), f"{ISSUE_FILE} must exist"
    content = ISSUE_FILE.read_text(encoding="utf-8")
    assert "Bluefin Server" in content
    assert "KubeStellar Console: https://127.0.0.1:8080/" in content
    assert "ssh -L 8080:127.0.0.1:8080" in content
    assert "root / bluefin" not in content, (
        "the banner must not advertise a root password login: root has no "
        "password and sshd refuses root entirely; the operator account is core"
    )


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
