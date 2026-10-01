"""Invariant tests for manual and script element sandbox runtimes.

In FSDK 26.08, runtime-minimal.bst no longer ships /bin/sh. Elements of
kind: manual or kind: script execute commands within their build-time
sandbox and must depend on base/base-stack.bst in build-depends to guarantee
a working shell environment.
"""

from __future__ import annotations

from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ELEMENTS_DIR = REPO_ROOT / "elements"


def test_manual_and_script_elements_depend_on_base_stack():
    """Ensure all manual/script elements have base/base-stack.bst in build-depends."""
    for bst_path in ELEMENTS_DIR.rglob("*.bst"):
        # Skip external junction declarations
        if bst_path.name == "freedesktop-sdk.bst":
            continue

        content = bst_path.read_text(encoding="utf-8")
        # Quick check for kind
        if "kind: manual" not in content and "kind: script" not in content:
            continue

        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            continue

        kind = data.get("kind")
        if kind in ("manual", "script"):
            build_depends = data.get("build-depends", [])
            dep_names = []
            for dep in build_depends:
                if isinstance(dep, str):
                    dep_names.append(dep)
                elif isinstance(dep, dict) and "filename" in dep:
                    dep_names.append(dep["filename"])

            assert "base/base-stack.bst" in dep_names, (
                f"{bst_path.relative_to(REPO_ROOT)} is kind: {kind} but does not include "
                f"base/base-stack.bst in build-depends"
            )


def test_compose_elements_declare_integration_explicitly():
    """Compose elements must say whether integration commands run.

    Shell-less compositions must set integrate: False (FSDK 26.08
    runtime-minimal has no /bin/sh). Compositions that ship a shell and need
    integration (the ld.so cache, hwdb) opt in with integrate: True.
    """
    for bst_path in ELEMENTS_DIR.rglob("*.bst"):
        if bst_path.name == "freedesktop-sdk.bst":
            continue

        content = bst_path.read_text(encoding="utf-8")
        if "kind: compose" not in content:
            continue

        data = yaml.safe_load(content)
        if not isinstance(data, dict) or data.get("kind") != "compose":
            continue

        config = data.get("config", {})
        assert config.get("integrate") in (True, False), (
            f"{bst_path.relative_to(REPO_ROOT)} is kind: compose but does not set "
            f"'integrate:' explicitly in config"
        )


def test_os_stack_uses_fsdk_base():
    """The OS payload is pure freedesktop-sdk: os-base.bst, no Flatcar imports."""
    os_stack = ELEMENTS_DIR / "bluefin-server" / "os-stack.bst"
    depends = yaml.safe_load(os_stack.read_text(encoding="utf-8")).get("depends", [])
    os_base = ELEMENTS_DIR / "bluefin-server" / "os-base.bst"
    base_depends = yaml.safe_load(os_base.read_text(encoding="utf-8")).get("depends", [])

    assert "bluefin-server/os-base.bst" in depends
    assert "freedesktop-sdk.bst:components/systemd.bst" in base_depends
    assert "bluefin-server/kernel-modules.bst" in base_depends
    for dep in depends + base_depends:
        assert not dep.startswith("flatcar/"), (
            f"OS payload must not import Flatcar binaries ({dep})"
        )



def test_os_countme_depends_on_curl_and_jq():
    """os-countme.bst must ship curl and jq through the freedesktop-sdk junction.

    Regression test for projectbluefin/server#96: the curl dependency was
    inferred rather than verified, so a wrong path would fail to resolve and
    the minimal image (which ships neither curl nor jq) would not build.
    Confirmed that the pinned freedesktop-sdk ref (freedesktop-sdk-26.08.0,
    elements/freedesktop-sdk.bst) ships both elements/components/curl.bst and
    elements/components/jq.bst, so the dependency must stay on this exact path.
    """
    countme = ELEMENTS_DIR / "bluefin-server" / "os-countme.bst"
    data = yaml.safe_load(countme.read_text(encoding="utf-8"))
    depends = data.get("depends", [])

    assert "freedesktop-sdk.bst:components/curl.bst" in depends, (
        "os-countme.bst must include freedesktop-sdk.bst:components/curl.bst "
        "(projectbluefin/server#96)"
    )
    assert "freedesktop-sdk.bst:components/jq.bst" in depends, (
        "os-countme.bst must include freedesktop-sdk.bst:components/jq.bst "
        "(projectbluefin/server#96)"
    )


def _build_depends(element):
    data = yaml.safe_load((ELEMENTS_DIR / element).read_text(encoding="utf-8"))
    return {d if isinstance(d, str) else d["filename"] for d in data.get("build-depends", [])}


def test_sbom_lists_every_published_sysext_and_its_payload():
    """collect_manifest follows only runtime dependencies of what it lists.

    A sysext only build-depends on the upstream payload it stages, so the
    SBOM must list the sysext (its own local sources) and the payload.
    """
    sysexts = {d for d in _build_depends("oci/bluefin-server-image.bst") if d.endswith("-sysext.bst")}
    sbom = _build_depends("oci/bluefin-server-sbom.bst")

    assert sysexts
    assert sysexts <= sbom, f"SBOM misses {sorted(sysexts - sbom)}"
    assert {
        "k0s/k0s-bin.bst",
        "kubeadm/kubeadm-bin.bst",
        "zfs/openzfs.bst",
        "nvidia/nvidia-open-595.bst",
        "nvidia/nvidia-container-toolkit.bst",
    } <= sbom

