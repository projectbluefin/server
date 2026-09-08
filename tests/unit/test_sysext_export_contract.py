from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
JUSTFILE = ROOT / "Justfile"


def test_export_sysext_does_not_emit_legacy_k3s_alias() -> None:
    justfile = JUSTFILE.read_text(encoding="utf-8")
    start = justfile.index("export-sysext:")
    end = justfile.index("\n# Write the raw GPT installer image", start)

    assert "k3s-" not in justfile[start:end]
