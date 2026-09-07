# k0s Sysext with Native Argo CD & KubeStellar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completely replace k3s with a k0s systemd-sysext packaging out-of-the-box declarative Argo CD and KubeStellar raw YAML manifest stacks, updating all tooling, tests, and documentation.

**Architecture:** A systemd-sysext EROFS image (`k0s-<version>.raw`) containing the upstream statically-linked k0s binary, `k0scontroller.service`, and immutable manifests in `/usr/share/k0s/manifests/`. `systemd-tmpfiles` recursively copies manifests to `/var/lib/k0s/manifests/` on boot, where k0s's native manifest deployer auto-reconciles Argo CD and KubeStellar without Helm.

**Tech Stack:** BuildStream 2, EROFS, systemd-sysext, systemd-tmpfiles, k0s, Kubernetes raw manifests.

**Spec:** `docs/superpowers/specs/2026-09-06-k0s-sysext-argo-kubestellar-design.md`

## Global Constraints

- k0s version: Kubernetes 1.36.4, k0s patch 0 (upstream tag `v1.36.4+k0s.0`, asset version `1.36.4-k0s.0`).
- Upstream AMD64 binary SHA256: `ca1e9e68107335846e8296777fce2ccd654284e6265b4b5d32c34ead872af98f`.
- Hard rule 4: No shell in the running OS DDI image.
- Single source of truth for version: `include/k0s.yml`.
- All manual BST elements executing commands must depend on `base/base-stack.bst` for `/bin/sh` and coreutils under FSDK 26.08.
- Sysupdate transfer target must declare `CurrentSymlink=k0s.raw` for `systemd-sysext` image name matching.
- No Helm: `--disable-components=helm` in `k0scontroller.service`.
- All unit tests must pass; `just validate` must pass.

---

### Task 1: Version Include & Binary Import Element

**Files:**
- Create: `include/k0s.yml`
- Create: `elements/k0s/k0s-bin.bst`
- Test: `tests/unit/test_k0s_version.py`

**Interfaces:**
- Produces: `include/k0s.yml` defining `%{k0s-upstream-tag}` and `%{k0s-version}`; `elements/k0s/k0s-bin.bst` staging `/usr/bin/k0s`.

- [x] **Step 1: Write the failing unit test**

Create `tests/unit/test_k0s_version.py`:
```python
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_k0s_version_ssot():
    k0s_yml = ROOT / "include" / "k0s.yml"
    assert k0s_yml.is_file(), "include/k0s.yml missing"
    data = yaml.safe_load(k0s_yml.read_text())
    vars_ = data.get("variables", {})
    assert vars_.get("k0s-k8s-version") == "1.36.4"
    assert vars_.get("k0s-patch") == "0"
    assert vars_.get("k0s-version") == "%{k0s-k8s-version}-k0s.%{k0s-patch}"


def test_k0s_bin_element():
    bin_bst = ROOT / "elements" / "k0s" / "k0s-bin.bst"
    assert bin_bst.is_file(), "elements/k0s/k0s-bin.bst missing"
    content = bin_bst.read_text()
    assert "base/base-stack.bst" in content
    assert "github:k0sproject/k0s/releases/download/" in content
    assert "ca1e9e68107335846e8296777fce2ccd654284e6265b4b5d32c34ead872af98f" in content
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_k0s_version.py -v`
Expected: FAIL (files missing)

- [x] **Step 3: Implement `include/k0s.yml` and `elements/k0s/k0s-bin.bst`**

Create `include/k0s.yml`:
```yaml
# Single source of truth for the k0s version axis.
#
# Pinned to k0s release v1.36.4+k0s.0.
# Derived variables:
#   %{k0s-k8s-version}    upstream Kubernetes version       1.36.4
#   %{k0s-patch}          upstream k0s patch suffix number  0
#   %{k0s-upstream-tag}   GitHub release tag, URL-escaped   v1.36.4%2Bk0s.0
#   %{k0s-version}        asset / extension-release version 1.36.4-k0s.0
variables:
  k0s-k8s-version: "1.36.4"
  k0s-patch: "0"

  k0s-upstream-tag: "v%{k0s-k8s-version}%2Bk0s.%{k0s-patch}"
  k0s-version: "%{k0s-k8s-version}-k0s.%{k0s-patch}"
```

Create `elements/k0s/k0s-bin.bst`:
```yaml
kind: manual
description: |
  Import the upstream k0s release binary.
  Pinned to v1.36.4+k0s.0 for x86_64.

(@): include/k0s.yml

build-depends:
  - base/base-stack.bst

variables:
  strip-binaries: ""

sources:
  - kind: remote
    url: github:k0sproject/k0s/releases/download/%{k0s-upstream-tag}/k0s-%{k0s-upstream-tag}-amd64
    ref: ca1e9e68107335846e8296777fce2ccd654284e6265b4b5d32c34ead872af98f

config:
  install-commands:
    - |
      if [ "%{arch}" != "x86_64" ]; then
        echo "ERROR: elements/k0s/k0s-bin.bst pins the upstream k0s amd64 binary;" >&2
        echo "       arch=%{arch} has no pinned source." >&2
        exit 1
      fi
    - install -D -m 0755 k0s-%{k0s-upstream-tag}-amd64 "%{install-root}/usr/bin/k0s"
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_k0s_version.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add include/k0s.yml elements/k0s/k0s-bin.bst tests/unit/test_k0s_version.py
git commit -m "feat(k0s): add k0s version include and binary import element"
```

---

### Task 2: Service Unit, tmpfiles.d & Native Manifest Stacks

**Files:**
- Create: `files/k0s/sysext/k0scontroller.service`
- Create: `files/k0s/sysext/extension-release.k0s`
- Create: `files/k0s/sysext/k0s-manifests.conf`
- Create: `files/k0s/manifests/argocd/install.yaml`
- Create: `files/k0s/manifests/kubestellar/00-kubeflex-crds.yaml`
- Create: `files/k0s/manifests/kubestellar/10-kubeflex-operator.yaml`
- Create: `files/k0s/manifests/kubestellar/20-postgres.yaml`
- Create: `files/k0s/manifests/kubestellar/30-kubestellar-core.yaml`
- Create: `files/k0s/manifests/kubestellar/40-kubestellar-console.yaml`
- Test: `tests/unit/test_k0s_manifests.py`

**Interfaces:**
- Produces: Systemd unit, tmpfiles config, and raw YAML stacks in `files/k0s/`.

- [x] **Step 1: Write the failing unit test**

Create `tests/unit/test_k0s_manifests.py`:
```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_k0s_service_unit():
    unit = ROOT / "files" / "k0s" / "sysext" / "k0scontroller.service"
    assert unit.is_file(), "k0scontroller.service missing"
    text = unit.read_text()
    assert "--disable-components=helm" in text
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
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_k0s_manifests.py -v`
Expected: FAIL

- [x] **Step 3: Create files/k0s/sysext and files/k0s/manifests**

1. Create `files/k0s/sysext/extension-release.k0s`:
```ini
NAME=k0s
ID=_any
```

2. Create `files/k0s/sysext/k0scontroller.service`:
```ini
[Unit]
Description=k0s - Zero Friction Kubernetes
Documentation=https://docs.k0sproject.io
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/k0s controller --enable-worker --single --disable-components=helm
Restart=always
RestartSec=5s
Delegate=yes
KillMode=process
LimitNOFILE=1048576
LimitNPROC=infinity
LimitCORE=infinity
TasksMax=infinity

[Install]
WantedBy=multi-user.target
```

3. Create `files/k0s/sysext/k0s-manifests.conf`:
```ini
# Seed Bluefin k0s declarative stacks into /var/lib/k0s/manifests/
d /var/lib/k0s/manifests 0755 root root - -
C+ /var/lib/k0s/manifests/argocd - - - - /usr/share/k0s/manifests/argocd
C+ /var/lib/k0s/manifests/kubestellar - - - - /usr/share/k0s/manifests/kubestellar
```

4. Populate `files/k0s/manifests/argocd/install.yaml` and `files/k0s/manifests/kubestellar/*.yaml` with declarative YAMLs.

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_k0s_manifests.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add files/k0s/ tests/unit/test_k0s_manifests.py
git commit -m "feat(k0s): add k0s systemd unit, tmpfiles seeder, and manifest stacks"
```

---

### Task 3: Sysext Assembly Element (`elements/oci/k0s-sysext.bst`)

**Files:**
- Create: `elements/oci/k0s-sysext.bst`
- Test: `pytest tests/unit/test_build_depends.py`

**Interfaces:**
- Consumes: `elements/k0s/k0s-bin.bst`, `files/k0s/sysext/`, `files/k0s/manifests/`.
- Produces: `dist/sysext/k0s-<version>.raw` and `k0s-<version>.raw.zst`.

- [x] **Step 1: Write `elements/oci/k0s-sysext.bst`**

```yaml
kind: manual
description: |
  Produce a systemd-sysext extension image for k0s.

  Output: k0s-<k0s-version>.raw, k0s-<k0s-version>.raw.zst, and SHA256SUMS.
  Contains /usr/bin/k0s, k0scontroller.service, tmpfiles.d/k0s-manifests.conf,
  and /usr/share/k0s/manifests/ (Argo CD and KubeStellar).

(@):
  - include/arch.yml
  - include/k0s.yml

build-depends:
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/erofs-utils.bst
  - freedesktop-sdk.bst:components/xz.bst
  - freedesktop-sdk.bst:components/zstd.bst
  - filename: k0s/k0s-bin.bst
    config:
      location: /

sources:
  - kind: local
    path: files/k0s/sysext
    directory: sysext-src
  - kind: local
    path: files/k0s/manifests
    directory: manifests-src
  - kind: local
    path: files/os/issue.d/40-kubestellar.issue
    directory: issue-src

variables:
  strip-binaries: ""

config:
  install-commands:
    - |
      set -euo pipefail
      OUT="%{install-root}"
      FNAME="k0s-%{k0s-version}.raw"

      if [ "%{arch}" != "x86_64" ]; then
        echo "ERROR: elements/oci/k0s-sysext.bst only supports x86_64 (got %{arch})" >&2
        exit 1
      fi

      mkdir -p sysext/usr/bin
      mkdir -p sysext/usr/lib/systemd/system
      mkdir -p sysext/usr/lib/extension-release.d
      mkdir -p sysext/usr/lib/tmpfiles.d
      mkdir -p sysext/usr/lib/issue.d
      mkdir -p sysext/usr/share/k0s/manifests
      mkdir -p "${OUT}"

      # Stage k0s binary
      cp -a /usr/bin/k0s sysext/usr/bin/k0s
      chmod 0755 sysext/usr/bin/k0s

      # Stage systemd service
      cp -a sysext-src/k0scontroller.service sysext/usr/lib/systemd/system/

      # Stage extension release metadata
      cp -a sysext-src/extension-release.k0s sysext/usr/lib/extension-release.d/
      echo "VERSION_ID=%{k0s-version}" >> sysext/usr/lib/extension-release.d/extension-release.k0s
      echo "ARCHITECTURE=%{systemd-arch}" >> sysext/usr/lib/extension-release.d/extension-release.k0s

      # Stage tmpfiles seeding configuration
      cp -a sysext-src/k0s-manifests.conf sysext/usr/lib/tmpfiles.d/

      # Stage console issue banner
      cp -a issue-src/40-kubestellar.issue sysext/usr/lib/issue.d/

      # Stage manifest stacks
      cp -a manifests-src/* sysext/usr/share/k0s/manifests/

      # Build EROFS image
      mkfs.erofs -d0 "${OUT}/${FNAME}" sysext

      # Compress release asset
      zstd -T0 -19 -q "${OUT}/${FNAME}" -o "${OUT}/${FNAME}.zst"

      (
        cd "${OUT}"
        sha256sum --binary "${FNAME}.zst" > SHA256SUMS
      )
```

- [x] **Step 2: Run tests to verify build dependencies invariant**

Run: `pytest tests/unit/test_build_depends.py -v`
Expected: PASS

- [x] **Step 3: Commit**

```bash
git add elements/oci/k0s-sysext.bst
git commit -m "feat(k0s): add k0s-sysext assembly element"
```

---

### Task 4: Systemd-Sysupdate Transfer (`files/os/sysupdate.d/70-k0s.transfer`)

**Files:**
- Create: `files/os/sysupdate.d/70-k0s.transfer`
- Delete: `files/os/sysupdate.d/70-k3s.transfer`

- [x] **Step 1: Create `files/os/sysupdate.d/70-k0s.transfer`**

```ini
[Transfer]

[Source]
Type=url-file
Path=https://github.com/projectbluefin/server/releases/latest/download/
MatchPattern=k0s-@v.raw.zst

[Target]
Type=regular-file
Path=/var/lib/extensions
MatchPattern=k0s-@v.raw
CurrentSymlink=k0s.raw
Mode=0644
```

- [x] **Step 2: Delete `files/os/sysupdate.d/70-k3s.transfer`**

```bash
git rm files/os/sysupdate.d/70-k3s.transfer
```

- [x] **Step 3: Commit**

```bash
git add files/os/sysupdate.d/70-k0s.transfer
git commit -m "feat(sysupdate): replace 70-k3s.transfer with 70-k0s.transfer"
```

---

### Task 5: Tooling, Workflows & Scripts

**Files:**
- Modify: `Justfile:39-44`
- Modify: `files/os/justfile:6-51`
- Modify: `.github/workflows/build.yml:76-80`
- Modify: `.pre-commit-config.yaml:21-26`
- Create: `.github/scripts/check-k0s-version.py`
- Delete: `.github/scripts/check-k3s-version.py`

- [x] **Step 1: Update `Justfile` sysext recipes**

Change `build-sysext` and `export-sysext` to target `oci/k0s-sysext.bst` and extract `k0s-*`.

- [x] **Step 2: Update `files/os/justfile` (`just k8s`)**

Update `just k8s` to check `/var/lib/extensions/k0s.raw` and start `k0scontroller.service`.

- [x] **Step 3: Update `.github/workflows/build.yml`**

Change step name to `Build and export k0s systemd-sysext`.

- [x] **Step 4: Create `.github/scripts/check-k0s-version.py` and delete check-k3s-version.py**

Create `check-k0s-version.py` verifying that `k0s-version` is defined in `include/k0s.yml` and consumers reference it.

- [x] **Step 5: Update `.pre-commit-config.yaml`**

Point hook entry to `.github/scripts/check-k0s-version.py`.

- [x] **Step 6: Commit**

```bash
git add Justfile files/os/justfile .github/ .pre-commit-config.yaml
git commit -m "chore(tooling): update Justfile, CI, and pre-commit hooks for k0s"
```

---

### Task 6: Purge k3s Files

**Files:**
- Delete: `include/k3s.yml`
- Delete: `elements/k3s/`
- Delete: `elements/oci/k3s-sysext.bst`
- Delete: `files/k3s/`
- Delete: `tests/unit/test_k3s_version.py`

- [x] **Step 1: Remove k3s files from git**

```bash
git rm -r include/k3s.yml elements/k3s/ elements/oci/k3s-sysext.bst files/k3s/ tests/unit/test_k3s_version.py
```

- [x] **Step 2: Commit**

```bash
git commit -m "chore(purge): remove deprecated k3s elements, configs, and tests"
```

---

### Task 7: Documentation Purge & Rewrite

**Files:**
- Create: `docs/skills/k0s-sysext.md`
- Create: `docs/skills/k0s-sysext-ops.md`
- Delete: `docs/skills/k3s-sysext.md`
- Delete: `docs/skills/k3s-sysext-ops.md`
- Modify: `docs/skills/index.md`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: cross-linking docs (`docs/skills/factory-integration.md`, `docs/skills/system-containers.md`, `docs/skills/systemd-sysext-extensions.md`, `docs/skills/gap-analysis-distros.md`, `SECURITY.md`)

- [x] **Step 1: Write `docs/skills/k0s-sysext.md` and `k0s-sysext-ops.md`**

Document k0s sysext build, layout, native manifest deployer (`/var/lib/k0s/manifests/`), and service management.

- [x] **Step 2: Update skill index and references**

Update `docs/skills/index.md`, `AGENTS.md`, and `README.md` to reference `k0s-sysext.md`.

- [x] **Step 3: Update cross-linking skills and purge stale k3s links**

Update `factory-integration.md`, `system-containers.md`, `systemd-sysext-extensions.md`, and `SECURITY.md`.

- [x] **Step 4: Commit**

```bash
git add docs/ AGENTS.md README.md SECURITY.md
git commit -m "docs: document k0s sysext, update skill routing, and purge k3s references"
```

---

### Task 8: Full Verification

**Files:**
- All touched files

- [x] **Step 1: Run pytest on all unit tests**

Run: `pytest tests/unit/ -v`
Expected: 100% PASS

- [x] **Step 2: Run docs link check**

Run: `python3 .github/scripts/docs-checks.py`
Expected: 0 broken internal links

- [x] **Step 3: Run pre-commit checks**

Run: `pre-commit run --all-files`
Expected: All hooks PASS

- [x] **Step 4: Run merge-contract element graph validation**

Run: `just validate`
Expected: PASS (zero dangling references, clean element graph)
