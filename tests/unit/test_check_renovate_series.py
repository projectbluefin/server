"""Unit coverage for .github/scripts/check-renovate-series.py.

The script guards a silent failure: when a junction moves to a new release
series and renovate.json's extractVersion does not, Renovate matches no tag
and simply reports no updates. The junction then stops receiving bumps with
nothing in any log to say so.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "check-renovate-series.py"

# The script's filename is not a valid module name, so load it by path —
# same approach as tests/unit/test_check_k0s_version.py.
_spec = importlib.util.spec_from_file_location("check_renovate_series", SCRIPT)
check_renovate_series = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_renovate_series)


def run_against(tmp_path, renovate, junctions):
    """Run the script with ROOT redirected at a throwaway tree."""
    (tmp_path / ".github" / "scripts").mkdir(parents=True)
    (tmp_path / "elements").mkdir()
    (tmp_path / "renovate.json").write_text(json.dumps(renovate))
    for name, body in junctions.items():
        (tmp_path / "elements" / name).write_text(body)
    script_copy = tmp_path / ".github" / "scripts" / SCRIPT.name
    script_copy.write_text(SCRIPT.read_text())
    return subprocess.run(
        [sys.executable, str(script_copy)], capture_output=True, text=True
    )


FSDK = "https://gitlab.com/freedesktop-sdk/freedesktop-sdk.git"
GBM = "https://gitlab.gnome.org/GNOME/gnome-build-meta.git"


def rule(dep, extract):
    return {
        "matchDatasources": ["git-refs"],
        "matchPackageNames": [dep],
        "extractVersion": extract,
        "versioning": "semver",
    }


def junction(track):
    return f"kind: junction\n\nsources:\n- kind: git_repo\n  track: {track}\n  ref: x\n"


BOTH_JUNCTIONS = {
    "freedesktop-sdk.bst": junction("freedesktop-sdk-26.08*"),
    "gnome-build-meta.bst": junction("gnome-50"),
}


def test_passes_when_series_agree(tmp_path):
    result = run_against(
        tmp_path,
        {
            "packageRules": [
                rule(FSDK, r"^freedesktop-sdk-(?<version>26\.08\.[0-9]+)$"),
                rule(GBM, r"^(?<version>50\.[0-9]+)$"),
            ]
        },
        BOTH_JUNCTIONS,
    )
    assert result.returncode == 0, result.stderr
    assert "OK: 2" in result.stdout


def test_fails_on_the_real_regression(tmp_path):
    """The shipped bug: junction on 26.08, Renovate still filtering 25.08."""
    result = run_against(
        tmp_path,
        {
            "packageRules": [
                rule(FSDK, r"^freedesktop-sdk-(?<version>25\.08\.[0-9]+)$"),
                rule(GBM, r"^(?<version>50\.[0-9]+)$"),
            ]
        },
        BOTH_JUNCTIONS,
    )
    assert result.returncode == 1
    assert "matches no tag" in result.stderr
    assert "freedesktop-sdk.bst" in result.stderr


def test_fails_when_a_junction_has_no_rule(tmp_path):
    result = run_against(
        tmp_path,
        {"packageRules": [rule(GBM, r"^(?<version>50\.[0-9]+)$")]},
        BOTH_JUNCTIONS,
    )
    assert result.returncode == 1
    assert "no packageRule" in result.stderr


def test_fails_when_the_junction_declares_no_track(tmp_path):
    result = run_against(
        tmp_path,
        {
            "packageRules": [
                rule(FSDK, r"^freedesktop-sdk-(?<version>26\.08\.[0-9]+)$"),
                rule(GBM, r"^(?<version>50\.[0-9]+)$"),
            ]
        },
        {
            "freedesktop-sdk.bst": "kind: junction\n\nsources:\n- kind: git_repo\n  ref: x\n",
            "gnome-build-meta.bst": junction("gnome-50"),
        },
    )
    assert result.returncode == 1
    assert "declares no `track:`" in result.stderr


def test_series_helpers_ignore_the_renovate_placeholder():
    assert check_renovate_series.series_of("freedesktop-sdk-26.08*") == "freedesktop-sdk-26.08"
    assert check_renovate_series.series_of("gnome-50") == "gnome-50"
    assert check_renovate_series.digits(r"^freedesktop-sdk-(?<version>26\.08\.[0-9]+)$") == ["26", "08"]
    assert check_renovate_series.digits("freedesktop-sdk-26.08") == ["26", "08"]


def test_the_real_repo_is_consistent():
    """Runs the script against the checked-in tree, so drift fails CI."""
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
