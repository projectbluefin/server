from pathlib import Path

import os
import posixpath
import subprocess

import yaml

from _systemd import SystemdFile, Tmpfile, tmpfiles

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "files" / "kubestellar" / "sysext" / "kubestellar-seed.service"


def test_k0s_service_unit():
    unit = ROOT / "files" / "k0s" / "sysext" / "k0scontroller.service"
    assert unit.is_file(), "k0scontroller.service missing"
    controller = SystemdFile(unit)
    # The default command line, K0S_CONTROLLER_ARGS from Environment= expanded:
    # a single-node controller that also runs the workloads.
    commands = controller.commands()
    assert len(commands) == 1
    argv = commands[0]
    assert posixpath.basename(argv[0]) == "k0s" and argv[1] == "controller"
    assert {"--enable-worker", "--single", "--disable-components=helm,autopilot"} <= set(argv[2:])
    assert "!/etc/k0s/token" in controller.values("Unit", "ConditionPathExists")


def test_k0s_worker_unit_joins_with_the_token_file():
    worker = SystemdFile(ROOT / "files" / "k0s" / "sysext" / "k0sworker.service")
    commands = worker.commands()
    assert len(commands) == 1
    argv = commands[0]
    assert posixpath.basename(argv[0]) == "k0s"
    assert argv[1:4] == ["worker", "--token-file", "/etc/k0s/token"]
    assert "/etc/k0s/token" in worker.values("Unit", "ConditionPathExists")


def test_k0s_manifests_conf():
    conf = ROOT / "files" / "kubestellar" / "sysext" / "k0s-manifests.conf"
    assert conf.is_file(), "k0s-manifests.conf missing"
    rules = {rule.path: rule for rule in tmpfiles(conf)}
    assert rules["/var/lib/k0s/manifests"] == Tmpfile(
        "d", "/var/lib/k0s/manifests", "0755", "root", "root", "-", "-"
    )
    for stack in ("argocd", "kubestellar"):
        rule = rules[f"/var/lib/k0s/manifests/{stack}"]
        assert (rule.type, rule.argument) == ("C+", f"/usr/share/k0s/manifests/{stack}")


def test_k0s_manifest_files():
    argo_yaml = ROOT / "files" / "k0s" / "manifests" / "argocd" / "install.yaml"
    assert argo_yaml.is_file(), "argocd install.yaml missing"
    docs = [d for d in yaml.safe_load_all(argo_yaml.read_text()) if d]
    assert {"kind": "Namespace", "name": "argocd"} in [
        {"kind": d["kind"], "name": d["metadata"]["name"]} for d in docs
    ]
    namespaced = [d for d in docs if d["kind"] != "Namespace"]
    assert namespaced
    assert all(d["metadata"].get("namespace") == "argocd" for d in namespaced)

    ks_dir = ROOT / "files" / "k0s" / "manifests" / "kubestellar"
    assert (ks_dir / "00-kubeflex-crds.yaml").is_file()
    assert (ks_dir / "10-kubeflex-operator.yaml").is_file()
    assert (ks_dir / "20-postgres.yaml").is_file()
    assert (ks_dir / "30-kubestellar-core.yaml").is_file()
    assert (ks_dir / "40-kubestellar-console.yaml").is_file()
    assert (ks_dir / "41-kubestellar-kiosk-proxy.yaml").is_file()
    assert (ks_dir / "42-kubestellar-console-rbac.yaml").is_file()


def test_postgres_password_not_hardcoded():
    # #98: the postgres superuser password must not be committed to git in
    # plaintext, and must not be the publicly documented kubeflex default.
    manifest = ROOT / "files" / "k0s" / "manifests" / "kubestellar" / "20-postgres.yaml"
    text = manifest.read_text()
    assert "kubeflex" not in text.lower().replace("kubeflex-system", "").replace("kubeflex-postgres", "")
    assert 'value: "kubeflex"' not in text
    assert "POSTGRESQL_PASSWORD" in text


def test_postgres_password_from_secret():
    # The StatefulSet reads the password from a Secret, not a plaintext env.
    docs = list(yaml.safe_load_all((ROOT / "files" / "k0s" / "manifests" / "kubestellar" / "20-postgres.yaml").read_text()))
    statefulset = next(d for d in docs if d and d.get("kind") == "StatefulSet")
    container = statefulset["spec"]["template"]["spec"]["containers"][0]
    env = {e["name"]: e for e in container["env"]}
    assert "value" not in env["POSTGRESQL_PASSWORD"]
    ref = env["POSTGRESQL_PASSWORD"]["valueFrom"]["secretKeyRef"]
    assert ref == {"name": "kubeflex-postgres", "key": "password"}


def seed_runs(script: str) -> bool:
    return any(posixpath.basename(argv[0]) == script for argv in SystemdFile(SEED).all_commands())


def test_k0s_first_boot_generates_postgres_secret_before_k0s():
    # The Secret must be staged before k0s applies the manifests, and the
    # generated 15- file must sort before 20-postgres.yaml.
    assert seed_runs("generate-postgres-secret.sh"), "kubestellar-seed never runs the postgres secret generator"
    assert "k0scontroller.service" in SystemdFile(SEED).words("Unit", "Before"), (
        "secrets must exist before k0s applies manifests"
    )


def test_generate_postgres_secret_is_idempotent(tmp_path):
    # Running the generator twice must not change an already-created password,
    # so the initialized database stays accessible across re-boots.
    script = ROOT / "files" / "k0s" / "kubeflex" / "generate-postgres-secret.sh"
    env = dict(os.environ, KUBEFLEX_MANIFEST_DIR=str(tmp_path))
    run = lambda: subprocess.run(["/bin/bash", str(script)], env=env, check=True, capture_output=True, text=True)
    run()
    secret_file = tmp_path / "15-kubeflex-postgres-secret.yaml"
    assert secret_file.is_file()
    secret = yaml.safe_load(secret_file.read_text())
    assert secret["kind"] == "Secret"
    assert secret["metadata"]["name"] == "kubeflex-postgres"
    assert secret["stringData"]["password"]
    first = secret_file.read_text()
    run()
    assert secret_file.read_text() == first, "password changed on re-run; DB would lose access"


def test_console_jwt_secret_not_hardcoded():
    # #72: the console JWT signing secret must not be committed to git. The
    # 01- manifest only creates the namespace; the Secret itself is generated
    # at first boot with a random jwt-secret.
    manifest = ROOT / "files" / "k0s" / "manifests" / "kubestellar" / "01-kubestellar-console-github-oauth.yaml"
    text = manifest.read_text()
    assert "kind: Secret" not in text
    assert "jwt-secret" not in yaml_values(text)
    docs = [d for d in yaml.safe_load_all(text) if d]
    assert [d["kind"] for d in docs] == ["Namespace"]


def yaml_values(text):
    # Collapse to non-comment lines so doc comments may still mention keys.
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def test_k0s_first_boot_generates_console_secret_before_k0s():
    assert seed_runs("generate-console-secret.sh"), "kubestellar-seed never runs the console secret generator"
    assert "k0scontroller.service" in SystemdFile(SEED).words("Unit", "Before")


def test_generate_console_secret_is_idempotent(tmp_path):
    # Re-running must not rotate the jwt-secret (sessions would break) and
    # must not clobber operator-supplied OAuth credentials.
    script = ROOT / "files" / "k0s" / "kubeflex" / "generate-console-secret.sh"
    env = dict(os.environ, KUBESTELLAR_MANIFEST_DIR=str(tmp_path))
    run = lambda: subprocess.run(["/bin/bash", str(script)], env=env, check=True, capture_output=True, text=True)
    run()
    secret_file = tmp_path / "02-kubestellar-console-secret.yaml"
    assert secret_file.is_file()
    assert (secret_file.stat().st_mode & 0o777) == 0o600
    secret = yaml.safe_load(secret_file.read_text())
    assert secret["kind"] == "Secret"
    assert secret["metadata"]["name"] == "kubestellar-console-github-oauth"
    assert secret["metadata"]["namespace"] == "kubestellar-console"
    jwt = secret["stringData"]["jwt-secret"]
    assert len(jwt) == 64 and all(c in "0123456789abcdef" for c in jwt)
    assert secret["stringData"]["client-id"] == ""
    assert secret["stringData"]["client-secret"] == ""
    first = secret_file.read_text()
    run()
    assert secret_file.read_text() == first, "jwt-secret changed on re-run"
