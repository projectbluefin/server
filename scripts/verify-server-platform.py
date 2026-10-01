#!/usr/bin/env python3
"""Observe pinned Argo CD Core/Valkey and cold offline snapshot repair in NEW kind.

Never reads ambient kubeconfig. Only public Git bytes enter the node/repo-server.
The selected actual Core manifests are reconciled from their exact shipped commit;
this does not claim full-platform/Cilium/admission/Console acceptance. On failure,
retain private diagnostics (not the disposable cluster); never emit a passed proof.
Requires Linux, a working local podman/docker provider, and Python PyYAML.
"""
import argparse
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import uuid

REPO = Path(__file__).resolve().parent.parent
CASES = ("sync", "drift_repair", "cache_flush", "cache_restart", "controller_restart", "repo_server_restart", "offline_snapshot")
KIND_VERSION = "v0.33.0"
KIND_HASHES = {"amd64": "aee6151561422756b764a4ae28e7f44cda5af5a9eead3cc9985112b1de8d8e0d",
               "arm64": "20022bee6cfcd5086cb7234d218e3454e6090022f2a8f55d1fa7fcf42c3867a2"}
# Official kind v0.33.0 release: both host architectures supported by this index.
NODE_IMAGE = "kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed"
SELECTED = ("argocd/10-core.yaml", "argocd/40-valkey.yaml", "argocd/50-network.yaml")
BASELINE_URL = "file:///bluefin-baseline/baseline.git"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_lock():
    return json.loads((REPO / "files/server/manifests/source-lock.json").read_text())


def provenance_hash(value):
    # Producer provenance uses standard ASCII JSON without a trailing newline;
    # artifact serialization below intentionally has its independent byte format.
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def proof_identity(staged):
    staged = Path(staged)
    producer_path = REPO / "files/server/manifests/produce-baseline.py"
    spec = importlib.util.spec_from_file_location("stock_baseline", producer_path)
    producer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(producer)
    locked = producer.validate_source_lock(producer_path.parent)
    validate_public_snapshot(staged / "baseline.git")
    # Re-render tracked resources, not caller-provided metadata or success flags.
    with tempfile.TemporaryDirectory(prefix="bluefin-stock-proof-") as temporary:
        expected = Path(temporary) / "platform"
        commit = producer.produce(producer_path.parent, expected)
        for relative in ("baseline-commit", "baseline-integrity.json", "platform-lock.json", "sbom-packages.json"):
            if (staged / relative).is_symlink() or (staged / relative).read_bytes() != (expected / relative).read_bytes():
                raise ValueError("staged stock artifact differs from tracked inputs: " + relative)
        expected_files = {p.relative_to(expected / "manifests").as_posix(): p.read_bytes()
                          for p in (expected / "manifests").rglob("*") if p.is_file()}
        actual_files = {p.relative_to(staged / "manifests").as_posix(): p.read_bytes()
                        for p in (staged / "manifests").rglob("*") if p.is_file() and not p.is_symlink()}
        if actual_files != expected_files:
            raise ValueError("staged resources differ from the canonical stock baseline")
    revision = subprocess.check_output(["git", "--git-dir", str(staged / "baseline.git"), "rev-parse", "HEAD"],
                                      env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null"))
    if revision.decode().strip() != commit:
        raise ValueError("staged bare Git HEAD differs from the canonical baseline commit")
    return {"baseline_commit": commit, "baseline_url": BASELINE_URL,
            "architecture": {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine()),
            "images": locked["images"], "source_lock_sha256": provenance_hash(locked),
            "platform_lock_sha256": sha256(staged / "platform-lock.json"),
            "proof_tool_sha256": sha256(Path(__file__)), "node_image": NODE_IMAGE,
            "selected_resources": list(SELECTED)}


def matching_proof(proof, identity):
    if not isinstance(proof, dict):
        return False
    if proof.get("schema") != 1 or proof.get("identity") != identity:
        return False
    if proof.get("argocd") != "3.5.3" or proof.get("valkey") != "9.1.2":
        return False
    observations = proof.get("observations", {})
    if not isinstance(observations, dict):
        return False
    artifacts = proof.get("artifacts")
    scope = proof.get("scope", {})
    if scope != {"selected_actual_core_only": True,
                 "production_roles_used": ["argocd/20-rbac.yaml", "argocd/21-cache-rbac.yaml", "bootstrap-rbac.yaml"],
                 "additional_test_rbac": [],
                 "not_verified": ["full-platform-sync", "Cilium-network-policy-enforcement", "Console-identity", "workload-admission"]}:
        return False
    application_uid = None
    if not isinstance(artifacts, str) or not Path(artifacts).is_dir():
        return False
    for case in CASES:
        observation = observations.get(case, {})
        if not isinstance(observation, dict) or not isinstance(observation.get("evidence_sha256"), str):
            return False
        if proof.get(case) is not True or observation.get("revision") != identity["baseline_commit"]:
            return False
        if not observation.get("application_uid") or not re.fullmatch(r"[0-9a-f]{64}", observation.get("evidence_sha256", "")):
            return False
        try:
            evidence = Path(artifacts) / (case + ".json")
            if evidence.is_symlink() or sha256(evidence) != observation["evidence_sha256"]:
                return False
            actual = json.loads(evidence.read_text())
            if actual.get("case") != case or actual.get("identity") != identity:
                return False
            application = actual.get("application", {})
            if not reconciled(application, identity["baseline_commit"]) or application.get("metadata", {}).get("uid") != observation["application_uid"]:
                return False
            if application_uid is not None and observation["application_uid"] != application_uid:
                return False
            application_uid = observation["application_uid"]
        except (OSError, ValueError, KeyError, TypeError):
            return False
    return True


def validate_public_snapshot(directory):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("public snapshot must be a real directory")
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("public snapshot contains a symlink: " + str(path))
        if not path.is_file() and not path.is_dir():
            raise ValueError("public snapshot contains nonpublic special files")
    # Never transport user/global git config, hooks, alternates, or credential helpers.
    for name in ("objects/info/alternates", "objects/info/http-alternates"):
        if (directory / name).exists():
            raise ValueError("public snapshot uses external Git objects")
    config = (directory / "config").read_text() if (directory / "config").exists() else ""
    if re.search(r"credential|include|url\s*=|helper\s*=|sshCommand|filter", config, re.I):
        raise ValueError("public snapshot contains nonpublic Git configuration")
    for path in (directory / "hooks").glob("*"):
        if path.is_file() and not path.name.endswith(".sample"):
            raise ValueError("public snapshot contains executable Git hooks")


def reconciled(application, revision):
    status = application.get("status", {})
    sync = status.get("sync", {})
    conditions = status.get("conditions", [])
    return (sync.get("status") == "Synced" and sync.get("revision") == revision
            and status.get("operationState", {}).get("phase") == "Succeeded"
            and bool(status.get("resources"))
            and not any(condition.get("type", "").endswith("Error") for condition in conditions))


def acquire_kind(cache, arch):
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / ("kind-" + KIND_VERSION + "-" + arch)
    expected = KIND_HASHES[arch]
    if target.exists() and sha256(target) == expected:
        target.chmod(0o755)
        return target
    url = f"https://github.com/kubernetes-sigs/kind/releases/download/{KIND_VERSION}/kind-linux-{arch}"
    with tempfile.NamedTemporaryFile(prefix=".kind-", dir=cache, delete=False) as temporary:
        path = Path(temporary.name)
        try:
            with urlopen(url, timeout=90) as response:
                shutil.copyfileobj(response, temporary)
            temporary.flush()
            if sha256(path) != expected:
                raise ValueError("kind download failed pinned SHA-256 verification")
            path.chmod(0o755)
            os.replace(path, target)
        finally:
            if path.exists():
                path.unlink()
    return target


class Proof:
    def __init__(self, args):
        self.args = args
        self.identity = proof_identity(args.staged)
        self.lock = source_lock()
        self.name = "bluefin-proof-" + uuid.uuid4().hex[:16]
        self.node = self.name + "-control-plane"
        self.context = "kind-" + self.name
        self.artifacts = args.artifacts.resolve()
        self.artifacts.mkdir(parents=True, exist_ok=False)
        self.artifacts.chmod(0o700)
        self.kubeconfig = self.artifacts / "kubeconfig"
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("GIT_", "KUBERNETES_"))
                    and key not in {"KUBECONFIG", "DOCKER_HOST", "DOCKER_CONTEXT", "CONTAINER_HOST", "CONTAINER_CONNECTION"}}
        self.env.update(KUBECONFIG=str(self.kubeconfig), KIND_EXPERIMENTAL_PROVIDER=args.provider,
                        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null")
        self.engine = shutil.which(args.provider)
        if not self.engine:
            raise ValueError("local container provider is missing: " + args.provider)
        self.kubectl = self.artifacts / "kubectl"
        self.kind = None
        self.attempted_create = False
        self.observations = {}
        self.sequence = 0

    def command(self, arguments, data=None, check=True, timeout=180):
        self.sequence += 1
        result = subprocess.run(list(map(str, arguments)), input=data, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=self.env, cwd=REPO, timeout=timeout)
        # Inputs can include generated cache passwords: never log stdin or Secrets.
        log = {"argv": list(map(str, arguments)), "returncode": result.returncode,
               "stdout": result.stdout.decode(errors="replace"), "stderr": result.stderr.decode(errors="replace")}
        (self.artifacts / f"command-{self.sequence:04d}.json").write_bytes(canonical(log))
        if check and result.returncode:
            raise RuntimeError("command failed; private diagnostics: " + str(self.artifacts) + ": " + " ".join(map(str, arguments)))
        return result

    def kube(self, *arguments, data=None, check=True, timeout=180):
        return self.command([self.kubectl, "--kubeconfig", self.kubeconfig, "--context", self.context,
                             "--request-timeout=45s", *arguments], data=data, check=check, timeout=timeout)

    def get(self, resource, name, namespace="argocd"):
        return json.loads(self.kube("get", resource, name, "-n", namespace, "-o", "json").stdout)

    def apply(self, documents):
        import yaml
        payload = yaml.safe_dump_all(documents, sort_keys=False).encode()
        self.kube("apply", "--server-side", "--field-manager=bluefin-proof-bootstrap", "-f", "-", data=payload)

    def pod(self, deployment):
        pods = json.loads(self.kube("get", "pods", "-n", "argocd", "-l", "app.kubernetes.io/name=" + deployment, "-o", "json").stdout)["items"]
        pods = [pod for pod in pods if not pod["metadata"].get("deletionTimestamp")]
        if len(pods) != 1:
            raise ValueError("expected one live pod for " + deployment)
        return pods[0]

    def exec(self, deployment, *arguments):
        pod = self.pod(deployment)
        return self.kube("exec", "-n", "argocd", pod["metadata"]["name"], "--", *arguments).stdout.decode().strip()

    def rollout(self, resource):
        self.kube("rollout", "status", resource, "-n", "argocd", "--timeout=" + str(self.args.timeout) + "s", timeout=self.args.timeout + 60)

    def ready(self):
        for resource in ("deployment/argocd-valkey", "deployment/argocd-repo-server", "deployment/argocd-applicationset-controller", "statefulset/argocd-application-controller"):
            self.rollout(resource)

    def wait_sync(self, after=None):
        deadline = time.monotonic() + self.args.timeout
        last = None
        while time.monotonic() < deadline:
            last = self.get("application", "bluefin-platform")
            if reconciled(last, self.identity["baseline_commit"]):
                fresh = not after or last["status"].get("reconciledAt", "") > after
                if fresh and last["status"].get("health", {}).get("status") == "Healthy":
                    return last
            time.sleep(3)
        (self.artifacts / "last-application.json").write_bytes(canonical(last))
        raise RuntimeError("actual Application failed exact-commit sync/health: " + str(self.artifacts))

    def refresh(self):
        prior = self.get("application", "bluefin-platform").get("status", {}).get("reconciledAt")
        time.sleep(1.1)
        self.kube("annotate", "application", "bluefin-platform", "-n", "argocd", "argocd.argoproj.io/refresh=hard", "--overwrite")
        return prior

    def repair(self):
        # Suspend only automatic sync while observing real workload drift, then
        # restore self-heal. No imperative resync/patch of desired state repairs it.
        self.kube("patch", "application", "bluefin-platform", "-n", "argocd", "--type=merge", "-p",
                  '{"spec":{"syncPolicy":{"automated":{"enabled":false}}}}')
        self.kube("patch", "deployment", "argocd-applicationset-controller", "-n", "argocd", "--type=merge", "-p", '{"spec":{"replicas":0}}')
        drift = self.get("deployment", "argocd-applicationset-controller")
        if drift["spec"]["replicas"] != 0:
            raise RuntimeError("workload drift was not observed")
        self.kube("patch", "application", "bluefin-platform", "-n", "argocd", "--type=merge", "-p",
                  '{"spec":{"syncPolicy":{"automated":{"enabled":true}}}}')
        application = self.wait_sync(self.refresh())
        self.rollout("deployment/argocd-applicationset-controller")
        repaired = self.get("deployment", "argocd-applicationset-controller")
        if repaired["spec"]["replicas"] != 1 or repaired.get("status", {}).get("availableReplicas", 0) != 1:
            raise RuntimeError("Argo did not restore the actual pinned workload")
        return {"drift": drift, "repaired": repaired, "application": application}

    def restart(self, deployment, resource):
        before = self.pod(deployment)
        self.kube("delete", "pod", before["metadata"]["name"], "-n", "argocd", "--wait=true")
        self.rollout(resource)
        deadline = time.monotonic() + self.args.timeout
        while time.monotonic() < deadline:
            try:
                after = self.pod(deployment)
                if after["metadata"]["uid"] != before["metadata"]["uid"] and all(c.get("ready") for c in after.get("status", {}).get("containerStatuses", [])) and after.get("status", {}).get("containerStatuses"):
                    return {"before_uid": before["metadata"]["uid"], "after_uid": after["metadata"]["uid"], "after": after}
            except ValueError:
                pass
            time.sleep(2)
        raise RuntimeError("replacement pod not observed: " + deployment)

    def observe(self, case, details):
        application = details.get("application") or self.wait_sync()
        evidence = self.artifacts / (case + ".json")
        evidence.write_bytes(canonical({"case": case, "identity": self.identity, "details": details, "application": application}))
        self.observations[case] = {"revision": application["status"]["sync"]["revision"],
                                   "application_uid": application["metadata"]["uid"], "evidence_sha256": sha256(evidence)}

    def block_wan(self):
        external_tcp = [self.engine, "exec", self.node, "timeout", "8", "bash", "-c", "exec 3<>/dev/tcp/1.1.1.1/443"]
        self.command(external_tcp)
        repo_pod = self.pod("argocd-repo-server")["metadata"]["name"]
        git_probe = ["exec", "-n", "argocd", repo_pod, "--", "git", "-c", "http.proxy=", "ls-remote",
                     "https://github.com/argoproj/argo-cd.git", "refs/tags/v3.5.3"]
        online_git = self.kube(*git_probe, timeout=90).stdout.decode()
        if not re.match(r"[0-9a-f]{40}\s", online_git):
            raise RuntimeError("actual repo-server WAN probe was not observed before blocking")
        addresses = json.loads(self.command([self.engine, "exec", self.node, "ip", "-j", "-4", "address"]).stdout)
        subnets = {"127.0.0.0/8", "10.244.0.0/16", "10.96.0.0/12"}
        for interface in addresses:
            for address in interface.get("addr_info", []):
                if address.get("scope") == "global":
                    subnets.add(str(ipaddress.ip_network(address["local"] + "/" + str(address["prefixlen"]), strict=False)))
        for family, allowed in (("iptables", sorted(subnets)), ("ip6tables", ["::1/128"])):
            self.command([self.engine, "exec", self.node, family, "-N", "BLUEFIN_PROOF_WAN"])
            for subnet in allowed:
                self.command([self.engine, "exec", self.node, family, "-A", "BLUEFIN_PROOF_WAN", "-d", subnet, "-j", "RETURN"])
            self.command([self.engine, "exec", self.node, family, "-A", "BLUEFIN_PROOF_WAN", "-j", "REJECT"])
            for chain in ("OUTPUT", "FORWARD"):
                self.command([self.engine, "exec", self.node, family, "-I", chain, "1", "-j", "BLUEFIN_PROOF_WAN"])
        blocked = self.command(external_tcp, check=False)
        blocked_git = self.kube(*git_probe, check=False, timeout=90)
        if blocked.returncode not in (1, 124) or blocked_git.returncode == 0:
            raise RuntimeError("WAN firewall did not deny both node and actual repo-server access")
        return {"allowed_ipv4": sorted(subnets), "external_tcp_returncode": blocked.returncode,
                "online_repo_probe": online_git, "blocked_repo_returncode": blocked_git.returncode,
                "blocked_repo_stderr": blocked_git.stderr.decode(errors="replace"),
                "ipv4_rules": self.command([self.engine, "exec", self.node, "iptables-save"]).stdout.decode(),
                "ipv6_rules": self.command([self.engine, "exec", self.node, "ip6tables-save"]).stdout.decode()}

    def clone_revisions(self):
        # repo-server's actual Git cache is on a disposable /tmp emptyDir. Inspect
        # checked-out Git objects, not a fabricated RPC/response or pod-ready bit.
        text = self.exec("argocd-repo-server", "sh", "-ec",
                         'find /tmp -type d -name .git -exec sh -c \'for p do git -C "$p/.." rev-parse HEAD; done\' sh {} +')
        revisions = [line.strip() for line in text.splitlines() if re.fullmatch(r"[0-9a-f]{40}", line.strip())]
        if self.identity["baseline_commit"] not in revisions:
            raise RuntimeError("exact baseline checkout was not observed in repo-server clone/cache")
        return revisions

    def run(self):
        import yaml
        host_arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
        if platform.system() != "Linux" or host_arch is None:
            raise ValueError("disposable kind proof requires supported Linux host")
        if self.identity["architecture"] != host_arch:
            raise ValueError("proof architecture differs from the host observation identity")
        if self.lock["sources"]["argocd"]["version"] != "3.5.3" or "valkey:9.1.2-" not in self.lock["images"]["valkey"]["ref"]:
            raise ValueError("proof must use the required pinned CD3.5.3/Valkey9.1.2")
        # Removing remote selector variables cannot neutralize saved engine contexts.
        # Assert actual endpoint is local before creating or deleting anything.
        if self.args.provider == "docker":
            contexts = json.loads(self.command([self.engine, "context", "inspect"]).stdout)
            if len(contexts) != 1 or not contexts[0]["Endpoints"]["docker"]["Host"].startswith("unix://"):
                raise ValueError("Docker engine context is not workstation-local")
        else:
            info = json.loads(self.command([self.engine, "info", "--format=json"]).stdout)
            if info.get("host", {}).get("serviceIsRemote"):
                raise ValueError("Podman engine is remote, not workstation-local")
            if info.get("host", {}).get("cgroupVersion") != "v2":
                raise ValueError("kind requires cgroup v2; no automatic host reconfiguration")
        provider_info = self.command([self.engine, "info", "--format=json"]).stdout.decode()
        (self.artifacts / "provider-permission.json").write_text(provider_info)
        snapshot = self.args.staged.resolve() / "baseline.git"
        validate_public_snapshot(snapshot)
        actual_commit = subprocess.check_output(["git", "--git-dir", str(snapshot), "rev-parse", "HEAD"], env=dict(self.env, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null")).decode().strip()
        if actual_commit != self.identity["baseline_commit"]:
            raise ValueError("staged snapshot differs from declared commit")
        names = self.command(["git", "--git-dir", snapshot, "ls-tree", "-r", "--name-only", actual_commit]).stdout.decode().splitlines()
        for name in names:
            if not name.startswith("platform/") or not name.endswith(".yaml"):
                raise ValueError("public snapshot contains a nonmanifest member: " + name)
            content = self.command(["git", "--git-dir", snapshot, "show", actual_commit + ":" + name]).stdout
            for document in yaml.safe_load_all(content):
                if isinstance(document, dict) and document.get("kind") == "Secret":
                    raise ValueError("refusing Secret bytes in the public proof snapshot")
            relative = name.removeprefix("platform/")
            if relative in SELECTED and content != (self.args.staged / "manifests" / relative).read_bytes():
                raise ValueError("staged Core manifests differ from the exact snapshot")
        public = self.artifacts / "public-baselines"
        public.mkdir(mode=0o755)
        public.chmod(0o755)
        shutil.copytree(snapshot, public / "baseline.git")
        # Parent diagnostics directory is private; kind mounts only this explicitly
        # public child, never kubeconfigs, keys, Console state, or the source tree.
        config = {"kind": "Cluster", "apiVersion": "kind.x-k8s.io/v1alpha4",
                  "networking": {"apiServerAddress": "127.0.0.1", "podSubnet": "10.244.0.0/16", "serviceSubnet": "10.96.0.0/12"},
                  "nodes": [{"role": "control-plane", "extraMounts": [{"hostPath": str(public),
                              "containerPath": "/var/lib/bluefin/server/baselines", "readOnly": True,
                              "selinuxRelabel": True}]}]}
        config_path = self.artifacts / "kind.yaml"
        config_path.write_text(yaml.safe_dump(config))
        self.kind = acquire_kind(self.args.cache.resolve(), host_arch)
        existing = self.command([self.kind, "get", "clusters"]).stdout.decode().splitlines()
        if self.name in existing:
            raise ValueError("refusing non-new cluster name")
        self.attempted_create = True
        create = [self.kind, "create", "cluster", "--name", self.name, "--image", NODE_IMAGE,
                  "--config", config_path, "--kubeconfig", self.kubeconfig, "--wait", str(self.args.timeout) + "s"]
        if self.args.provider == "podman" and info.get("host", {}).get("security", {}).get("rootless"):
            delegation = shutil.which("systemd-run")
            if not delegation:
                raise ValueError("rootless kind requires systemd-run user-scope cgroup delegation")
            create = [delegation, "--user", "--scope", "-p", "Delegate=yes", *create]
        self.command(create, timeout=self.args.timeout + 300)
        self.kubeconfig.chmod(0o600)
        node_environment = json.loads(self.command([self.engine, "inspect", self.node]).stdout)[0].get("Config", {}).get("Env", [])
        if any(item.split("=", 1)[0].lower() in {"http_proxy", "https_proxy", "all_proxy"} and item.split("=", 1)[-1] for item in node_environment):
            raise ValueError("proxy-enabled node cannot prove WAN denial")
        kubectl_path = self.command([self.engine, "exec", self.node, "sh", "-ec", "command -v kubectl"]).stdout.decode().strip()
        if not kubectl_path.startswith("/") or "\n" in kubectl_path:
            raise ValueError("node image did not provide a kubectl binary")
        self.command([self.engine, "cp", self.node + ":" + kubectl_path, self.kubectl])
        self.kubectl.chmod(0o755)
        self.kube("label", "node", self.node, "bluefin.io/controller=true")
        for key in ("argocd", "valkey"):
            self.command([self.engine, "exec", self.node, "ctr", "--namespace", "k8s.io", "images", "pull", self.lock["images"][key]["ref"]], timeout=600)
        manifests = self.args.staged / "manifests"
        def documents(name):
            return [document for document in yaml.safe_load_all((manifests / name).read_text()) if document]
        self.apply(documents("namespaces.yaml"))
        for path in sorted((manifests / "argocd/crds").glob("*.yaml")):
            self.apply([doc for doc in yaml.safe_load_all(path.read_text()) if doc])
        self.kube("wait", "--for=condition=Established", "crd/applications.argoproj.io", "crd/appprojects.argoproj.io", "--timeout=120s")
        for name in ("argocd/20-rbac.yaml", "argocd/21-cache-rbac.yaml", "bootstrap-rbac.yaml"):
            self.apply(documents(name))
        self.apply(documents("argocd/22-pod-policy.yaml"))
        password = secrets.token_urlsafe(32)
        self.apply([{"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "argocd-valkey", "namespace": "argocd"},
                     "stringData": {"auth": password}}])
        # Same root-generated Core inputs as the real lifecycle bootstrap. The
        # in-cluster config uses the controller's own bounded ServiceAccount;
        # it neither embeds admin credentials nor grants cluster-wide access.
        self.apply([
            {"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
             "metadata": {"name": "argocd-secret", "namespace": "argocd"}},
            {"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
             "metadata": {"name": "bluefin-in-cluster", "namespace": "argocd",
                          "labels": {"argocd.argoproj.io/secret-type": "cluster"}},
             "stringData": {"name": "in-cluster", "server": "https://kubernetes.default.svc",
                            "namespaces": "kube-system,argocd,argo,bluefin-system,bluefin-apps",
                            "clusterResources": "true", "config": "{}"}},
        ])
        for name in SELECTED:
            self.apply(documents(name))
        baseline = documents("argocd/30-baseline.yaml")
        application = next(doc for doc in baseline if doc["kind"] == "Application")
        if application["spec"]["source"]["repoURL"] != BASELINE_URL or application["spec"]["source"]["targetRevision"] != self.identity["baseline_commit"]:
            raise ValueError("baseline Application source does not match pinned proof identity")
        # Keep the real project/source/path/commit. Select only actual Core
        # manifests so no proof setup replaces the disposable node's CNI.
        application["spec"]["source"]["directory"] = {"recurse": True, "include": "{" + ",".join(SELECTED) + "}", "exclude": "**/kustomization.yaml"}
        self.apply(baseline)
        self.ready()
        initial = self.wait_sync()
        version = self.exec("argocd-repo-server", "argocd", "version", "--client", "--short")
        if not re.search(r"\bv?3\.5\.3(?:[+\s]|$)", version):
            raise RuntimeError("repo-server binary is not selected Argo CD3.5.3")
        server = self.exec("argocd-valkey", "valkey-cli", "INFO", "server")
        if "valkey_version:9.1.2" not in server:
            raise RuntimeError("actual cache server is not Valkey9.1.2")
        keys = self.exec("argocd-valkey", "valkey-cli", "DBSIZE")
        if not keys.isdigit() or int(keys) == 0:
            raise RuntimeError("Argo did not populate actual Valkey cache")
        self.observe("sync", {"application": initial, "argocd_version": version, "valkey_info": server,
                              "cache_keys": keys, "clones": self.clone_revisions(),
                              "cache_clients": self.exec("argocd-valkey", "valkey-cli", "CLIENT", "LIST")})
        self.observe("drift_repair", self.repair())
        flushed = self.exec("argocd-valkey", "valkey-cli", "FLUSHALL", "SYNC")
        if flushed != "OK":
            raise RuntimeError("actual cache flush failed")
        self.observe("cache_flush", dict(self.repair(), flush_reply=flushed))
        for case, deployment, resource in (("cache_restart", "argocd-valkey", "deployment/argocd-valkey"),
                                           ("controller_restart", "argocd-application-controller", "statefulset/argocd-application-controller"),
                                           ("repo_server_restart", "argocd-repo-server", "deployment/argocd-repo-server")):
            restarted = self.restart(deployment, resource)
            self.observe(case, dict(self.repair(), restart=restarted))
        clones_before = self.clone_revisions()
        wan = self.block_wan()
        flushed = self.exec("argocd-valkey", "valkey-cli", "FLUSHALL", "SYNC")
        if flushed != "OK":
            raise RuntimeError("offline cache flush failed")
        # Deleting the old repo pod physically destroys its /tmp emptyDir clone;
        # no cached repo or manifest response survives this pod replacement+flush.
        restarted = self.restart("argocd-repo-server", "deployment/argocd-repo-server")
        controller_restarted = self.restart("argocd-application-controller", "statefulset/argocd-application-controller")
        details = self.repair()
        clones_after = self.clone_revisions()
        self.observe("offline_snapshot", dict(details, wan=wan, flush_reply=flushed,
                                               destroyed_clone_pod_uid=restarted["before_uid"], restart=restarted,
                                               controller_restart=controller_restarted,
                                               clones_before=clones_before, clones_after=clones_after))
        return {"schema": 1, "identity": self.identity, "argocd": "3.5.3", "valkey": "9.1.2",
                **{case: True for case in self.observations}, "observations": self.observations,
                "artifacts": str(self.artifacts), "scope": {"selected_actual_core_only": True,
                "production_roles_used": ["argocd/20-rbac.yaml", "argocd/21-cache-rbac.yaml", "bootstrap-rbac.yaml"],
                "additional_test_rbac": [], "not_verified": ["full-platform-sync", "Cilium-network-policy-enforcement", "Console-identity", "workload-admission"]}}

    def cleanup(self):
        if self.attempted_create and self.kind:
            # Only the newly selected unique cluster can be affected by this.
            self.command([self.kind, "export", "logs", "--name", self.name, self.artifacts / "node-logs"], check=False, timeout=120)
            self.command([self.kind, "delete", "cluster", "--name", self.name, "--kubeconfig", self.kubeconfig], timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True, help="fresh private diagnostics directory; retained on failure")
    parser.add_argument("--cache", type=Path, default=REPO / ".cache/server-proof-tools")
    parser.add_argument("--provider", choices=("podman", "docker"), default="podman")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    os.umask(0o077)
    proof = None
    try:
        if args.timeout < 30:
            raise ValueError("timeout must be at least 30 seconds")
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("proof output must be fresh; refusing to overwrite any record")
        proof = Proof(args)
        try:
            record = proof.run()
        finally:
            proof.cleanup()
        if not matching_proof(record, proof.identity):
            raise ValueError("observed proof is incomplete")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as stream:
            stream.write(canonical(record))
        print(json.dumps({"proof": str(args.output), "artifacts": str(proof.artifacts)}))
    except (OSError, ValueError, KeyError, RuntimeError, ImportError, subprocess.SubprocessError) as error:
        if proof:
            (proof.artifacts / "failure.txt").write_text(str(error) + "\n")
        parser.exit(1, f"verify-server-platform: {error}\n")


if __name__ == "__main__":
    main()
