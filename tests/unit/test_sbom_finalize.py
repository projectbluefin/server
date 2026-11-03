"""The jq step in oci/bluefin-server-image.bst that finalizes the SBOM.

collect_manifest (buildstream-plugins-community) writes one DESCRIBES
relationship per package, and FSDK bootstrap elements reached through two
junction paths come out twice. The step drops exact duplicates only: a
relationship whose fields differ, or two different packages under one SPDXID,
must never be merged away.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
IMAGE = ROOT / "elements" / "oci" / "bluefin-server-image.bst"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="needs jq")


def program() -> str:
    (command,) = [c for c in yaml.safe_load(IMAGE.read_text(encoding="utf-8"))["config"]["commands"]
                  if "/sbom/bluefin-server.spdx.json" in c]
    match = re.search(r"'(\.creationInfo\.created = \$created.*?)'", command, re.DOTALL)
    assert match, "the jq program starts by stamping creationInfo.created"
    return match[1]


def finalize(doc: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["jq", "--arg", "created", "2011-11-11T11:11:11Z", program()],
                          input=json.dumps(doc), capture_output=True, text=True)


def package(spdxid: str, version: str = "1") -> dict:
    return {"SPDXID": spdxid, "name": spdxid, "versionInfo": version, "filesAnalyzed": False}


def describes(spdxid: str, kind: str = "DESCRIBES", source: str = "SPDXRef-DOCUMENT") -> dict:
    return {"spdxElementId": source, "relationshipType": kind, "relatedSpdxElement": spdxid}


def test_identical_packages_and_relationships_collapse() -> None:
    a, b = package("SPDXRef-a-0"), package("SPDXRef-b-0")
    doc = {"packages": [b, a, b], "relationships": [describes("SPDXRef-b-0"), describes("SPDXRef-a-0"),
                                                    describes("SPDXRef-b-0")]}
    result = finalize(doc)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["creationInfo"]["created"] == "2011-11-11T11:11:11Z"
    assert out["packages"] == [a, b]
    assert out["relationships"] == [describes("SPDXRef-a-0"), describes("SPDXRef-b-0")]


def test_relationships_to_one_element_are_kept_when_they_differ() -> None:
    # unique_by(.relatedSpdxElement) used to keep only one of these.
    rels = [describes("SPDXRef-a-0"), describes("SPDXRef-a-0", kind="CONTAINS"),
            describes("SPDXRef-a-0", source="SPDXRef-b-0")]
    result = finalize({"packages": [package("SPDXRef-a-0"), package("SPDXRef-b-0")], "relationships": rels})
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)["relationships"]) == 3


def test_one_package_per_spdxid_is_kept() -> None:
    # fsdk-containers pins its own FSDK, so brew-nspawn brings a second pcre2
    # under the same SPDXID. The build keeps one rather than failing; the
    # SBOM gap is tracked in an issue.
    doc = {"packages": [package("SPDXRef-a-0", "1"), package("SPDXRef-a-0", "2")],
           "relationships": [describes("SPDXRef-a-0")]}
    result = finalize(doc)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["packages"] == [package("SPDXRef-a-0", "1")]
