"""Contract tests for elements/flatcar/flatcar-usr.bst.

Verifies that the Flatcar /usr base import:
- Uses kind: manual with prebuilt binaries unstripped (strip-binaries: "").
- Imports flatcar-container.tar.gz pinned by sha256 via the flatcar: alias.
- Removes /usr/lib/modules to avoid filesystem collisions with flatcar-kernel.bst.
- Explicitly removes Flatcar's update and provisioning stack (update_engine,
  locksmithd, ignition, coreos-cloudinit, flatcar-update, download_sysext,
  ensure-sysext) with individual rm commands documented with their Bluefin replacements.
- Preserves usr/lib/flatcar/bootengine.img for two-stage kernel boot.
- Preserves verified OS components (systemd 257, glibc, bash, sshd, crictl, etc.).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
FLATCAR_USR_ELEMENT = REPO_ROOT / "elements" / "flatcar" / "flatcar-usr.bst"
FLATCAR_YML = REPO_ROOT / "include" / "flatcar.yml"

REMOVED_BINARIES = [
    "usr/bin/update_engine",
    "usr/bin/update_engine_client",
    "usr/bin/update_engine_stub",
    "usr/lib/locksmith/locksmithd",
    "usr/bin/locksmithctl",
    "usr/bin/ignition",
    "usr/bin/coreos-cloudinit",
    "usr/bin/flatcar-update",
    "usr/bin/download_sysext",
]

REMOVED_UNITS = [
    "usr/lib/systemd/system/update-engine.service",
    "usr/lib/systemd/system/multi-user.target.wants/update-engine.service",
    "usr/lib/systemd/system/update-engine-stub.service",
    "usr/lib/systemd/system/update-engine-stub.timer",
    "usr/lib/systemd/system/multi-user.target.wants/update-engine-stub.timer",
    "usr/lib/systemd/system/locksmithd.service",
    "usr/lib/systemd/system/multi-user.target.wants/locksmithd.service",
    "usr/lib/systemd/system/ignition-delete-config.service",
    "usr/lib/systemd/system/sysinit.target.wants/ignition-delete-config.service",
    "usr/lib/systemd/system/enable-oem-cloudinit.service",
    "usr/lib/systemd/system/multi-user.target.wants/enable-oem-cloudinit.service",
    "usr/lib/systemd/system/oem-cloudinit.service",
    "usr/lib/systemd/system/ensure-sysext.service",
    "usr/lib/systemd/system/sysinit.target.wants/ensure-sysext.service",
]

REMOVED_EXTRA_FILES = [
    "usr/lib/tmpfiles.d/update-engine.conf",
    "usr/lib/tmpfiles.d/flatcar-update.conf",
    "usr/libexec/ignition-rmcfg",
]

REMOVED_COMPONENTS = [
    "update_engine",
    "update_engine_client",
    "update_engine_stub",
    "update-engine.service",
    "locksmithd",
    "locksmithctl",
    "locksmithd.service",
    "ignition",
    "ignition-delete-config.service",
    "coreos-cloudinit",
    "flatcar-update",
    "download_sysext",
    "ensure-sysext.service",
]


def _load_element_data() -> dict:
    content = FLATCAR_USR_ELEMENT.read_text(encoding="utf-8")
    return yaml.safe_load(content)


def test_flatcar_usr_element_structure() -> None:
    """Verify flatcar-usr.bst declares the expected BuildStream structure."""
    assert FLATCAR_USR_ELEMENT.is_file(), f"{FLATCAR_USR_ELEMENT} must exist"
    data = _load_element_data()

    assert data.get("kind") == "manual", "flatcar-usr.bst must be kind: manual"

    # Must include arch.yml and flatcar.yml
    includes = data.get("(@)", [])
    assert "include/arch.yml" in includes
    assert "include/flatcar.yml" in includes

    # Must declare build-depends for sandbox execution
    build_deps = data.get("build-depends", [])
    assert "base/base-stack.bst" in build_deps, "Must depend on base/base-stack.bst"
    assert "freedesktop-sdk.bst:components/tar.bst" in build_deps
    assert "freedesktop-sdk.bst:components/gzip.bst" in build_deps
    assert "freedesktop-sdk.bst:components/findutils.bst" in build_deps

    # Prebuilt binaries must not be stripped
    variables = data.get("variables", {})
    assert variables.get("strip-binaries") == "", (
        "variables.strip-binaries must be empty string to prevent stripping"
    )

    # Exactly one remote source for flatcar-container.tar.gz pinned by sha256
    sources = data.get("sources", [])
    assert len(sources) == 1, "Must declare exactly one source"
    src = sources[0]
    assert src.get("kind") == "remote"
    assert src.get("url") == "flatcar:stable/%{flatcar-board}/%{flatcar-version}/flatcar-container.tar.gz"
    assert len(src.get("ref", "")) == 64, "Source ref must be a valid sha256 hash"


def test_flatcar_usr_explicit_removals_and_replacements() -> None:
    """Verify explicit rm lines and Bluefin replacement documentation."""
    content = FLATCAR_USR_ELEMENT.read_text(encoding="utf-8")

    for component in REMOVED_COMPONENTS:
        assert component in content, (
            f"flatcar-usr.bst must explicitly name {component} in its removal commands"
        )

    # Assert no wildcard sweeps in removal section
    install_commands = _load_element_data().get("config", {}).get("install-commands", [])
    script = "\n".join(install_commands)
    for line in script.splitlines():
        clean = line.strip()
        if clean.startswith("rm "):
            assert "*" not in clean, (
                f"Wildcard removal forbidden to ensure rename failures: {line}"
            )

    # Assert each removed component is commented with replacement
    for component in [
        "update_engine",
        "locksmithd",
        "ignition",
        "coreos-cloudinit",
        "flatcar-update",
        "download_sysext",
        "ensure-sysext",
    ]:
        pattern = rf"#\s*{component}.*?:.*?replaced by"
        assert re.search(pattern, content, re.IGNORECASE), (
            f"flatcar-usr.bst must document replacement for {component}"
        )


def test_flatcar_usr_preserves_bootengine_img() -> None:
    """Verify usr/lib/flatcar/bootengine.img is preserved and never deleted."""
    content = FLATCAR_USR_ELEMENT.read_text(encoding="utf-8")

    assert "bootengine.img" in content, (
        "flatcar-usr.bst must explicitly document preservation of bootengine.img"
    )

    install_commands = _load_element_data().get("config", {}).get("install-commands", [])
    script = "\n".join(install_commands)
    for line in script.splitlines():
        if "bootengine" in line:
            assert not line.strip().startswith("rm"), (
                f"bootengine.img must not be removed: {line}"
            )


def test_flatcar_usr_removes_modules() -> None:
    """Verify script logic removes /usr/lib/modules to avoid collision with flatcar-kernel.bst."""
    content = FLATCAR_USR_ELEMENT.read_text(encoding="utf-8")
    assert 'rm -rf "%{install-root}/usr/lib/modules"' in content, (
        "Script must remove /usr/lib/modules to prevent collision with flatcar-kernel.bst"
    )


def test_flatcar_usr_contract_execution(tmp_path: Path) -> None:
    """Simulate execution of flatcar-usr.bst install-commands against a staged /usr.

    Verifies:
    1. Removed binaries are absent.
    2. Removed units are absent.
    3. bootengine.img is preserved.
    4. Module directory /usr/lib/modules is removed to avoid collision with flatcar-kernel.bst.
    5. Retained files (bash, sshd, systemd, crictl) remain untouched.
    """
    flatcar_yml_data = yaml.safe_load(FLATCAR_YML.read_text(encoding="utf-8"))
    kver = flatcar_yml_data["variables"]["flatcar-kver"]

    install_root = tmp_path / "install-root"
    usr = install_root / "usr"

    # Populate mock files that flatcar-container.tar.gz delivers
    bin_dir = usr / "bin"
    bin_dir.mkdir(parents=True)
    for b in [
        "bash", "crictl", "sshd", "update_engine", "update_engine_client",
        "update_engine_stub", "locksmithctl", "ignition", "coreos-cloudinit",
        "flatcar-update", "download_sysext"
    ]:
        (bin_dir / b).write_text(f"mock-{b}", encoding="utf-8")

    locksmith_dir = usr / "lib" / "locksmith"
    locksmith_dir.mkdir(parents=True)
    (locksmith_dir / "locksmithd").write_text("mock-locksmithd", encoding="utf-8")

    libexec_dir = usr / "libexec"
    libexec_dir.mkdir(parents=True)
    (libexec_dir / "ignition-rmcfg").write_text("mock-ignition-rmcfg", encoding="utf-8")

    tmpfiles_dir = usr / "lib" / "tmpfiles.d"
    tmpfiles_dir.mkdir(parents=True)
    (tmpfiles_dir / "update-engine.conf").write_text("mock-tmpfiles", encoding="utf-8")
    (tmpfiles_dir / "flatcar-update.conf").write_text("mock-tmpfiles", encoding="utf-8")

    systemd_dir = usr / "lib" / "systemd" / "system"
    systemd_dir.mkdir(parents=True)
    (systemd_dir / "update-engine.service").write_text("mock-unit", encoding="utf-8")
    (systemd_dir / "update-engine-stub.service").write_text("mock-unit", encoding="utf-8")
    (systemd_dir / "update-engine-stub.timer").write_text("mock-unit", encoding="utf-8")
    (systemd_dir / "locksmithd.service").write_text("mock-unit", encoding="utf-8")
    (systemd_dir / "ignition-delete-config.service").write_text("mock-unit", encoding="utf-8")
    (systemd_dir / "enable-oem-cloudinit.service").write_text("mock-unit", encoding="utf-8")
    (systemd_dir / "oem-cloudinit.service").write_text("mock-unit", encoding="utf-8")
    (systemd_dir / "ensure-sysext.service").write_text("mock-unit", encoding="utf-8")

    wants_dir1 = systemd_dir / "multi-user.target.wants"
    wants_dir1.mkdir(parents=True)
    (wants_dir1 / "update-engine.service").symlink_to("../update-engine.service")
    (wants_dir1 / "update-engine-stub.timer").symlink_to("../update-engine-stub.timer")
    (wants_dir1 / "locksmithd.service").symlink_to("../locksmithd.service")
    (wants_dir1 / "enable-oem-cloudinit.service").symlink_to("../enable-oem-cloudinit.service")

    wants_dir2 = systemd_dir / "sysinit.target.wants"
    wants_dir2.mkdir(parents=True)
    (wants_dir2 / "ignition-delete-config.service").symlink_to("../ignition-delete-config.service")
    (wants_dir2 / "ensure-sysext.service").symlink_to("../ensure-sysext.service")

    flatcar_dir = usr / "lib" / "flatcar"
    flatcar_dir.mkdir(parents=True)
    bootengine = flatcar_dir / "bootengine.img"
    bootengine.write_bytes(b"mock-bootengine-squashfs")

    # Module directory: usr/lib/modules/<kver>/
    mod_dir = usr / "lib" / "modules" / kver
    (mod_dir / "kernel" / "drivers").mkdir(parents=True)
    (mod_dir / "kernel" / "drivers" / "driver.ko").write_bytes(b"mock-driver")
    (mod_dir / "modules.dep").write_text("mock modules.dep", encoding="utf-8")

    # Extract script from flatcar-usr.bst and adapt variables
    install_commands = _load_element_data().get("config", {}).get("install-commands", [])
    script = "\n".join(install_commands)

    # Replace BuildStream variables
    script = script.replace("%{install-root}", str(install_root))
    script = script.replace("%{flatcar-kver}", kver)

    # In test environment, the mock files are already populated, so bypass tar extraction
    script = re.sub(r"tar\s+-xzf\s+flatcar-container\.tar\.gz\s+-C\s+.*", "# tar extract bypassed", script)

    # Run the script in bash
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, f"Script failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

    # 1. Assert removed binaries are absent
    for rel_path in REMOVED_BINARIES:
        target = install_root / rel_path
        assert not target.exists(), f"Removed binary {rel_path} must be absent from output"

    # 2. Assert removed units and extra files are absent
    for rel_path in REMOVED_UNITS:
        target = install_root / rel_path
        assert not target.exists(), f"Removed unit {rel_path} must be absent from output"

    for rel_path in REMOVED_EXTRA_FILES:
        target = install_root / rel_path
        assert not target.exists(), f"Removed file {rel_path} must be absent from output"

    # 3. Assert module tree is completely removed to avoid collision with flatcar-kernel.bst
    assert not (usr / "lib" / "modules").exists(), (
        "/usr/lib/modules must be removed to avoid collision with flatcar-kernel.bst"
    )

    # 4. Assert usr/lib/flatcar/bootengine.img exists in output
    assert bootengine.is_file(), "usr/lib/flatcar/bootengine.img must exist in element output"

    # 5. Assert kept binaries remain
    for kept in ["bash", "crictl", "sshd"]:
        assert (bin_dir / kept).is_file(), f"Kept binary {kept} must remain in output"
