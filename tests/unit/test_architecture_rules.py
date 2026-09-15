"""Architecture-rule invariants for the Flatcar payload migration."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS = REPO_ROOT / "AGENTS.md"
ADR = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-09-13-flatcar-binary-imports-adr.md"
)


def test_hard_rule_scopes_fsdk_to_installer_and_allows_flatcar_payload_imports() -> None:
    """Rule 1 must allow Flatcar OS-payload imports without loosening the installer.

    Note: This test matches exact contractual phrases in AGENTS.md defining the
    boundary between FSDK installer composition and Flatcar binary imports.
    """
    agents = AGENTS.read_text(encoding="utf-8")

    assert "Installer image composes from FSDK 26.08 `components/*`" in agents
    assert "OS payload may import Flatcar binaries pinned by digest" in agents
    assert "Never use `platform.bst`" in agents


def test_flatcar_binary_import_adr_records_decision_and_rejected_alternatives() -> None:
    """The rule change must have a decision record, not only a terse AGENTS.md edit.

    Note: These assertions guard the structural sections and core decisions of the ADR.
    """
    adr = ADR.read_text(encoding="utf-8")

    assert "## Decision" in adr
    assert "installer image" in adr
    assert "installed OS payload" in adr
    assert "pinned by digest" in adr
    assert "### Rebuild Flatcar from source in BuildStream" in adr
    assert "### Keep the status quo hybrid" in adr
