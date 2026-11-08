"""Home defaults and cluster access use the published templates and real helpers."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from _systemd import SystemdFile

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "files/homebrew/templates/home-server.bu"
SELECTOR = ROOT / "files/runtimes/bluefin-oci-features"
RENDERER = ROOT / "files/homebrew/compose-profile.py"
CLUSTER_TEMPLATE = ROOT / "files/homelab/templates/homelab-control-plane.bu"


def template_credentials(tmp_path: Path, profile: str = "home-server.bu") -> Path:
    """Render the published profile, then execute its real pre-fetch selector."""
    source = tmp_path / "profile-source"
    source.mkdir()
    shutil.copyfile(TEMPLATE, source / "home-server.bu")
    published = tmp_path / "published"
    subprocess.run([sys.executable, RENDERER, source / "home-server.bu", CLUSTER_TEMPLATE,
                    published], check=True)
    home = yaml.safe_load((published / profile).read_text())
    shutil.copyfile(SELECTOR, tmp_path / "bootstrap")
    units = {unit["name"]: unit for unit in home["systemd"]["units"]}
    defaults = [line.removeprefix("SetCredential=")
                for dropin in units["bluefin-oci-features.service"]["dropins"]
                for line in dropin["contents"].splitlines()
                if line.startswith("SetCredential=")]
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    for setting in defaults:
        name, value = setting.split(":", 1)
        (credentials / name).write_text(value)
    return credentials


def runtime(tmp_path: Path, credentials: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", tmp_path / "bootstrap", *args],
        env=os.environ | {
            "CREDENTIALS_DIRECTORY": str(credentials),
            "BLUEFIN_OCI_STATE_FILE": str(tmp_path / "runtimes.state"),
            "BLUEFIN_SYSUPDATE_ROOT": str(tmp_path / "host"),
        },
        text=True, capture_output=True, check=False,
    )


@pytest.mark.parametrize("profile", ["home-server.bu", "home-server-cluster.bu"])
def test_template_only_home_enables_podman_without_usb_profile_credential(
    tmp_path: Path, profile: str,
) -> None:
    result = runtime(tmp_path, template_credentials(tmp_path, profile), "--print-selection")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "true:false\n"


def test_explicit_docker_choice_does_not_require_podman(tmp_path: Path) -> None:
    credentials = template_credentials(tmp_path)
    (credentials / "bluefin.homebrew.podman").write_text("false")
    (credentials / "bluefin.homebrew.docker").write_text("true")
    result = runtime(tmp_path, credentials, "--print-selection")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "false:true\n"


def test_explicit_podman_disable_wins_template_default(tmp_path: Path) -> None:
    credentials = template_credentials(tmp_path)
    (credentials / "bluefin.homebrew.podman").write_text("false")
    result = runtime(tmp_path, credentials, "--print-selection")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "false:false\n"


@pytest.mark.root
def test_persisted_operator_disable_wins_template_default(tmp_path: Path) -> None:
    credentials = template_credentials(tmp_path)
    (tmp_path / "runtimes.state").write_text("false:false\n")
    result = runtime(tmp_path, credentials, "--print-selection")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "false:false\n"


# Real systemd configuration merging: the bootstrap reads the drop-ins with
# systemd-analyze.
@pytest.mark.root
@pytest.mark.usefixtures("systemd_analyze")
@pytest.mark.parametrize("operator_name", ["90-operator.conf", "50-bluefin-home-server.conf"])
def test_operator_feature_disable_is_not_reenabled_or_recorded_as_running(
    tmp_path: Path, operator_name: str,
) -> None:
    credentials = template_credentials(tmp_path)
    dropins = tmp_path / "host/etc/sysupdate.d/podman.feature.d"
    dropins.mkdir(parents=True)
    operator = dropins / operator_name
    contents = "# Operator policy\n[Feature]\nEnabled=false\n"
    operator.write_text(contents)
    result = runtime(tmp_path, credentials, "--configure-features")
    assert result.returncode == 0, result.stderr
    assert operator.read_text() == contents
    assert (tmp_path / "runtimes.state").read_text() == "false:false\n"
    assert not (tmp_path / "host/etc/sysupdate.d/docker.feature.d/90-operator.conf").exists()


@pytest.mark.parametrize("profile", ["home-server.bu", "home-server-cluster.bu"])
def test_profile_has_no_homebrew_machine_or_bridge(tmp_path: Path, profile: str) -> None:
    template_credentials(tmp_path, profile)
    text = (tmp_path / "published" / profile).read_text()
    for gone in (".nspawn", "machinectl", "sudo", "bluefin-homebrew.service",
                 "default-formulae", "homebrew.feature", "/var/lib/machines"):
        assert gone not in text
