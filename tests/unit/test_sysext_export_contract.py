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

    # k0s no longer delegates: its recipe inlines the checkout and copies
    # oci/k0s-sysext.bst's artifact, so the export is preserved by the body.
    assert any("oci/k0s-sysext.bst" in line for line in body), "export-sysext no longer exports k0s"

    assert not [line for line in body if "k3s" in line]


def sysext_image_name(element: str) -> str:
    text = (ROOT / "elements" / "oci" / element).read_text(encoding="utf-8")
    match = re.search(r'^\s*sysext-image:\s*"([^"]+)"', text, re.MULTILINE)
    assert match, f"{element} does not declare a sysext-image name"
    return match.group(1).replace("%{image-version}", "")


# The five single-element add-on exports delegate to the shared helper.
# k0s behavior changes remain separate; homelab exports several elements.
def _sysext_export_recipes() -> list[str]:
    names = []
    for line in JUSTFILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not re.match(r"^export-", stripped) or ":" not in line:
            continue
        name = stripped.split(":", 1)[0].split()[0]
        if (name.endswith("-sysext")
                and name not in {"export-sysext", "export-homelab-sysext"}):
            names.append(name)
    return names


def _recipe_header(name: str) -> str:
    lines = JUSTFILE.read_text(encoding="utf-8").splitlines()
    header = re.compile(rf"^{re.escape(name)}(\s[^:]*)?:(?!=)")
    for line in lines:
        if header.match(line):
            return line
    return ""


def _flavour_of(header: str) -> str | None:
    match = re.search(r'FLAVOUR="([^"]*)"', header)
    return match.group(1) if match else None


def _resolve(expr: str, flavour: str | None) -> str:
    return expr.replace("{{FLAVOUR}}", flavour) if flavour else expr


def _helper_call(body: list[str]) -> tuple[str, str] | None:
    for line in body:
        if not line.startswith("just _export-sysext-element"):
            continue
        args = re.findall(r'"([^"]*)"', line)
        if len(args) == 2:
            return args[0], args[1]
    return None


def test_single_element_recipes_call_the_shared_helper() -> None:
    recipes = _sysext_export_recipes()
    assert recipes, "no export-*-sysext recipes found"
    # The parser splits the FLAVOUR= assignment off the header, so the NVIDIA
    # recipe is discovered rather than silently skipped (regression for #649).
    assert "export-nvidia-sysext" in recipes, "NVIDIA export dropped from discovery"

    for name in recipes:
        header = _recipe_header(name)
        flavour = _flavour_of(header)
        body = recipe_body(name)
        call = _helper_call(body)
        assert call, (
            f"{name} does not call _export-sysext-element; it re-inlines the "
            "checkout, copy, and SHA256SUMS steps, so its glob is unguarded"
        )

        ename = f"{_resolve(call[0], flavour)}-sysext.bst"
        element_path = ROOT / "elements" / "oci" / ename
        assert element_path.exists(), f"{name} names element {ename}, which does not exist"
        expected = re.sub(r"%\{[^}]+\}", "", sysext_image_name(ename))
        prefix = _resolve(call[1], flavour)
        assert prefix == expected, (
            f"{name} copies with prefix {prefix!r}, but the element's sysext-image is "
            f"{expected!r}, so the glob never matches the built artifact"
        )
