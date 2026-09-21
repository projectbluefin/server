"""`files/kubernetes/kubeadm.yaml` must parse the way kubeadm parses it.

kubeadm reads `--config` through `k8s.io/apimachinery/pkg/util/yaml`, whose
YAMLReader splits the stream on lines that are exactly ``---`` and decodes each
chunk independently. Every chunk must carry both ``apiVersion`` and ``kind``;
an empty one is rejected with::

    error: invalid configuration for GroupVersionKind /, Kind=: kind and
    apiVersion is mandatory information that must be specified

That is not a hypothetical. The file opened with a fourteen-line comment header
followed by a ``---`` separator, which made the header a document of its own.
`kubeadm init` failed on every boot, `kubeadm-init.service` restart-looped,
`bluefin-cluster-bootstrap.service` never ran because it declares
``Requires=kubeadm-init.service``, and the installer smoke gate timed out after
900 s waiting for a console that could never come up. Nothing else caught it:
the element builds, `just validate` resolves, and the unit suite passed.

**This module deliberately does not use ``yaml.safe_load_all``.** PyYAML is
more forgiving than the Go splitter: on the broken file it returned three clean
documents and no empty one, so a PyYAML-based gate would have passed while
kubeadm kept failing. Emulating the splitter is the whole point.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
KUBEADM_CONFIG = ROOT / "files" / "kubernetes" / "kubeadm.yaml"

# k8s.io/apimachinery/pkg/util/yaml YAMLReader: a separator is a line that is
# exactly `---`, optionally followed by whitespace.
SEPARATOR = re.compile(r"(?m)^---\s*$")


def chunks() -> list[str]:
    return SEPARATOR.split(KUBEADM_CONFIG.read_text(encoding="utf-8"))


def test_config_exists() -> None:
    assert KUBEADM_CONFIG.is_file(), f"{KUBEADM_CONFIG.relative_to(ROOT)} is missing"


def test_every_document_kubeadm_sees_has_apiversion_and_kind() -> None:
    parts = chunks()

    assert parts, "the splitter produced no chunks at all"

    for index, chunk in enumerate(parts):
        document = yaml.safe_load(chunk) if chunk.strip() else None

        assert document is not None, (
            f"chunk {index} of {KUBEADM_CONFIG.relative_to(ROOT)} carries no "
            f"YAML nodes — only blank lines or comments. kubeadm decodes each "
            f"`---`-separated chunk independently and rejects an empty one with "
            f"'invalid configuration for GroupVersionKind /, Kind=: kind and "
            f"apiVersion is mandatory'. A comment block above the first `---` "
            f"becomes exactly this. Chunk content:\n{chunk[:200]}"
        )
        assert document.get("apiVersion"), (
            f"chunk {index} has no apiVersion; kubeadm requires one per document"
        )
        assert document.get("kind"), (
            f"chunk {index} has no kind; kubeadm requires one per document"
        )


def test_the_file_does_not_open_with_a_separator() -> None:
    """The specific shape that produced the empty leading document.

    Stated directly as well as through the splitter, because this is the form
    the mistake actually takes: a header comment, then `---`, then the first
    real document.
    """
    meaningful = [
        line
        for line in KUBEADM_CONFIG.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert meaningful, f"{KUBEADM_CONFIG.relative_to(ROOT)} has no content"
    assert meaningful[0].strip() != "---", (
        "the first non-comment line is a `---` separator, so everything above "
        "it becomes an empty document and kubeadm init fails. Drop the leading "
        "separator; the header comment belongs to the first real document."
    )


@pytest.mark.parametrize("required", ["InitConfiguration", "ClusterConfiguration"])
def test_the_kinds_kubeadm_init_needs_are_present(required: str) -> None:
    kinds = {
        (yaml.safe_load(c) or {}).get("kind")
        for c in chunks()
        if c.strip()
    }
    assert required in kinds, (
        f"{required} is missing; `kubeadm init --config` needs it to build the "
        f"control plane. Found: {sorted(k for k in kinds if k)}"
    )
