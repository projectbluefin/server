"""Every workflow installs the same `just`, so CI never runs two versions at once."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def just_installs() -> list[tuple[str, str, str]]:
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for name, job in yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"].items():
            for step in job.get("steps", []):
                tool = str(step.get("with", {}).get("tool", ""))
                if step.get("uses", "").startswith("taiki-e/install-action@") and tool.startswith("just@"):
                    found.append((f"{path.name}:{name}", step["uses"], tool))
    return found


def test_just_is_pinned_identically_everywhere() -> None:
    installs = just_installs()
    assert len(installs) >= 6, installs
    assert len({(uses, tool) for _, uses, tool in installs}) == 1, installs
