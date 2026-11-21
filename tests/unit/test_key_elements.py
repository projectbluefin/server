"""One element per kind of signing key, and each signer depends on only its own.

A single element importing all of files/boot-keys/ put every key in the cache
key of every signer. scripts/gen-dev-keys.sh makes new Secure Boot, image and
Ignition keys on every non-release CI run, so the kernel modules, which are
signed with the committed INSECURE dev module key, were rebuilt, re-signed and
zstd-compressed on every pull request, and so were ZFS and NVIDIA.

These tests keep the split honest:

- an element reads only /boot-keys/ paths that the key element it depends on
  stages, so it cannot quietly go back to needing the rest;
- the module signers do not depend on the Secure Boot or image keys;
- scripts/kernel-cache.sh refuses the graph of every key element, so no key
  element can be added without it knowing.
"""


import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ELEMENTS = ROOT / "elements"
KEYS = ELEMENTS / "bluefin-server" / "keys"
KEY_ELEMENTS = {
    "bluefin-server/keys/module-signing-key.bst",
    "bluefin-server/keys/secure-boot-keys.bst",
    "bluefin-server/keys/image-signing-keys.bst",
}
MODULE_SIGNERS = {"bluefin-server/kernel-modules.bst", "zfs/openzfs-signed.bst", "nvidia/nvidia-open-595-signed.bst"}
BOOT_SIGNERS = {
    "bluefin-server/keys/efi-keys.bst",
    "bluefin-server/os-sd-boot-signed.bst",
    "bluefin-server/shim.bst",
    "oci/bluefin-server-boot.bst",
}
IMAGE_SIGNERS = {"oci/bluefin-server-image.bst"}


def load(rel: str) -> dict:
    return yaml.safe_load((ELEMENTS / rel).read_text(encoding="utf-8"))


def dependencies(rel: str) -> set[str]:
    element = load(rel)
    deps = element.get("build-depends", []) + element.get("depends", [])
    return {d if isinstance(d, str) else d["filename"] for d in deps}


def staged_key_files(key_element: str) -> set[str]:
    """/boot-keys/<path> for each file the key element imports."""
    out = set()
    for source in load(key_element)["sources"]:
        directory = source.get("directory", "").rstrip("/")
        out.add("/boot-keys/" + (directory + "/" if directory else "") + Path(source["path"]).name)
    return out


def used_key_files(rel: str) -> set[str]:
    """/boot-keys/<path> for each key file the element's commands name."""
    text = (ELEMENTS / rel).read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return {f"/boot-keys/{path}" for path in re.findall(r"/boot-keys/((?:modules/)?[A-Za-z0-9_.-]+\.[a-z]+)", code)}


def test_the_whole_key_directory_is_never_imported() -> None:
    assert not (KEYS / "boot-keys.bst").exists()
    for key_element in KEY_ELEMENTS:
        for source in load(key_element)["sources"]:
            assert source["path"] != "files/boot-keys", key_element
            assert Path(source["path"]).suffix, f"{key_element}: {source['path']} is a directory, not a key file"


def test_the_key_elements_stage_disjoint_files() -> None:
    seen: dict[str, str] = {}
    for key_element in sorted(KEY_ELEMENTS):
        for path in staged_key_files(key_element):
            assert path not in seen, f"{path} is staged by {seen[path]} and {key_element}"
            seen[path] = key_element


def test_each_signer_depends_on_its_own_kind_of_key_only() -> None:
    for signer, key_element in [(s, "bluefin-server/keys/module-signing-key.bst") for s in MODULE_SIGNERS] + \
            [(s, "bluefin-server/keys/secure-boot-keys.bst") for s in BOOT_SIGNERS] + \
            [(s, "bluefin-server/keys/image-signing-keys.bst") for s in IMAGE_SIGNERS]:
        deps = dependencies(signer)
        assert key_element in deps, f"{signer} must depend on {key_element}"
        assert not (KEY_ELEMENTS - {key_element}) & deps, f"{signer} depends on a key it does not sign with"


def test_every_signer_reads_only_files_its_key_element_stages() -> None:
    for signer, key_element in [(s, "bluefin-server/keys/module-signing-key.bst") for s in MODULE_SIGNERS] + \
            [(s, "bluefin-server/keys/secure-boot-keys.bst") for s in BOOT_SIGNERS] + \
            [(s, "bluefin-server/keys/image-signing-keys.bst") for s in IMAGE_SIGNERS]:
        unstaged = used_key_files(signer) - staged_key_files(key_element)
        assert not unstaged, f"{signer} reads {sorted(unstaged)}, which {key_element} does not stage"
        assert used_key_files(signer), f"{signer} reads no /boot-keys file; this check would pass vacuously"


def test_no_other_element_depends_on_a_key_element() -> None:
    allowed = MODULE_SIGNERS | BOOT_SIGNERS | IMAGE_SIGNERS
    for element in sorted(ELEMENTS.rglob("*.bst")):
        rel = element.relative_to(ELEMENTS).as_posix()
        if rel in allowed or rel in KEY_ELEMENTS:
            continue
        assert not KEY_ELEMENTS & dependencies(rel), f"{rel} depends on a private-key element"


def test_the_cache_seed_refuses_every_key_element() -> None:
    script = (ROOT / "scripts" / "kernel-cache.sh").read_text(encoding="utf-8")
    listed = set(re.findall(r"^\s+(bluefin-server/keys/[a-z-]+\.bst)$", script.split("KEY_ELEMENTS=(", 1)[1].split(")", 1)[0], re.MULTILINE))
    assert listed == KEY_ELEMENTS
    on_disk = {p.relative_to(ELEMENTS).as_posix() for p in KEYS.glob("*.bst")}
    private = {e for e in on_disk if any("files/boot-keys" in s.get("path", "") and not s["path"].endswith(("modules", "ignition-pubring.pgp"))
                                         for s in load(e).get("sources", []))}
    assert private - {"bluefin-server/keys/linux-module-cert.bst"} <= KEY_ELEMENTS
