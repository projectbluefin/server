"""Contracts for action pins and the shared `just` version in workflows."""


import re
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


def test_action_version_comments_name_exact_releases() -> None:
    annotations = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "uses:" not in line or "docker://" in line:
                continue
            match = re.search(r"#\s*(v[0-9][0-9A-Za-z.-]*)\s*$", line)
            if match:
                annotations.append((path.name, line_number, match.group(1)))
                assert re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", match.group(1)), (
                    path.name,
                    line_number,
                    match.group(1),
                )
    assert annotations
