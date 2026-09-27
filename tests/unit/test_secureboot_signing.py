"""Contracts for the post-build Secure Boot signing pass (projectbluefin/server#257).

The signing script runs outside BuildStream and reaches into artifacts the
installer element produces, so the paths and ordering both sides rely on are
pinned here rather than discovered at release time.
"""

from __future__ import annotations

import re
import subprocess
import shutil
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SIGN_SCRIPT = REPO_ROOT / "scripts" / "sign-secureboot-artifacts.sh"
INSTALLER_ELEMENT = REPO_ROOT / "elements" / "oci" / "bluefin-server-installer.bst"
BUILD_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build.yml"
SKILL = REPO_ROOT / "docs" / "skills" / "secure-boot-signing.md"
SKILL_INDEX = REPO_ROOT / "docs" / "skills" / "index.md"
AGENTS = REPO_ROOT / "AGENTS.md"

SIGN_STEP_NAME = "Sign Secure Boot artifacts"
TEST_ARTIFACT_STEP_NAME = "Upload installer test artifacts"
MANIFEST_STEP_NAME = "Sign release SHA256SUMS manifest"
SECRETS = ("SECUREBOOT_SIGNING_KEY", "SECUREBOOT_SIGNING_CERT")


def _script_var(name: str) -> str:
    match = re.search(rf'^{name}="([^"]+)"$', SIGN_SCRIPT.read_text(), flags=re.M)
    assert match, f"{name} must be assigned once at column 0 in the signing script"
    return match.group(1)


def _build_steps() -> list[dict]:
    workflow = yaml.safe_load(BUILD_WORKFLOW.read_text())
    return workflow["jobs"]["build"]["steps"]


def _step(name: str) -> dict:
    steps = [s for s in _build_steps() if s.get("name") == name]
    assert len(steps) == 1, f"build job must have exactly one step named {name!r}"
    return steps[0]


def test_script_is_executable_and_strict() -> None:
    assert SIGN_SCRIPT.stat().st_mode & 0o111, "signing script must be executable"
    text = SIGN_SCRIPT.read_text()
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_script_passes_shellcheck() -> None:
    subprocess.run(["shellcheck", str(SIGN_SCRIPT)], check=True)


def test_script_overlays_the_paths_the_installer_element_stages() -> None:
    element = INSTALLER_ELEMENT.read_text()
    target_uki = _script_var("TARGET_UKI_PATH")
    sd_boot = _script_var("SD_BOOT_PATH")
    installer_uki = _script_var("INSTALLER_UKI_ESP_PATH")

    # The element copies the target UKI into the initrd rootfs at /layer/<path>
    # and the wrapper consumes it from /<path>; both must agree with the overlay.
    assert f"/layer/{target_uki}" in element
    assert f"--kernel=/{target_uki}" in element
    # bootctl install takes systemd-boot from the live initrd's systemd tree.
    assert sd_boot == "usr/lib/systemd/boot/efi/systemd-bootx64.efi"
    # The installer media UKI the script rebuilds is the one the element writes.
    assert f"--output=/layer/boot/efi/{installer_uki}" in element


def test_script_rebuilds_installer_uki_from_its_own_sections() -> None:
    text = SIGN_SCRIPT.read_text()
    for section in (".linux", ".cmdline", ".osrel"):
        assert f"dump_section {section} " in text, f"{section} must be reused, not restated"
    # No hardcoded installer command line: the element is the single source.
    assert "system-install.target" not in text
    assert '--os-release="@' in text


def test_script_strips_flatcar_signature_before_resigning_pxe_kernel() -> None:
    text = SIGN_SCRIPT.read_text()
    assert "sbattach --remove" in text
    assert text.index("sbattach --remove") < text.index('sign_pe "${WORK}/vmlinuz.unsigned"')


def test_script_appends_root_owned_overlay_instead_of_repacking() -> None:
    text = SIGN_SCRIPT.read_text()
    assert "--owner=root:root" in text
    assert re.search(r'cat "\$\{PXE_INITRD\}" "\$\{WORK\}/overlay\.cpio\.gz"', text)


def test_script_locates_esp_by_partition_type() -> None:
    text = SIGN_SCRIPT.read_text()
    assert _script_var("ESP_PARTTYPE") == "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
    assert "partitions[0]" not in text, "ESP must be found by type, not index"


def test_script_publishes_certificate() -> None:
    text = SIGN_SCRIPT.read_text()
    base = _script_var("CERT_BASENAME")
    assert base == "bluefin-server-secureboot"
    assert f'"${{DIST}}/${{CERT_BASENAME}}.der"' in text
    assert f'"${{DIST}}/${{CERT_BASENAME}}.pem"' in text
    assert f'"::${{CERT_BASENAME}}.der"' in text, "cert must land on the installer media ESP"


def test_workflow_signs_on_main_only_with_step_scoped_secrets() -> None:
    step = _step(SIGN_STEP_NAME)
    assert step["if"] == "github.ref == 'refs/heads/main'"
    for secret in SECRETS:
        assert step["env"][secret] == f"${{{{ secrets.{secret} }}}}"
    # The secret must not leak to PR-controlled steps via a job-level env.
    workflow = yaml.safe_load(BUILD_WORKFLOW.read_text())
    assert "env" not in workflow["jobs"]["build"]
    assert "env" not in workflow
    run = step["run"]
    assert "scripts/sign-secureboot-artifacts.sh" in run
    assert "exit 0" in run, "unset secrets must skip signing, not fail the build"
    for pkg in ("sbsigntool", "systemd-ukify", "mtools", "cpio"):
        assert pkg in run


def test_workflow_signs_before_test_upload_and_before_manifest() -> None:
    names = [s.get("name") for s in _build_steps()]
    assert names.index(SIGN_STEP_NAME) < names.index(TEST_ARTIFACT_STEP_NAME)
    assert names.index(SIGN_STEP_NAME) < names.index(MANIFEST_STEP_NAME)


def test_workflow_ships_certificate_with_release_assets() -> None:
    run = _step(MANIFEST_STEP_NAME)["run"]
    assert "bluefin-server-secureboot.der" in run
    assert "bluefin-server-secureboot.pem" in run


def test_skill_is_routed() -> None:
    assert SKILL.exists()
    assert "secure-boot-signing.md" in SKILL_INDEX.read_text()
    assert "docs/skills/secure-boot-signing.md" in AGENTS.read_text()
    for secret in SECRETS:
        assert secret in SKILL.read_text()
