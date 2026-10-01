#!/usr/bin/env python3
"""Render vendored stock resources and a deterministic immutable bare Git baseline.

No network, upstream compilation, user files, private credentials, or compatibility
claims enter this producer. Optional disposable proof is a separate host operation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
from urllib.parse import quote

MODULES = ("cilium", "argocd", "workflows", "dashboard", "mcp", "reboot")


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def maintained_resources(source):
    source = Path(source)
    return {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(source.rglob("*")) if p.is_file() and p.suffix in {".yaml", ".in"}}


def validate_source_lock(source):
    lock = json.loads((Path(source) / "source-lock.json").read_text())
    if lock.get("schema") != 1:
        raise ValueError("unsupported stock source lock schema")
    for name, image in lock.get("images", {}).items():
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image.get("digest", "")) or not image.get("ref", "").endswith("@" + image["digest"]):
            raise ValueError("unresolved or inconsistent stock image: " + name)
    if lock.get("maintained_resources") != maintained_resources(source):
        raise ValueError("maintained raw resources differ from source provenance lock")
    if lock.get("producer_sha256") != hashlib.sha256((Path(source) / "produce-baseline.py").read_bytes()).hexdigest():
        raise ValueError("platform producer differs from source provenance lock")
    return lock


# These are initial root-owned security/storage contracts, not reconcilable user
# authority. CD never gets bind/escalate merely to repair its own broader roles.
BOOTSTRAP_ONLY = {"10-rbac.yaml", "20-rbac.yaml", "20-executor-rbac.yaml",
                  "10-storage.yaml", "21-cache-rbac.yaml", "22-pod-policy.yaml", "30-baseline.yaml",
                  "30-bounds.yaml", "30-apps-bounds.yaml", "20-api-policy.yaml",
                  "20-console.yaml",
                  "50-api-policies.yaml", "50-api-policy.yaml", "51-platform-admission.yaml"}


def snapshot(destination, files):
    """Git plumbing gives identical commits regardless of input order/mtimes/host."""
    destination = Path(destination)
    if destination.exists():
        raise ValueError("snapshot destination must not already exist")
    for name in files:
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts or not p.parts or "\n" in name or "\t" in name:
            raise ValueError("unsafe snapshot member")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
                       GIT_AUTHOR_NAME="Bluefin Server", GIT_AUTHOR_EMAIL="server@projectbluefin.io",
                       GIT_COMMITTER_NAME="Bluefin Server", GIT_COMMITTER_EMAIL="server@projectbluefin.io",
                       GIT_AUTHOR_DATE="2000-01-01T00:00:00+0000",
                       GIT_COMMITTER_DATE="2000-01-01T00:00:00+0000")
    def git(*args, data=None):
        return subprocess.check_output(["git", "--git-dir", str(destination), *args], input=data,
                                       env=environment).decode().strip()
    subprocess.run(["git", "init", "--bare", "--quiet", "--template=", "--initial-branch=baseline", str(destination)],
                   check=True, env=environment)
    with tempfile.TemporaryDirectory() as temporary:
        environment["GIT_INDEX_FILE"] = str(Path(temporary) / "index")
        for name, content in sorted(files.items()):
            blob = git("hash-object", "-w", "--stdin", data=content)
            git("update-index", "--add", "--cacheinfo", "100644," + blob + "," + name)
        tree = git("write-tree")
        commit = git("commit-tree", tree, data=b"Bluefin Server immutable platform baseline\n")
    git("update-ref", "refs/heads/baseline", commit)
    git("symbolic-ref", "HEAD", "refs/heads/baseline")
    git("config", "core.sharedRepository", "all")
    git("fsck", "--full", "--strict")
    # All contained objects are publicly readable. Root's retained generation
    # selection is the only runtime writer, and repo-server mounts this read-only.
    for path in destination.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    destination.chmod(0o755)
    return commit

def baseline_integrity(repository, commit):
    repository = Path(repository)
    files = {}
    for path in sorted(repository.rglob("*")):
        if path.is_symlink():
            raise ValueError("baseline inventory may not contain symlinks")
        if path.is_file():
            files[path.relative_to(repository).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"schema": 1, "commit": commit, "files": files}



def render(source, output):
    """Resolve stock refs; keep bootstrap authority outside the public snapshot."""
    source, output = Path(source), Path(output)
    lock = validate_source_lock(source)
    if output.exists():
        raise ValueError("output must be a fresh staging directory")
    replacements = {"@@CONSOLE_IMAGE@@": lock["images"]["console"]["ref"],
                    "@@ARGOEXEC_IMAGE@@": lock["images"]["argoexec"]["ref"]}
    resolved = {}
    for module in MODULES:
        for path in sorted((source / module).rglob("*")):
            if not path.is_file() or path.suffix not in {".yaml", ".in"}:
                continue
            relative = path.relative_to(source).as_posix().removesuffix(".in")
            text = path.read_text()
            for token, value in replacements.items():
                text = text.replace(token, value)
            resolved[relative] = text
    public = {"platform/" + name: text.encode() for name, text in resolved.items()
              if not name.endswith("kustomization.yaml") and "/crds/" not in name
              and PurePosixPath(name).name not in BOOTSTRAP_ONLY}
    # Snapshot reconciliation excludes all root security/resource contracts.
    public["platform/kustomization.yaml"] = (
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n" +
        "".join("- " + name.removeprefix("platform/") + "\n" for name in sorted(public))
    ).encode()
    if any(b"@@" in data for data in public.values()):
        raise ValueError("unresolved producer input in public baseline")
    output.mkdir(parents=True)
    commit = snapshot(output / "baseline.git", public)
    replacements["@@BASELINE_COMMIT@@"] = commit
    for path in ("namespaces.yaml", "bootstrap-rbac.yaml", "admission.yaml.in"):
        resolved[path.removesuffix(".in")] = (source / path).read_text()
    for name, text in resolved.items():
        for token, value in replacements.items():
            text = text.replace(token, value)
        if "@@" in text:
            raise ValueError("unresolved input in shipped manifest: " + name)
        target = output / "manifests" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    (output / "baseline-commit").write_text(commit + "\n")
    return commit


def platform_sbom(provenance, output):
    """An SPDX 2.3 fragment for the parent's release document, not an attestation."""
    output = Path(output)
    packages, relationships = [], []

    def package(identity, name, version, location="NOASSERTION", checksum=None, info="", purl=None):
        identifier = "SPDXRef-Platform-" + identity
        item = {"SPDXID": identifier, "name": name, "versionInfo": version,
                "downloadLocation": location, "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION", "licenseDeclared": "NOASSERTION",
                "copyrightText": "NOASSERTION", "sourceInfo": info}
        if checksum is not None:
            if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
                raise ValueError("unknown or malformed package SHA256: " + name)
            item["checksums"] = [{"algorithm": "SHA256", "checksumValue": checksum}]
        if purl is not None:
            item["externalRefs"] = [{"referenceCategory": "PACKAGE-MANAGER",
                                     "referenceType": "purl", "referenceLocator": purl}]
        packages.append(item)
        return identifier

    def relationship(origin, kind, target, comment=None):
        item = {"spdxElementId": origin, "relationshipType": kind, "relatedSpdxElement": target}
        if comment is not None:
            item["comment"] = comment
        relationships.append(item)

    def image(identity, name, ref, digest, version, info):
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest) or not ref.endswith("@" + digest):
            raise ValueError("inconsistent OCI reference/digest: " + name)
        repository = ref.rsplit("@", 1)[0]
        if ":" in repository.rsplit("/", 1)[-1]:
            repository = repository.rsplit(":", 1)[0]
        purl = ("pkg:oci/" + quote(repository.rsplit("/", 1)[-1], safe="") + "@" +
                quote(digest, safe="") + "?repository_url=" + quote(repository, safe=""))
        return package(identity, name, version, ref, digest.removeprefix("sha256:"), info, purl)

    repositories = {"cilium": "cilium/cilium", "argocd": "argoproj/argo-cd",
                    "workflows": "argoproj/argo-workflows", "native-mcp": "containers/kubernetes-mcp-server",
                    "console": "kubestellar/console", "kured": "kubereboot/kured"}
    source_ids = {}
    for name, source in sorted(provenance["sources"].items()):
        commit, version = source["commit"], source["version"]
        repository = repositories[name]
        info = "Pinned upstream source commit " + commit + "; publisher signatures were not verified."
        location = source.get("url", "https://github.com/" + repository + "/tree/" + commit)
        if "raw.githubusercontent.com" in location:
            location = re.sub(r"/(?:v)?" + re.escape(version) + r"/", "/" + commit + "/", location, count=1)
        checksum = source.get("sha256")
        source_ids[name] = package("Source-" + name, name + (" upstream resource bundle" if checksum else " upstream source"),
                                   version, location, checksum, info)
        for path, sha256 in sorted(source.get("files", {}).items()):
            reference = "reference-only upstream deployment/config source; not compiled or rendered" if not "/crds/" in path else "vendored complete CRD source"
            identifier = package("SourceFile-" + hashlib.sha256((name + "/" + path).encode()).hexdigest(),
                                 name + "/" + path, version,
                                 "https://raw.githubusercontent.com/" + repository + "/" + commit + "/" + path,
                                 sha256, info + " " + reference + ".")
            relationship(source_ids[name], "CONTAINS", identifier)
    mapping = {"cilium": "cilium", "argocd": "argocd", "workflows": "workflows", "reboot": "kured", "mcp": "native-mcp", "dashboard": "console"}
    for path, sha256 in sorted(provenance["maintained_resources"].items()):
        identifier = package("RawResource-" + hashlib.sha256(path.encode()).hexdigest(),
                             "Bluefin platform raw resource " + path, provenance["baseline_commit"],
                             checksum=sha256, info="Maintained raw source path files/server/manifests/" + path)
        source_name = mapping.get(path.partition("/")[0])
        if source_name:
            relationship(identifier, "OTHER", source_ids[source_name],
                         "Reviewed raw resource module references this pinned upstream source; not an upstream signature claim.")
        resolved = output / "manifests" / path.removesuffix(".in")
        if resolved.is_file():
            resolved_id = package("ResolvedResource-" + hashlib.sha256(path.encode()).hexdigest(),
                                  "Bluefin platform packaged resource " + path.removesuffix(".in"), provenance["baseline_commit"],
                                  checksum=hashlib.sha256(resolved.read_bytes()).hexdigest(),
                                  info="Resolved public output manifests/" + path.removesuffix(".in"))
            relationship(resolved_id, "GENERATED_FROM", identifier)
    image_sources = {"argocd": "argocd", "cilium": "cilium", "cilium-operator": "cilium",
                     "workflow-controller": "workflows", "argoexec": "workflows", "kured": "kured", "native-mcp": "native-mcp", "console": "console"}
    for name, entry in sorted(provenance["images"].items()):
        tagged = entry["ref"].rsplit("@", 1)[0]
        version = tagged.rsplit(":", 1)[1] if ":" in tagged.rsplit("/", 1)[-1] else entry["digest"]
        identifier = image("Image-" + name, name + " upstream OCI image", entry["ref"], entry["digest"], version,
                           "Observed immutable upstream OCI index digest; not a filesystem checksum, publisher signature or verified build attestation.")
        if name in image_sources:
            relationship(identifier, "OTHER", source_ids[image_sources[name]],
                         "Named release image and vendored upstream source share the recorded version; no verified build attestation asserted.")
    package("ProvenanceLock", "Bluefin platform provenance lock", provenance["baseline_commit"],
            checksum=hashlib.sha256((output / "platform-lock.json").read_bytes()).hexdigest(),
            info="Actual packaged platform-lock.json bytes bind vendored resources, source commits, immutable image refs and baseline commit. No runtime compatibility attestation.")
    return {"packages": packages, "relationships": relationships}


def produce(source, output):
    commit = render(source, output)
    source, output = Path(source), Path(output)
    (output / "baseline-integrity.json").write_text(json.dumps(
        baseline_integrity(output / "baseline.git", commit), sort_keys=True, indent=2) + "\n")
    provenance = json.loads((source / "source-lock.json").read_text())
    provenance["source_lock_sha256"] = canonical_hash(provenance)
    provenance["baseline_commit"] = commit
    provenance["baseline_integrity_sha256"] = hashlib.sha256((output / "baseline-integrity.json").read_bytes()).hexdigest()
    (output / "platform-lock.json").write_text(json.dumps(provenance, sort_keys=True, indent=2) + "\n")
    fragment = platform_sbom(provenance, output)
    (output / "sbom-packages.json").write_text(json.dumps(fragment, sort_keys=True, indent=2) + "\n")
    return commit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).parent)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(produce(args.source, args.output))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
