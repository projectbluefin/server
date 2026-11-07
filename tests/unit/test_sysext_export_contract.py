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
    return match.group(1).split("%{", 1)[0]


HELPER = "_export-sysext-element"
# Recipes that still carry their own checkout body: k0s (wipes dist/sysext,
# its own version axis) and the homelab loop over four elements.
INLINE_EXPORTS = {"export-sysext", "export-homelab-sysext"}


def export_recipes() -> list[str]:
    text = JUSTFILE.read_text(encoding="utf-8")
    return re.findall(r"^(export-[\w-]*sysext)\b", text, re.MULTILINE)


def test_export_recipes_copy_globs_match_the_element_image_names() -> None:
    callers = 0
    for recipe in export_recipes():
        if recipe in INLINE_EXPORTS:
            continue
        body = recipe_body(recipe)
        calls = [line.split() for line in body if line.startswith(f"just {HELPER} ")]
        assert len(calls) == 1 and len(body) == 1, (
            f"{recipe} must delegate to {HELPER} instead of repeating the export body"
        )
        name, prefix = (
            arg.replace("{{FLAVOUR}}", "nvidia-open-595") for arg in calls[0][2:4]
        )
        assert prefix == sysext_image_name(f"{name}-sysext.bst"), (
            f"{recipe} copies {prefix}*.raw.zst, which never matches "
            f"{sysext_image_name(f'{name}-sysext.bst')}<version>.raw.zst"
        )
        callers += 1
    assert callers >= 5, "no export recipe delegates to the shared helper, so this check passed vacuously"


def test_shared_export_helper_copies_the_prefix_glob() -> None:
    body = recipe_body(HELPER)
    assert body, f"the {HELPER} recipe is missing, so this check would pass vacuously"
    assert "just bst artifact checkout oci/{{NAME}}-sysext.bst --directory /src/dist/{{NAME}}-checkout" in body
    assert "cp dist/{{NAME}}-checkout/{{PREFIX}}*.raw.zst dist/sysext/" in body
    assert "grep 'raw.zst$' dist/{{NAME}}-checkout/SHA256SUMS >> dist/sysext/SHA256SUMS" in body
