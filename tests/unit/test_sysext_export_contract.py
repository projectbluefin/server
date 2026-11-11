import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JUSTFILE = ROOT / "Justfile"
HELPER = "_export-sysext-element"
EXPORT_RECIPE = re.compile(r"^(export-(?:[\w-]+-)?sysext)\b[^:]*:(?!=)", re.MULTILINE)
HELPER_CALL = re.compile(rf"^just {re.escape(HELPER)} (\S+) (\S+)$")


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


def export_recipes() -> list[str]:
    return EXPORT_RECIPE.findall(JUSTFILE.read_text(encoding="utf-8"))


def sysext_image_name(element: str) -> str:
    text = (ROOT / "elements" / "oci" / element).read_text(encoding="utf-8")
    match = re.search(r'^\s*sysext-image:\s*"([^"]+)"', text, re.MULTILINE)
    assert match, f"{element} does not declare a sysext-image name"
    return re.sub(r"%\{[\w-]+-version\}$", "", match.group(1))


def test_export_sysext_does_not_emit_legacy_k3s_alias() -> None:
    body = recipe_body("export-sysext")

    assert body, "the export-sysext recipe is missing, so this check would pass vacuously"
    assert f"just {HELPER} k0s-sysext k0s-" in body, "export-sysext no longer exports k0s"
    assert not [line for line in body if "k3s" in line]


def test_every_export_recipe_only_calls_the_shared_helper() -> None:
    recipes = export_recipes()
    assert len(recipes) >= 7, f"found only {recipes}; the recipe pattern no longer matches"

    for recipe in recipes:
        body = recipe_body(recipe)
        assert body, f"{recipe} has no body"
        inlined = [line for line in body if not HELPER_CALL.match(line)]
        assert not inlined, f"{recipe} re-inlines the export body instead of calling {HELPER}: {inlined}"


def test_export_recipes_copy_globs_match_the_element_image_names() -> None:
    for recipe in export_recipes():
        for line in recipe_body(recipe):
            match = HELPER_CALL.match(line)
            assert match, f"{recipe}: {line!r} does not call {HELPER}"
            element, prefix = (
                part.replace("{{FLAVOUR}}", "nvidia-open-595") for part in match.groups()
            )
            assert prefix == sysext_image_name(f"{element}.bst"), (
                f"{recipe} copies {prefix}*.raw.zst, which never matches {element}'s image name"
            )


def test_helper_keeps_other_exports_and_replaces_its_own_checksum_line() -> None:
    body = recipe_body(HELPER)

    assert body, f"the {HELPER} recipe is missing, so this check would pass vacuously"
    assert not [line for line in body if re.search(r"rm -rf\s+\"?dist/sysext\"?(\s|$)", line)], (
        "the helper wipes dist/sysext/, so one export erases the others"
    )
    assert not [line for line in body if re.search(r">>\s*dist/sysext/SHA256SUMS", line)], (
        "the helper appends to SHA256SUMS blindly, so a re-export duplicates its line"
    )
    assert any("drop[$NF]" in line for line in body), "the helper no longer drops stale SHA256SUMS lines"
