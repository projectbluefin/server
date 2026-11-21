"""reproducibility.yml rebuilds everything that ships.

Every element oci/bluefin-server-image.bst stages into the release set and
every oci/* target `just validate` resolves must be in FINAL_ASSEMBLY, or its
cached artifact is reused by the second build and never compared.
"""


import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
IMAGE = ROOT / "elements" / "oci" / "bluefin-server-image.bst"


def final_assembly() -> set[str]:
    job = yaml.safe_load((WORKFLOWS / "reproducibility.yml").read_text())["jobs"]["reproducibility"]
    return set(job["env"]["FINAL_ASSEMBLY"].split())


def staged_into_release_set() -> set[str]:
    """Dependencies the image element stages at a location: its payload."""
    element = yaml.safe_load(IMAGE.read_text())
    deps = element.get("build-depends", []) + element.get("depends", [])
    return {d["filename"] for d in deps if isinstance(d, dict) and "location" in d.get("config", {})}


def validate_targets() -> set[str]:
    recipe = (ROOT / "Justfile").read_text().split("\nvalidate:", 1)[1].split("\n\n", 1)[0]
    return set(re.findall(r"\boci/[\w.-]+\.bst\b", recipe))


def test_shipped_set_is_derived_from_the_build() -> None:
    staged, validated = staged_into_release_set(), validate_targets()
    assert {"oci/bluefin-server-usr.bst", "oci/bluefin-server-sbom.bst", "oci/nvidia-open-595-sysext.bst"} <= staged
    assert "oci/bluefin-server-image.bst" in validated
    assert "oci/nvidia-container-toolkit-sysext.bst" in validated


def test_reproducibility_rebuilds_everything_that_ships() -> None:
    missing = (staged_into_release_set() | validate_targets()) - final_assembly()
    assert not missing, f"add to FINAL_ASSEMBLY in reproducibility.yml: {sorted(missing)}"


def rebuild_step() -> str:
    job = yaml.safe_load((WORKFLOWS / "reproducibility.yml").read_text())["jobs"]["reproducibility"]
    return next(s["run"] for s in job["steps"] if s["name"].startswith("Rebuild"))


def test_the_rebuild_deletes_the_project_elements_the_roots_are_built_from() -> None:
    # Deleting only the roots reused the cached signed modules, the Go helpers
    # and the initrd, so their reproducibility was never tested.
    run = rebuild_step()
    assert "just bst show --deps all --format '%{name}' ${FINAL_ASSEMBLY}" in run
    assert "just bst artifact delete $(cat rebuild.txt)" in run
    # FSDK's own elements and efi-keys stay cached, by name.
    assert "freedesktop-sdk\\.bst:" in run and "efi-keys\\.bst" in run
    # Colour codes would break the element names; a short listing must fail.
    assert "x1b" in run
    assert "-lt 60" in run and "kernel-modules.bst" in run


def test_a_failed_or_cancelled_scheduled_run_opens_the_tracking_issue() -> None:
    workflow = yaml.safe_load((WORKFLOWS / "reproducibility.yml").read_text())
    job = workflow["jobs"]["status"]
    assert job["needs"] == ["reproducibility"]
    assert job["if"] == "${{ !cancelled() && github.event_name == 'schedule' }}"
    assert job["permissions"] == {"issues": "write"}
    report = job["steps"][-1]
    assert report["env"]["FAILED"] == "${{ contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled') }}"
    assert 'tracking-issue.sh "Reproducibility check failing"' in report["run"]


def test_final_assembly_names_real_elements_and_keeps_the_efi_keys() -> None:
    for element in final_assembly():
        assert (ROOT / "elements" / element).is_file(), element
    # sbvarsign stamps the current time into PK/KEK/db.auth; see the header.
    assert "bluefin-server/keys/efi-keys.bst" not in final_assembly()
