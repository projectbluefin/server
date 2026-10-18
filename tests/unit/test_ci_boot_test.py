"""scripts/ci/boot-test.sh holds the boot test's scenarios; build.yml runs its buckets as a matrix.

- The matrix runs exactly the script's buckets, and each scenario runs in
  one bucket only.
- Scenarios that read the image-update artifact (the next/broken sets and
  the Ignition signatures) run only outside releases, and only in buckets
  whose job downloads that artifact.
- A bucket stops at its first failing scenario, so the uploaded logs are
  that scenario's, and names it in an error annotation.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci" / "boot-test.sh"
BUILD_YML = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
JOBS = yaml.safe_load(BUILD_YML)["jobs"]
JOB = JOBS["boot-test"]
BASH = shutil.which("bash") or "/bin/bash"
UPDATE_PATHS = re.compile(r"\bdist/(diskless-next|diskless-broken|ignition-sigs)\b")


def script(*args: str, release: bool = False, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, str(SCRIPT), *args],
        cwd=ROOT,
        env={**os.environ, **(env or {}), "RELEASE": "true" if release else "false"},
        capture_output=True,
        text=True,
        check=False,
    )


def buckets() -> list[str]:
    return script("--buckets").stdout.split()


def scenarios(bucket: str, release: bool) -> list[tuple[str, list[str]]]:
    out = script("--list", bucket, release=release)
    assert out.returncode == 0, out.stderr
    return [(name, shlex.split(cmd)) for name, cmd in (line.split(": ", 1) for line in out.stdout.splitlines())]


def test_the_matrix_runs_every_bucket() -> None:
    assert JOB["strategy"]["fail-fast"] is False
    assert JOB["strategy"]["matrix"]["scenario"] == buckets()
    run = next(s for s in JOB["steps"] if "scripts/ci/boot-test.sh" in s.get("run", ""))
    assert run["run"] == 'bash scripts/ci/boot-test.sh "${SCENARIO}"'
    assert run["env"] == {"RELEASE": "${{ needs.changes.outputs.release }}", "SCENARIO": "${{ matrix.scenario }}"}


def test_qemu_and_ovmf_come_from_the_one_install_script() -> None:
    assert "apt-get" not in str(JOB["steps"]) and "OVMF_RPM" not in BUILD_YML
    users = [name for name, job in JOBS.items()
             if any(s.get("run") == "bash scripts/ci/install-qemu-ovmf.sh" for s in job.get("steps", []))]
    assert users == ["boot-test-preflight", "boot-test"]


@pytest.mark.parametrize("release", [False, True], ids=["pull-request", "release"])
def test_each_scenario_runs_once_and_its_fixtures_exist(release: bool) -> None:
    names = []
    for bucket in buckets():
        found = scenarios(bucket, release)
        assert found, bucket
        for name, words in found:
            names.append(name)
            assert words[words.index("bash") + 1].startswith("scripts/dogfood-"), name
            for word in words:
                for path in re.findall(r"\btests/fixtures/\S+", word):
                    assert (ROOT / path).is_file(), f"{name}: {path}"
    assert len(names) == len(set(names))
    assert len(names) == (11 if release else 15)


def test_update_sets_are_read_only_where_they_are_downloaded() -> None:
    download = next(s for s in JOB["steps"] if s.get("with", {}).get("name") == "image-update")
    skipped = set(re.findall(r"matrix\.scenario != '([\w-]+)'", download["if"]))
    assert "needs.changes.outputs.release != 'true'" in download["if"]
    for bucket in buckets():
        assert not any(UPDATE_PATHS.search(" ".join(w)) for _, w in scenarios(bucket, release=True)), bucket
        uses_update = any(UPDATE_PATHS.search(" ".join(w)) for _, w in scenarios(bucket, release=False))
        assert uses_update == (bucket not in skipped), bucket


def fake_bash(tmp_path: Path, fail_on: str) -> dict[str, str]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "bash"
    fake.write_text(
        "#!/bin/sh\n"
        f'echo "$* target=${{DOGFOOD_TARGET:-}}" >> "{tmp_path}/calls"\n'
        f'[ "${{DOGFOOD_TARGET:-}}" != "{fail_on}" ]\n'
    )
    fake.chmod(0o755)
    return {"PATH": f"{bindir}:{os.environ['PATH']}"}


def test_a_bucket_runs_its_scenarios_in_order(tmp_path: Path) -> None:
    out = script("installer-disks", env=fake_bash(tmp_path, fail_on="none"))
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "calls").read_text().splitlines() == [
        "scripts/dogfood-installer.sh dist/diskless target=prior-install",
        "scripts/dogfood-installer.sh dist/diskless target=foreign-gpt",
    ]
    assert out.stdout.count("::group::") == out.stdout.count("::endgroup::") == 2


def test_a_bucket_stops_at_the_first_failure(tmp_path: Path) -> None:
    out = script("installer-disks", env=fake_bash(tmp_path, fail_on="prior-install"))
    assert out.returncode == 1
    assert len((tmp_path / "calls").read_text().splitlines()) == 1
    assert "::error title=boot-test (installer-disks)::Install from the offline USB installer, boot it, reinstall over it failed" in out.stdout


@pytest.mark.parametrize("args", [[], ["nope"], ["diskless", "install"], ["--list", "nope"]])
def test_usage_errors(args: list[str]) -> None:
    assert script(*args).returncode == 2
