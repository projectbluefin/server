"""scripts/ci/dogfood-preflight.sh fails before the image build when the boot test could not run.

- build waits for boot-test-preflight, which installs the boot test's tools
  the same way boot-test does and runs the check, so a missing host tool
  (#486: mcopy) fails in minutes instead of after the build.
- Every tool its pattern finds in the dogfood scripts boot-test runs is
  listed, as a host tool or as one the runner never runs; a new one fails
  the check until it is.
- A missing tool, firmware file or KVM device is an error.
"""


import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci" / "dogfood-preflight.sh"
BASH = shutil.which("bash") or "/bin/bash"
JOBS = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8"))["jobs"]
PREFLIGHT = JOBS["boot-test-preflight"]


def test_build_waits_for_the_preflight() -> None:
    assert PREFLIGHT["needs"] == "changes"
    assert PREFLIGHT["if"] == "${{ !cancelled() && needs.changes.outputs.image == 'true' }}"
    assert PREFLIGHT["permissions"] == {"contents": "read"}
    assert PREFLIGHT["runs-on"] == "ubuntu-26.04" and PREFLIGHT["timeout-minutes"] <= 15
    runs = [s.get("run") for s in PREFLIGHT["steps"] if "run" in s]
    assert runs == ["bash scripts/ci/install-qemu-ovmf.sh", "bash scripts/ci/dogfood-preflight.sh"]
    build = JOBS["build"]
    assert "boot-test-preflight" in build["needs"]
    assert "needs.boot-test-preflight.result == 'success'" in build["if"]


def host_tools() -> list[str]:
    out = subprocess.run([BASH, str(SCRIPT), "--tools"], capture_output=True, text=True, check=True)
    return out.stdout.split()


def runner(tmp_path: Path, missing: str = "") -> dict[str, str]:
    """A PATH holding only grep, sort and a stub per host tool (minus `missing`), plus firmware and KVM stand-ins."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for real in ("grep", "sort"):
        (bindir / real).symlink_to(shutil.which(real) or f"/usr/bin/{real}")
    for tool in host_tools():
        if tool != missing:
            (bindir / tool).write_text("#!/bin/sh\n")
            (bindir / tool).chmod(0o755)
    firmware = tmp_path / "OVMF.fd"
    firmware.write_bytes(b"fd")
    kvm = tmp_path / "kvm"
    kvm.touch()
    return {"PATH": str(bindir), "OVMF_CODE": str(firmware), "OVMF_CODE_INSECURE": str(firmware),
            "OVMF_VARS": str(firmware), "PREFLIGHT_KVM": str(kvm)}


def preflight(env: dict[str, str], script: Path = SCRIPT) -> subprocess.CompletedProcess[str]:
    return subprocess.run([BASH, str(script)], env=env, capture_output=True, text=True, check=False)


def test_the_repository_passes_with_every_host_tool(tmp_path: Path) -> None:
    out = preflight(runner(tmp_path))
    assert out.returncode == 0, out.stdout + out.stderr
    scanned = out.stdout.splitlines()[0].removeprefix("Scanned: ").split()
    assert sorted(scanned) == ["dogfood-diskless.sh", "dogfood-firmware.sh", "dogfood-install.sh", "dogfood-installer.sh"]


@pytest.mark.parametrize("tool", ["mcopy", "qemu-system-x86_64", "mkfs.vfat", "sfdisk"])
def test_a_missing_host_tool_fails(tmp_path: Path, tool: str) -> None:
    out = preflight(runner(tmp_path, missing=tool))
    assert out.returncode == 1
    assert f"::error title=boot-test preflight::{tool}: command not found" in out.stdout


@pytest.mark.parametrize("unset", ["OVMF_CODE", "OVMF_CODE_INSECURE", "OVMF_VARS", "PREFLIGHT_KVM"])
def test_missing_firmware_or_kvm_fails(tmp_path: Path, unset: str) -> None:
    env = runner(tmp_path)
    env[unset] = str(tmp_path / "absent")
    out = preflight(env)
    assert out.returncode == 1 and out.stdout.count("::error") == 1, out.stdout


def test_a_tool_new_to_the_dogfood_scripts_fails_until_listed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "scripts" / "ci").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "ci")
    (repo / "scripts" / "ci" / "boot-test.sh").write_text("bash scripts/dogfood-a.sh\n")
    (repo / "scripts" / "dogfood-a.sh").write_text('# zstd in a comment is not a call\nbash "${here}/dogfood-b.sh"\n')
    (repo / "scripts" / "dogfood-b.sh").write_text("zstd -d image.raw.zst\nmcopy -o x ::/y\n")
    out = preflight(runner(tmp_path), repo / "scripts" / "ci" / "dogfood-preflight.sh")
    assert out.returncode == 1
    assert out.stdout.splitlines()[0] == "Scanned: dogfood-a.sh dogfood-b.sh"
    errors = [line for line in out.stdout.splitlines() if line.startswith("::error")]
    assert len(errors) == 1 and "the dogfood scripts run zstd, which is in neither" in errors[0]
