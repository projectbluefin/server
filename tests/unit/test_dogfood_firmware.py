"""scripts/dogfood-firmware.sh: the one OVMF firmware lookup the single-VM
QEMU checks source. An environment variable wins; with none set and no
firmware at the usual paths the lookup fails and names the variable."""


import subprocess
from pathlib import Path

import pytest

FIRMWARE = Path(__file__).resolve().parents[2] / "scripts" / "dogfood-firmware.sh"
LOOKUPS = {"ovmf_code": "OVMF_CODE", "ovmf_code_insecure": "OVMF_CODE_INSECURE", "ovmf_vars": "OVMF_VARS"}


def lookup(function: str, env: dict[str, str], root: Path) -> subprocess.CompletedProcess[str]:
    # Point the candidate paths at a directory the test controls.
    helper = FIRMWARE.read_text(encoding="utf-8").replace("/usr/share/", f"{root}/")
    return subprocess.run(["bash", "-c", f"{helper}\n{function}"],
                          env={"PATH": "/usr/bin:/bin", **env}, capture_output=True, text=True, check=False)


@pytest.mark.parametrize(("function", "variable"), LOOKUPS.items())
def test_the_environment_variable_wins(function: str, variable: str, tmp_path: Path) -> None:
    out = lookup(function, {variable: "/custom/firmware.fd"}, tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout == "/custom/firmware.fd\n"


@pytest.mark.parametrize(("function", "variable"), LOOKUPS.items())
def test_no_firmware_fails_and_names_the_variable(function: str, variable: str, tmp_path: Path) -> None:
    out = lookup(function, {}, tmp_path)
    assert out.returncode == 1
    assert out.stdout == ""
    assert f"(set {variable})" in out.stderr


@pytest.mark.parametrize(("function", "first", "second"), [
    ("ovmf_code", "OVMF/OVMF_CODE_4M.secboot.fd", "edk2/x64/OVMF_CODE.secboot.4m.fd"),
    ("ovmf_code_insecure", "OVMF/OVMF_CODE_4M.fd", "edk2/x64/OVMF_CODE.4m.fd"),
    ("ovmf_vars", "OVMF/OVMF_VARS_4M.fd", "edk2/x64/OVMF_VARS.4m.fd"),
])
def test_the_first_existing_candidate_is_chosen(function: str, first: str, second: str, tmp_path: Path) -> None:
    for name in (first, second):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(b"")
    out = lookup(function, {}, tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout == f"{tmp_path}/{first}\n"
