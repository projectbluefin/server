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
