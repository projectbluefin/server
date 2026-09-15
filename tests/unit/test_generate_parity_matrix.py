"""Tests for the Flatcar-to-FSDK parity matrix generator.

The generator resolves each in-scope component from the Flatcar SBOM
(`pkg:gentoo/<category/name>` keys) with the raw package manifest as a
fallback, so the fixtures below supply versions through the SBOM the same way
the real release does.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "arch" / "parity" / "generate-parity-matrix.py"


def _load():
    spec = importlib.util.spec_from_file_location("generate_parity", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["generate_parity"] = mod
    spec.loader.exec_module(mod)
    return mod


def _sbom_entry(category, name, version):
    return {"name": name, "versionInfo": version,
            "externalRefs": [{"externalReference":
                {"referenceLocator": f"pkg:gentoo/{category}/{name}@{version}"}}]}


def _install_env(mod, tmp_path, packages, sbom):
    """Wire the module at a minimal Flatcar release + FSDK snapshot on disk."""
    release = tmp_path / "flatcar" / "4593.2.5"
    release.mkdir(parents=True)
    (release / "flatcar_production_image_packages.txt").write_text(packages)
    (release / "version.txt").write_text("FLATCAR_VERSION=4593.2.5\n")
    (release / "flatcar_production_image_sbom.json").write_text(json.dumps(
        {"packages": sbom}))
    (tmp_path / "fsdk-versions.json").write_text(json.dumps({
        "systemd": {"version": "261.2", "element_path": "components/systemd.bst",
                    "source": "include/systemd.yml"},
        "coreutils": {"version": "9.11", "element_path": "bootstrap/coreutils.bst",
                      "source": "bootstrap/coreutils-source.yml"},
        "kmod": {"version": "34.2", "element_path": "components/kmod.bst",
                 "source": "components/kmod.bst"},
        "gnupg": {"version": "2.4.9", "element_path": "components/gnupg.bst",
                  "source": "components/gnupg.bst"},
        "xfsprogs": {"version": "7.1.1", "element_path": "components/xfsprogs.bst",
                     "source": "components/xfsprogs.bst"},
        "podman": {"version": "6.1.0", "element_path": "components/podman.bst",
                   "source": "components/podman.bst"},
    }))
    mod.FLATCAR_DIR = release.parent
    mod.FSDK_VERSIONS = tmp_path / "fsdk-versions.json"
    mod.MD_OUT = tmp_path / "matrix.md"
    mod.CSV_OUT = tmp_path / "matrix.csv"


@pytest.fixture
def env(tmp_path):
    mod = _load()
    _install_env(mod, tmp_path, "", [
        _sbom_entry("sys-apps", "systemd", "257.9"),
        _sbom_entry("sys-apps", "coreutils", "9.8-r1"),
        _sbom_entry("sys-apps", "kmod", "34.2"),
        _sbom_entry("app-crypt", "gnupg", "2.5.16"),
        _sbom_entry("sys-fs", "xfsprogs", "6.16.0"),
    ])
    return mod


def _gap_rows(csv_text):
    import csv
    return {row["component"]: row["gap"]
            for row in csv.DictReader(csv_text.splitlines())}


def test_matrix_generated(env):
    env.main()
    md = env.MD_OUT.read_text()
    assert "Flatcar 4593.2.5 vs freedesktop-sdk 26.08" in md
    # systemd, coreutils, kmod, gnupg, xfsprogs + kernel + podman special rows
    for component in ("systemd", "coreutils", "kmod", "gnupg",
                      "xfsprogs", "kernel", "podman"):
        assert f"| {component} |" in md


def test_gap_classification(env):
    env.main()
    gaps = _gap_rows(env.CSV_OUT.read_text())
    assert gaps["systemd"] == "fsdk-newer"    # 257.9 < 261.2
    assert gaps["coreutils"] == "fsdk-newer"   # 9.8 < 9.11
    assert gaps["gnupg"] == "flatcar-newer"    # 2.5.16 > 2.4.9
    assert gaps["kmod"] == "none"              # 34.2 == 34.2
    assert gaps["xfsprogs"] == "fsdk-newer"    # 6.16.0 < 7.1.1
    assert gaps["kernel"] == "n/a"
    assert gaps["podman"] == "imported"


def test_missing_flatcar_version_is_skipped(tmp_path):
    mod = _load()
    # coreutils absent from the SBOM -> omitted; systemd stays.
    _install_env(mod, tmp_path, "", [
        _sbom_entry("sys-apps", "systemd", "257.9"),
    ])
    mod.main()
    md = mod.MD_OUT.read_text()
    assert "| systemd |" in md
    assert "| coreutils |" not in md
