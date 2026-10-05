"""What a build.yml run builds: the `changes` job's release/image/validate.

A wrong `release=true` hands the signing secrets to a run that is not a
reviewed push to main (the nightly schedule runs on main too) and publishes
it; a wrong `image=false` merges an untested FSDK bump. The decide script runs
here with the real base-revision classifier and a stubbed `gh`.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8"))
JOBS = WORKFLOW["jobs"]
DECIDE = next(s for s in JOBS["changes"]["steps"] if s.get("id") == "decide")["run"]


def decide(tmp_path: Path, event: str, ref: str = "refs/heads/main", action: str = "",
           label: str = "", labels: tuple[str, ...] = (), changed: tuple[str, ...] = ()) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text("#!/bin/sh\ncat \"$CHANGED_FILE\"\n", encoding="utf-8")
    gh.chmod(0o755)
    changed_file = tmp_path / "changed-in"
    changed_file.write_text("".join(f"{p}\n" for p in changed), encoding="utf-8")
    output = tmp_path / "output"
    output.touch()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CHANGED_FILE": str(changed_file),
        "GITHUB_EVENT_NAME": event,
        "GITHUB_REF": ref,
        "GITHUB_OUTPUT": str(output),
        "GITHUB_REPOSITORY": "projectbluefin/server",
        "RUNNER_TEMP": str(tmp_path),
        "PR_NUMBER": "1",
        "PR_LABELS": json.dumps(list(labels)),
        "ACTION": action,
        "LABEL": label,
    }
    subprocess.run(["bash", "-c", DECIDE], cwd=ROOT, env=env, check=True, capture_output=True)
    return dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())


ELEMENT = ("elements/bluefin-server/nfs-utils.bst",)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"event": "push"}, ("true", "true", "false")),
        ({"event": "workflow_dispatch"}, ("true", "true", "false")),
        ({"event": "schedule"}, ("true", "false", "false")),
        ({"event": "workflow_dispatch", "ref": "refs/heads/topic"}, ("true", "false", "false")),
        ({"event": "pull_request", "action": "opened", "changed": ELEMENT}, ("false", "false", "true")),
        ({"event": "pull_request", "action": "synchronize", "changed": ELEMENT, "labels": ("full-build",)},
         ("true", "false", "true")),
        ({"event": "pull_request", "action": "labeled", "label": "full-build", "changed": ELEMENT,
          "labels": ("full-build",)}, ("true", "false", "true")),
        ({"event": "pull_request", "action": "opened", "changed": ("elements/freedesktop-sdk.bst",)},
         ("true", "false", "true")),
        ({"event": "pull_request", "action": "opened", "changed": ("patches/freedesktop-sdk/0006-x.patch",)},
         ("true", "false", "true")),
        ({"event": "pull_request", "action": "opened", "changed": ("patches/freedesktop-sdk/0007-x.patch",)},
         ("true", "false", "true")),
        ({"event": "pull_request", "action": "opened", "changed": ("docs/skills/index.md",),
          "labels": ("full-build",)}, ("false", "false", "true")),
        ({"event": "pull_request", "action": "labeled", "label": "hold", "changed": ELEMENT,
          "labels": ("hold", "full-build")}, ("false", "false", "false")),
    ],
)
def test_decide(tmp_path: Path, kwargs: dict, expected: tuple[str, str, str]) -> None:
    out = decide(tmp_path, **kwargs)
    assert (out["image"], out["release"], out["validate"]) == expected


def test_signing_secrets_and_publishing_are_release_only() -> None:
    for name, job in JOBS.items():
        for step in job.get("steps", []):
            for key, value in (step.get("env") or {}).items():
                if "secrets." in str(value) and "GITHUB_TOKEN" not in str(value):
                    if name in ("kernel-cache", "kernel-cache-dev"):
                        # The CAS push key, in a job that only runs for
                        # releases and holds no signing secret.
                        assert (key, value) == ("CASD_CLIENT_KEY", "${{ secrets.CASD_CLIENT_KEY }}")
                        assert job["if"] == "needs.changes.outputs.release == 'true'"
                        continue
                    assert name == "build", (name, key)
                    assert str(value).startswith("${{ needs.changes.outputs.release == 'true' && secrets."), key
    assert "needs.changes.outputs.release == 'true'" in JOBS["release"]["if"]
