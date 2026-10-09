"""The shim option: shim built from source, laid out on the ESPs only when asked.

`shim` (project.conf, default False) adds bluefin-server/shim.bst to the
image graph and puts the DB-signed shim at EFI/BOOT/BOOT<ARCH>.EFI with
MokManager next to it on the netboot and installer ESPs. With the option
off, the image element lays out the same files as before. The ESP steps run
here with systemd-repart stubbed out, once per option value.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "project.conf"
SHIM = ROOT / "elements" / "bluefin-server" / "shim.bst"
IMAGE = ROOT / "elements" / "oci" / "bluefin-server-image.bst"
IMAGE_YML = ROOT / "include" / "image.yml"
SHIM_DATA = "/usr/share/bluefin-server/shim"
STAGED = ("/sd-boot", "/boot-out", "/shim", "/homelab-templates", "/sysext", "/usr-image", "/tmp/")


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def expand(text: str, variables: dict[str, str]) -> str:
    for _ in range(5):
        text = re.sub(r"%\{([a-z0-9-]+)\}", lambda m: variables[m.group(1)], text)
    assert "%{" not in text
    return text


def test_option_is_a_bool_that_defaults_to_false() -> None:
    option = load(PROJECT)["options"]["shim"]
    assert option["type"] == "bool"
    assert option["default"] is False


def test_shim_is_built_from_a_pinned_upstream_release() -> None:
    element = load(SHIM)
    (source,) = element["sources"]
    assert source["kind"] == "tar"
    assert source["url"] == "github:rhboot/shim/releases/download/%{shim-version}/shim-%{shim-version}.tar.bz2"
    assert re.fullmatch(r"[0-9a-f]{64}", source["ref"])
    assert re.fullmatch(r"16\.\d+", element["variables"]["shim-version"])
    deps = element["build-depends"]
    assert "base/base-stack.bst" in deps
    assert "bluefin-server/keys/boot-keys.bst" in deps
    # Hard rule 2: no CPU baseline beyond x86_64.
    assert "-march" not in SHIM.read_text(encoding="utf-8")


def test_shim_embeds_the_db_certificate_and_a_bluefin_sbat_entry() -> None:
    element = load(SHIM)
    variables = element["variables"]
    configure = "\n".join(element["config"]["configure-commands"])
    build = "\n".join(element["config"]["build-commands"])
    assert "openssl x509 -in /boot-keys/DB.crt -outform DER -out vendor.cer" in configure
    # shim's build includes every data/sbat.<EFIDIR>.csv in .sbat.
    assert "data/sbat.%{shim-efidir}.csv" in configure
    assert "VENDOR_CERT_FILE=vendor.cer" in build
    assert "EFIDIR='%{shim-efidir}'" in build
    assert variables["shim-sbat"].startswith("shim.%{shim-efidir},1,Bluefin Server,shim,%{shim-version},")
    assert variables["shim-default-loader"] == r"\EFI\systemd\systemd-boot%{efi-arch}.efi"


def test_shim_build_fails_without_the_vendor_cert_sbat_or_signature() -> None:
    install = "\n".join(load(SHIM)["config"]["install-commands"])
    assert 'objcopy -O binary -j .vendor_cert "${shim}" vendor_cert.bin' in install
    assert 'cmp -s -n "${n}" -i 16:0 vendor_cert.bin vendor.cer' in install
    assert "objcopy -O binary -j .sbat" in install
    assert "grep -Fxq '%{shim-sbat}' sbat.csv" in install
    assert "grep -Fxq '%{shim-default-loader}'" in install
    assert 'sbverify --cert /boot-keys/DB.crt "${dst}/${f}.signed"' in install
    assert "for f in shim%{efi-arch}.efi mm%{efi-arch}.efi; do" in install


def test_image_depends_on_shim_only_under_the_option() -> None:
    image = load(IMAGE)
    assert all("shim" not in str(dep) for dep in image["build-depends"])
    assert image["variables"]["shim-esp"] == "false"
    (conditional,) = image["(?)"]
    assert list(conditional) == ["shim"]
    assert conditional["shim"]["variables"] == {"shim-esp": "true"}
    assert conditional["shim"]["build-depends"]["(>)"] == [
        {"filename": "bluefin-server/shim.bst", "config": {"location": "/shim"}}
    ]


def esp_step(marker: str) -> str:
    (step,) = [c for c in load(IMAGE)["config"]["commands"] if marker in c]
    return step


def run_esp_step(tmp_path: Path, marker: str, shim_esp: str) -> Path:
    variables = {k: v for k, v in load(IMAGE)["variables"].items() if isinstance(v, str)}
    variables.update(load(IMAGE_YML)["variables"])
    variables.update({"shim-esp": shim_esp, "datadir": "/usr/share"})
    script = expand(esp_step(marker), {**variables, "install-root": "/out"})
    root = tmp_path / "root"
    staged = "|".join(re.escape(p) for p in (*STAGED, "/out"))
    script = re.sub(rf"(?<=[\s\"=])(?={staged})", str(root), script)
    # Every file the step installs from a staged dependency.
    for path in set(re.findall(rf"{re.escape(str(root))}/(?:sd-boot|boot-out|shim|homelab-templates|sysext)/[^\s\"]+", script)):
        path = path.replace("*", "x")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(Path(path).name, encoding="utf-8")
    (root / "out").mkdir(parents=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "systemd-repart").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bindir / "systemd-repart").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "SOURCE_DATE_EPOCH": "1321009871"}
    subprocess.run(["bash", "-c", script], env=env, check=True, capture_output=True, text=True)
    return Path(re.search(r"esp=(\S+)", script).group(1))


@pytest.mark.parametrize("marker", ["esp=/tmp/netboot-esp", "esp=/tmp/installer-esp"])
def test_esps_boot_systemd_boot_by_default(tmp_path: Path, marker: str) -> None:
    esp = run_esp_step(tmp_path, marker, "false")
    boot = sorted(p.name for p in (esp / "EFI" / "BOOT").iterdir())
    assert boot == ["BOOTX64.EFI"]
    assert (esp / "EFI/BOOT/BOOTX64.EFI").read_text() == "systemd-bootx64.efi.signed"
    assert (esp / "EFI/systemd/systemd-bootx64.efi").read_text() == "systemd-bootx64.efi.signed"
    assert "secure-boot-enroll if-safe" in (esp / "loader/loader.conf").read_text()


@pytest.mark.parametrize("marker", ["esp=/tmp/netboot-esp", "esp=/tmp/installer-esp"])
def test_esps_boot_shim_under_the_option(tmp_path: Path, marker: str) -> None:
    esp = run_esp_step(tmp_path, marker, "true")
    boot = sorted(p.name for p in (esp / "EFI" / "BOOT").iterdir())
    assert boot == ["BOOTX64.EFI", "mmx64.efi"]
    assert (esp / "EFI/BOOT/BOOTX64.EFI").read_text() == "shimx64.efi.signed"
    assert (esp / "EFI/BOOT/mmx64.efi").read_text() == "mmx64.efi.signed"
    # shim's DEFAULT_LOADER: the DB-signed systemd-boot, still enrolling keys.
    assert (esp / "EFI/systemd/systemd-bootx64.efi").read_text() == "systemd-bootx64.efi.signed"
    assert "secure-boot-enroll if-safe" in (esp / "loader/loader.conf").read_text()
    assert not list(esp.rglob("fb*.efi"))


def test_shim_lands_only_on_the_netboot_and_installer_esps() -> None:
    steps = [c for c in load(IMAGE)["config"]["commands"] if "/shim" in c]
    assert len(steps) == 2
    assert all('if [ "%{shim-esp}" = true ]; then' in step for step in steps)
    assert "/shim" not in esp_step("esp=/tmp/ddi-esp")
    assert SHIM_DATA.replace("/usr/share", "%{datadir}") in steps[0]
