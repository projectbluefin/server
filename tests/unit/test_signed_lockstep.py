"""Contracts for signed downloads, version-locked sysexts and HTTP-boot Ignition."""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SYSUPDATE = ROOT / "files" / "os" / "sysupdate.d"
BOOT = ROOT / "elements" / "oci" / "bluefin-server-boot.bst"
KEYS = ROOT / "elements" / "bluefin-server" / "os-sysupdate-keys.bst"
INITRD = ROOT / "elements" / "bluefin-server" / "initrd" / "initrd-stack.bst"
IGN = ROOT / "files" / "initrd-ignition" / "usr"


def ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def test_diskless_pull_verifies_the_signature() -> None:
    boot = BOOT.read_text(encoding="utf-8")
    assert "rd.systemd.pull=raw,machine,verify=signature,blockdev,bootorigin:" in boot
    assert "verify=no" not in boot


def test_keyring_updates_with_usr_and_replaces_fsdk_vendor_key() -> None:
    keys = yaml.safe_load(KEYS.read_text(encoding="utf-8"))
    assert keys["sources"] == [{"kind": "local", "path": "files/boot-keys/import-pubring.pgp"}]
    assert keys["config"]["target"] == "/usr/lib/systemd"
    # Dependency order must make our key win in every consumer; allow only
    # this replacement, without masking unrelated staging collisions.
    assert "freedesktop-sdk.bst:components/systemd.bst" in keys["runtime-depends"]
    assert keys["public"]["bst"]["overlap-whitelist"] == ["/usr/lib/systemd/import-pubring.pgp"]
    for stack in (INITRD, ROOT / "elements/bluefin-server/os-stack.bst"):
        assert "bluefin-server/os-sysupdate-keys.bst" in yaml.safe_load(stack.read_text())["depends"]
    assert "freedesktop-sdk.bst:components/gnupg.bst" in INITRD.read_text()


def _feature_names() -> list[str]:
    """Return the stem of every ``*.feature`` file, failing loudly if none exist.

    An empty or missing ``sysupdate.d`` would otherwise collapse every
    parametrized test below into a silent skip.
    """
    names = sorted(p.stem for p in SYSUPDATE.glob("*.feature"))
    if not names:
        raise AssertionError(f"no *.feature files found under {SYSUPDATE}")
    return names


def _transfers_by_feature() -> dict[str, list[str]]:
    """Map each feature named in a ``[Transfer] Features=`` key to its transfers.

    ``Features=`` is a whitespace-separated list (systemd-sysupdate and
    ``bluefin-sysext-fetch`` both split it), so one transfer may serve
    several features.
    """
    by_feature: dict[str, list[str]] = {}
    for path in sorted(SYSUPDATE.glob("*.transfer")):
        for feature in ini(path)["Transfer"].get("Features", "").split():
            by_feature.setdefault(feature, []).append(path.name)
    return by_feature


def _feature_transfer_pairs() -> list[tuple[str, str | None]]:
    """Return ``(name, transfer_filename)`` for every optional sysupdate feature.

    ``updatectl features`` (and the D-Bus ``org.freedesktop.sysupdate1``
    interface it fronts) discovers features from ``*.feature`` files and the
    transfers each one enables from the ``Features=`` key inside
    ``[Transfer]``. Drift between the two sides silently breaks
    ``updatectl enable <feature>`` and the boot-time feature fetch, so the
    pair list is derived from disk rather than maintained by hand. A feature
    with no transfer is paired with ``None`` so the test fails for it.
    """
    by_feature = _transfers_by_feature()
    return [
        (name, transfer)
        for name in _feature_names()
        for transfer in by_feature.get(name) or [None]
    ]


@pytest.mark.parametrize("name,transfer", _feature_transfer_pairs())
def test_version_locked_sysexts_are_optional_features(name: str, transfer: str | None) -> None:
    assert transfer is not None, f"{name}.feature has no transfer naming it in Features="
    feature = ini(SYSUPDATE / f"{name}.feature")["Feature"]
    assert feature.get("Enabled", "false").lower() in {"", "false", "no", "0"}, (
        f"{name}.feature carries Enabled={feature.get('Enabled')!r}; "
        "opt-in features must default to Enabled=false so the homelab "
        "Ignition templates can flip them on per node"
    )
    t = ini(SYSUPDATE / transfer)
    assert name in t["Transfer"]["Features"].split()
    assert t["Transfer"]["ProtectVersion"] == "%A"
    assert t["Target"]["Path"] == "/var/lib/extensions"
    assert t["Target"]["MatchPattern"] == f"{name}_@v.raw"


@pytest.mark.parametrize("name", _feature_names())
def test_sysupdate_feature_definition_parses(name: str) -> None:
    """Every ``*.feature`` file is a ``[Feature]`` section that updatectl can read.

    A missing ``[Feature]`` section makes ``updatectl features`` print the
    feature with empty fields, so the shape is asserted explicitly.

    ``Documentation=`` and ``AppStream=`` are refused (#375): in systemd 261
    (FSDK 26.08) ``systemd-sysupdate --json features <name>`` reports them as
    ``documentation``/``appStream``, while updatectl's strict JSON dispatch
    only knows ``documentationUrl``, so one such key makes every
    ``updatectl features`` fail with "Unexpected object field
    'documentation'" and EADDRNOTAVAIL ("Cannot assign requested address").
    systemd 262 aligns both sides (systemd/systemd#43617); allow them again
    once FSDK ships it.
    """
    parser = ini(SYSUPDATE / f"{name}.feature")
    assert "Feature" in parser, (
        f"{name}.feature is missing the [Feature] section; updatectl will "
        "list it but every field will be empty"
    )
    section = parser["Feature"]
    assert section.get("Description", "").strip(), (
        f"{name}.feature has no Description=; the updatectl features table "
        "falls back to an empty column"
    )
    unreadable = sorted({"Documentation", "AppStream"} & set(section))
    assert not unreadable, (
        f"{name}.feature sets {unreadable}: systemd 261's updatectl cannot "
        "parse them, and `updatectl features` fails for every feature (#375)"
    )
    assert set(section) <= {"Description", "Enabled"}, (
        f"{name}.feature carries keys systemd-sysupdate does not know: "
        f"{sorted(set(section) - {'Description', 'Enabled'})}"
    )


def test_no_sysupdate_feature_or_transfer_is_orphaned() -> None:
    """Each ``*.feature`` file pairs with exactly one ``*.transfer``.

    systemd-sysupdate itself allows several transfers per feature; the
    one-transfer rule is this repo's convention (one sysext per feature).

    ``updatectl features`` reads feature definitions; ``systemd-sysupdate
    update`` looks up the transfer that installs each enabled feature's
    sysext. Either side missing its counterpart leaves the feature silent:
    a feature without a transfer never stages anything, and a transfer
    that names a feature that doesn't exist errors out with
    "Optional feature not found".
    """
    features = set(_feature_names())
    transfers_by_feature = _transfers_by_feature()

    referenced = set(transfers_by_feature)
    assert features == referenced, (
        f"feature/transfer pairs drift: features without a transfer "
        f"{sorted(features - referenced)}; transfers referencing a missing "
        f"feature {sorted(referenced - features)}"
    )

    duplicates = {name: names for name, names in transfers_by_feature.items() if len(names) > 1}
    assert not duplicates, (
        f"repo convention: each feature ships exactly one sysext transfer "
        f"(MatchPattern <feature>_@v.raw); found several for {duplicates}"
    )


@pytest.mark.parametrize("element,name", [(f"{name}-sysext.bst", name) for name in _feature_names()])
def test_extension_release_name_carries_the_image_version(element: str, name: str) -> None:
    text = (ROOT / "elements" / "oci" / element).read_text(encoding="utf-8")
    assert f'sysext-release: "{name}_%{{image-version}}"' in text
    assert f'sysext-image: "{name}_%{{image-version}}"' in text


def test_sysext_units_are_started_after_a_boot_time_merge() -> None:
    unit = ini(ROOT / "files" / "os" / "systemd" / "system" / "bluefin-sysext-activate.service")
    assert unit["Unit"]["After"] == "systemd-sysext.service"
    assert unit["Service"]["ExecStart"] == "/usr/bin/systemctl start --no-block multi-user.target"


def test_http_booted_nodes_look_for_ignition_next_to_the_uki() -> None:
    helper = (IGN / "libexec" / "bluefin-ignition-credentials").read_text(encoding="utf-8")
    origin = (ROOT / "files" / "boot-origin" / "usr" / "libexec" / "bluefin-boot-origin").read_text(encoding="utf-8")
    assert "/usr/libexec/bluefin-boot-origin" in helper
    assert "StubDeviceURL-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f" in origin
    assert "rd.systemd.pull=*)" in origin and "*:http://*|*:https://*)" in origin, "iPXE-chainloaded nodes use the explicit pull URL"
    assert "NODE_CONFIG=bluefin-node.ign" in helper
    for stage in ("disks", "fetch", "fetch-offline", "files", "mount"):
        unit = (IGN / "lib" / "systemd" / "system" / f"ignition-{stage}.service").read_text(encoding="utf-8")
        assert "ConditionPathExists=/run/ignition/user.ign" in unit
