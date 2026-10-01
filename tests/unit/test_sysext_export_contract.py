import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
JUSTFILE = ROOT / "Justfile"


def recipe_body(name: str) -> list[str]:
    lines = JUSTFILE.read_text(encoding="utf-8").splitlines()
    header = re.compile(rf"{re.escape(name)}(\s[^:]*)?:(?!=)")
    for index, line in enumerate(lines):
        if header.match(line):
            body = []
            for following in lines[index + 1 :]:
                if following and not following[0].isspace():
                    break
                if following.strip():
                    body.append(following.strip())
            return body
    return []


def test_export_sysext_does_not_emit_legacy_k3s_alias() -> None:
    body = recipe_body("export-sysext")

    assert body, "the export-sysext recipe is missing, so this check would pass vacuously"
    assert any("oci/k0s-sysext.bst" in line for line in body), "export-sysext no longer exports k0s"
    assert not [line for line in body if "k3s" in line]


def sysext_image_name(element: str) -> str:
    text = (ROOT / "elements" / "oci" / element).read_text(encoding="utf-8")
    match = re.search(r'^\s*sysext-image:\s*"([^"]+)"', text, re.MULTILINE)
    assert match, f"{element} does not declare a sysext-image name"
    return match.group(1).replace("%{image-version}", "")


def test_export_recipes_copy_globs_match_the_element_image_names() -> None:
    for recipe, element in (
        ("export-zfs-sysext", "zfs-sysext.bst"),
        ("export-nvidia-sysext", "nvidia-open-595-sysext.bst"),
    ):
        body = recipe_body(recipe)
        assert body, f"the {recipe} recipe is missing, so this check would pass vacuously"

        copies = [line for line in body if line.startswith("cp ") and ".raw.zst" in line]
        assert copies, f"{recipe} never copies a .raw.zst artifact"

        prefix = sysext_image_name(element)
        for line in copies:
            glob = line.split()[1].rsplit("/", 1)[-1]
            stem = glob.split("*", 1)[0].replace("{{FLAVOUR}}", "nvidia-open-595")
            assert stem == prefix, (
                f"{recipe} copies {glob!r}, which never matches {prefix}<version>.raw.zst"
            )
