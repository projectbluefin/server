"""The shared sysext recipe (include/sysext.yml) ships only the release asset.

The uncompressed EROFS image is an intermediate. Left in the artifact it
doubled or tripled every sysext in the BuildStream cache and in the sandbox of
every element that stages one (kubeadm: 383 MB beside its 106 MB .raw.zst),
and nothing reads it: the image element, the Justfile exports and the release
all take the .raw.zst.
"""


import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RECIPE = yaml.safe_load((ROOT / "include" / "sysext.yml").read_text(encoding="utf-8"))["variables"]["sysext-pack"]


def test_the_uncompressed_image_is_built_outside_the_artifact() -> None:
    assert re.search(r'^\s*out="\$\{PWD\}/%\{sysext-image\}\.raw"$', RECIPE, re.MULTILINE)
    assert "%{install-root}/%{sysext-image}.raw\"" not in RECIPE.replace(".raw.zst", "")


def test_the_artifact_holds_the_compressed_image_and_its_checksum() -> None:
    assert 'zstd -T0 -19 -q "${out}" -o "%{install-root}/%{sysext-image}.raw.zst"' in RECIPE
    assert '(cd "%{install-root}" && sha256sum --binary "%{sysext-image}.raw.zst" > SHA256SUMS)' in RECIPE


def test_no_element_reads_an_uncompressed_sysext_from_an_artifact() -> None:
    # Every consumer names the .raw.zst; a bare ".raw" under /sysext would
    # have been the stripped intermediate.
    for element in sorted((ROOT / "elements").rglob("*.bst")):
        text = element.read_text(encoding="utf-8")
        assert not re.search(r"/sysext/[a-z0-9-]+/[a-z0-9_.-]+\.raw(?![.\w])", text), element
