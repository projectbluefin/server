from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_k0s_service_unit():
    unit = ROOT / "files" / "k0s" / "sysext" / "k0scontroller.service"
    assert unit.is_file(), "k0scontroller.service missing"
    text = unit.read_text()
    assert "--disable-components=helm,autopilot" in text
    assert "--enable-worker" in text
    assert "--single" in text


def test_k0s_manifests_conf():
    conf = ROOT / "files" / "k0s" / "sysext" / "k0s-manifests.conf"
    assert conf.is_file(), "k0s-manifests.conf missing"
    text = conf.read_text()
    assert "d /var/lib/k0s/manifests 0755 root root - -" in text
    assert "C+ /var/lib/k0s/manifests/argocd - - - - /usr/share/k0s/manifests/argocd" in text
    assert "C+ /var/lib/k0s/manifests/kubestellar - - - - /usr/share/k0s/manifests/kubestellar" in text


def test_k0s_manifest_files():
    argo_yaml = ROOT / "files" / "k0s" / "manifests" / "argocd" / "install.yaml"
    assert argo_yaml.is_file(), "argocd install.yaml missing"
    assert "namespace: argocd" in argo_yaml.read_text()

    ks_dir = ROOT / "files" / "k0s" / "manifests" / "kubestellar"
    assert (ks_dir / "00-kubeflex-crds.yaml").is_file()
    assert (ks_dir / "10-kubeflex-operator.yaml").is_file()
    assert (ks_dir / "20-postgres.yaml").is_file()
    assert (ks_dir / "30-kubestellar-core.yaml").is_file()
    assert (ks_dir / "40-kubestellar-console.yaml").is_file()
    assert (ks_dir / "41-kubestellar-kiosk-proxy.yaml").is_file()
