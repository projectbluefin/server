"""The weekly opt-in feature e2e run: .github/workflows/e2e-opt-in.yml and scripts/ci/e2e-opt-in.sh.

- The workflow's matrix runs exactly the script's scenarios, and every
  scenario runs a dogfood script that exists.
- The nvidia scenario runs dogfood-nvidia.sh once per driver flavour in the
  set, never on the Container Toolkit sysext, and fails when the set has no
  driver sysext.
- A scenario stops at its first failing call and names it in an error
  annotation.
- The run tests a published release as published: the set is verified
  against the committed release keyring, the harness is the release's tag,
  and the workflow holds no secret and no write token outside its
  issues-only status job.
"""


import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci" / "e2e-opt-in.sh"
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "e2e-opt-in.yml").read_text(encoding="utf-8"))
JOBS = WORKFLOW["jobs"]
BASH = shutil.which("bash") or "/bin/bash"


def script(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run([BASH, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True, check=False)


def scenarios() -> list[str]:
    return script("--scenarios").stdout.split()


def release_set(tmp_path: Path, *names: str) -> Path:
    d = tmp_path / "release"
    d.mkdir()
    for name in names:
        (d / name).touch()
    return d


def test_matrix_runs_every_scenario() -> None:
    assert scenarios()
    assert JOBS["e2e"]["strategy"]["matrix"]["scenario"] == scenarios()
    assert JOBS["e2e"]["strategy"]["fail-fast"] is False


def test_every_scenario_runs_an_existing_dogfood_script(tmp_path: Path) -> None:
    d = release_set(tmp_path, "nvidia-open-595_1.2.raw.zst")
    out = script("--list", str(d))
    assert out.returncode == 0, out.stderr
    listed = [line.split(": ", 1) for line in out.stdout.splitlines()]
    assert sorted({name for name, _ in listed}) == sorted(scenarios())
    for _, call in listed:
        path, *args = call.split()
        assert (ROOT / path).is_file(), path
        assert args[0] == str(d)


def test_nvidia_runs_each_driver_flavour_and_not_the_toolkit(tmp_path: Path) -> None:
    d = release_set(tmp_path, "nvidia-open-595_1.2.raw.zst", "nvidia-open-610_1.2.raw.zst",
                    "nvidia-container-toolkit-1.20.1.raw.zst")
    calls = [line for line in script("--list", str(d)).stdout.splitlines() if line.startswith("nvidia: ")]
    assert calls == [
        f"nvidia: scripts/dogfood-nvidia.sh {d} {d}/nvidia-open-595_1.2.raw.zst",
        f"nvidia: scripts/dogfood-nvidia.sh {d} {d}/nvidia-open-610_1.2.raw.zst",
    ]


def test_nvidia_fails_without_a_driver_sysext(tmp_path: Path) -> None:
    d = release_set(tmp_path, "nvidia-container-toolkit-1.20.1.raw.zst")
    out = script("nvidia", str(d))
    assert out.returncode != 0
    assert "no nvidia-open-*_<version>.raw.zst" in out.stderr


def test_unknown_scenario_and_bad_usage_exit_2(tmp_path: Path) -> None:
    assert script("bogus", str(tmp_path)).returncode == 2
    assert script().returncode == 2
    assert script("mdns").returncode == 2
    assert script("--list").returncode == 2


def fake_dogfood(tmp_path: Path, rc_by_script: dict[str, int]) -> tuple[Path, Path]:
    cwd = tmp_path / "work"
    (cwd / "scripts").mkdir(parents=True)
    log = tmp_path / "calls.log"
    for name, rc in rc_by_script.items():
        (cwd / "scripts" / name).write_text(f'echo "{name} $*" >> "{log}"\nexit {rc}\n', encoding="utf-8")
    return cwd, log


def test_scenario_runs_its_calls_and_stops_at_the_first_failure(tmp_path: Path) -> None:
    d = release_set(tmp_path, "nvidia-open-595_1.2.raw.zst", "nvidia-open-610_1.2.raw.zst")
    cwd, log = fake_dogfood(tmp_path, {"dogfood-nvidia.sh": 1})
    out = script("nvidia", str(d), cwd=cwd)
    assert out.returncode == 1
    assert log.read_text().splitlines() == [f"dogfood-nvidia.sh {d} {d}/nvidia-open-595_1.2.raw.zst"]
    assert re.search(r"::error title=e2e \(nvidia\)::scripts/dogfood-nvidia\.sh \S+ \S+595\S+ failed", out.stdout)


def test_scenario_passes_when_its_script_passes(tmp_path: Path) -> None:
    d = release_set(tmp_path)
    cwd, log = fake_dogfood(tmp_path, {"dogfood-mdns.sh": 0})
    out = script("mdns", str(d), cwd=cwd)
    assert out.returncode == 0, out.stdout + out.stderr
    assert log.read_text().splitlines() == [f"dogfood-mdns.sh {d}"]
    assert "::notice title=e2e (mdns)::passed" in out.stdout


def test_helm_is_pinned_by_version_and_checksum() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert re.search(r"^HELM_VERSION=v\d+\.\d+\.\d+$", text, re.MULTILINE)
    assert re.search(r"^HELM_SHA256=[0-9a-f]{64}$", text, re.MULTILINE)
    assert 'sha256sum -c -' in text


def test_workflow_tests_the_release_as_published() -> None:
    steps = JOBS["e2e"]["steps"]
    checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "${{ needs.release.outputs.tag }}"
    runs = "\n".join(s.get("run", "") for s in steps)
    assert 'publish-release.sh verify dist/release "${TAG#v}" files/os/sysupdate-keys/import-pubring.gpg' in runs
    assert runs.index("publish-release.sh verify") < runs.index('e2e-opt-in.sh "${SCENARIO}"')


def test_workflow_is_read_only_and_secret_free() -> None:
    assert WORKFLOW["permissions"] == {"contents": "read"}
    assert "secrets." not in json.dumps(WORKFLOW)
    for name, job in JOBS.items():
        if name == "status":
            assert job["permissions"] == {"issues": "write"}
        else:
            assert "permissions" not in job, name
        assert isinstance(job.get("timeout-minutes"), int), name
    on = WORKFLOW.get("on", WORKFLOW.get(True))
    assert set(on) == {"schedule", "workflow_dispatch"}, "never on pull_request: it runs a published release"


def test_dispatch_input_reaches_the_shell_through_env_only() -> None:
    resolve = JOBS["release"]["steps"][0]
    assert "inputs." not in resolve["run"]
    assert resolve["env"]["REQUESTED"] == "${{ inputs.release }}"
    tag_check = re.search(r"\[\[ \"\$\{tag\}\" =~ (\S+) \]\]", resolve["run"])
    assert tag_check, "the tag is validated before use"
    env = {**os.environ}
    for good in ("v26.10.1349", "v1.2.3"):
        assert subprocess.run([BASH, "-c", f'tag={good}; [[ "$tag" =~ {tag_check.group(1)} ]]'], env=env).returncode == 0
    for bad in ("main", "v1;rm", "26.10.1", "v1/../x"):
        assert subprocess.run([BASH, "-c", f'tag="{bad}"; [[ "$tag" =~ {tag_check.group(1)} ]]'], env=env).returncode != 0
