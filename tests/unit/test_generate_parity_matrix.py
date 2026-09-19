"""Tests for the Flatcar-to-FSDK parity matrix generator (scripts/generate-parity-matrix.py)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "generate-parity-matrix.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_parity_matrix", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["generate_parity_matrix"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def generator():
    return _load_module()


def test_compare_versions(generator):
    assert generator.compare_versions("257.9", "261.2") == -1  # fsdk newer
    assert generator.compare_versions("2.41-r6", "2.44-23") == -1  # fsdk newer
    assert generator.compare_versions("2.5.16", "2.4.9") == 1  # flatcar newer
    assert generator.compare_versions("34.2", "34.2") == 0  # none
    assert generator.compare_versions("5.3_p3-r3", "5.3-16") == 0  # both 5.3
    assert generator.compare_versions(None, "1.0") is None


def test_parse_packages_manifest(generator):
    manifest = """
# Flatcar package manifest
sys-apps/systemd-257.9::portage-stable
sys-libs/glibc-2.41-r6::portage-stable
app-shells/bash-5.3_p3-r3::portage-stable
app-misc/ca-certificates-3.126::coreos-overlay
"""
    pkgs = generator.parse_packages_manifest(manifest)
    assert pkgs["sys-apps/systemd"] == "257.9"
    assert pkgs["sys-libs/glibc"] == "2.41-r6"
    assert pkgs["app-shells/bash"] == "5.3_p3-r3"
    assert pkgs["app-misc/ca-certificates"] == "3.126"


def test_parse_spdx_sbom(generator):
    sbom = {
        "packages": [
            {
                "name": "systemd",
                "versionInfo": "257.9",
                "externalRefs": [
                    {
                        "referenceLocator": "pkg:gentoo/sys-apps/systemd@257.9",
                        "externalReference": {"referenceLocator": "pkg:gentoo/sys-apps/systemd@257.9"},
                    }
                ],
            },
            {
                "name": "glibc",
                "versionInfo": "2.41-r6",
                "externalRefs": [
                    {"referenceLocator": "pkg:gentoo/sys-libs/glibc@2.41-r6"}
                ],
            },
        ]
    }
    pkgs = generator.parse_spdx_sbom(json.dumps(sbom))
    assert pkgs["sys-apps/systemd"] == "257.9"
    assert pkgs["sys-libs/glibc"] == "2.41-r6"


def test_matrix_generation_from_flatcar_dir(generator, tmp_path):
    mock_dir = tmp_path / "flatcar" / "4593.2.5"
    mock_dir.mkdir(parents=True)
    (mock_dir / "version.txt").write_text("FLATCAR_VERSION=4593.2.5\nFLATCAR_BUILD_ID=\"2026-08-11-2350\"\n")
    (mock_dir / "flatcar_production_image_packages.txt").write_text("""
sys-apps/systemd-257.9::portage-stable
sys-libs/glibc-2.41-r6::portage-stable
sys-apps/coreutils-9.8-r1::portage-stable
app-shells/bash-5.3_p3-r3::portage-stable
sys-apps/kmod-34.2::portage-stable
app-crypt/gnupg-2.5.16::portage-stable
app-misc/ca-certificates-3.126::coreos-overlay
sys-fs/xfsprogs-6.16.0::portage-stable
""")
    (mock_dir / "flatcar-podman_packages.txt").write_text("""
app-containers/podman-5.5.2::portage-stable
""")

    flatcar_ver, pkgs, sources = generator.collect_flatcar_versions(flatcar_dir=mock_dir)
    assert flatcar_ver == "4593.2.5"
    assert pkgs["sys-apps/systemd"] == "257.9"
    assert pkgs["app-containers/podman"] == "5.5.2"

    rows = generator.build_matrix_rows(flatcar_ver, pkgs, sources, strict=False)
    row_map = {r["component"]: r for r in rows}

    # Kernel special row
    assert "kernel" in row_map
    assert row_map["kernel"]["gap"] == "n/a"
    assert row_map["kernel"]["priority"] == "load-bearing"

    # Systemd & glibc
    assert row_map["systemd"]["gap"] == "fsdk-newer"
    assert row_map["systemd"]["priority"] == "load-bearing"
    assert row_map["glibc"]["gap"] == "fsdk-newer"
    assert row_map["glibc"]["priority"] == "load-bearing"

    # Gnupg & kmod & bash
    assert row_map["gnupg"]["gap"] == "flatcar-newer"
    assert row_map["kmod"]["gap"] == "none"
    assert row_map["bash"]["gap"] == "none"

    # Podman & ca-certificates
    assert row_map["podman"]["gap"] == "fsdk-newer"
    assert row_map["podman"]["priority"] == "deferred"
    assert row_map["ca-certificates"]["gap"] == "different-scheme"

    # Render markdown
    output_md = tmp_path / "flatcar-parity-matrix.md"
    rendered = generator.render_markdown(flatcar_ver, "26.08.0", rows)
    output_md.write_text(rendered, encoding="utf-8")

    assert "name: flatcar-parity-matrix" in rendered
    assert "Flatcar 4593.2.5 vs freedesktop-sdk 26.08" in rendered
    assert "| systemd | 257.9 | 261.2 | fsdk-newer | `components/systemd.bst` | load-bearing |" in rendered
    assert "| glibc | 2.41-r6 | 2.44-23 | fsdk-newer | `bootstrap/glibc.bst` | load-bearing |" in rendered


def test_checked_in_matrix_is_up_to_date(generator):
    """Ensure the committed docs/skills/flatcar-parity-matrix.md matches generator output."""
    output_path = REPO_ROOT / "docs" / "skills" / "flatcar-parity-matrix.md"
    assert output_path.is_file(), "docs/skills/flatcar-parity-matrix.md must exist"

    pinned_ver = generator.get_flatcar_pinned_version()
    fsdk_ver = generator.check_fsdk_junction_ref()
    try:
        flatcar_version, packages, sources = generator.collect_flatcar_versions(flatcar_version=pinned_ver)
    except SystemExit as exc:
        pytest.skip(f"Flatcar CDN/artifacts unavailable offline: {exc}")
    rows = generator.build_matrix_rows(flatcar_version, packages, sources)
    expected_content = generator.render_markdown(flatcar_version, fsdk_ver, rows)

    actual_content = output_path.read_text(encoding="utf-8")
    assert actual_content == expected_content, "Matrix on disk has drifted from generator output."


def test_strict_mode_fails_on_missing_atoms(generator, tmp_path):
    """Ensure build_matrix_rows in strict mode fails fast when in-scope atoms are missing."""
    mock_dir = tmp_path / "flatcar" / "4593.2.5"
    mock_dir.mkdir(parents=True)
    (mock_dir / "version.txt").write_text("FLATCAR_VERSION=4593.2.5\nFLATCAR_BUILD_ID=\"2026-08-11-2350\"\n")
    (mock_dir / "flatcar_production_image_packages.txt").write_text("sys-apps/systemd-257.9::portage-stable\n")
    (mock_dir / "flatcar-podman_packages.txt").write_text("")

    flatcar_ver, pkgs, sources = generator.collect_flatcar_versions(flatcar_dir=mock_dir)
    with pytest.raises(SystemExit) as exc_info:
        generator.build_matrix_rows(flatcar_ver, pkgs, sources, strict=True)
    assert "in-scope components missing from Flatcar manifests" in str(exc_info.value)
