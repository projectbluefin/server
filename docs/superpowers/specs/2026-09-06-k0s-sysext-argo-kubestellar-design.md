# Design Spec: k0s systemd-sysext with Native Argo CD & KubeStellar Manifests

## Context & Purpose

Bluefin Server produces an immutable, distroless Linux server OS payload (`bluefin-server-ddi.bst`), an offline installer (`bluefin-server-installer.bst`), and an optional decoupled Kubernetes system extension (`systemd-sysext`).

This specification defines the complete replacement ("purge") of k3s with **k0s** across the entire project repository. k0s provides a single statically-linked binary that embeds the Kubernetes control plane, worker runtime (`containerd`, `runc`), and a native manifest deployer that watches `/var/lib/k0s/manifests/`.

Along with k0s, this extension packages out-of-the-box (OOTB) declarative raw YAML manifest stacks for **Argo CD** and **KubeStellar** (including KubeFlex, PostgreSQL, and KubeStellar Console), completely eliminating Helm dependencies and imperative installer scripts while strictly honoring Bluefin Server's read-only immutable `/usr` architecture.

---

## Architecture & Sysext Layout

### 1. File Structure within `k0s.raw`

The `k0s-<k0s-version>.raw` EROFS extension image overlays the read-only host `/usr` filesystem:

```
/usr/bin/k0s                                         # Statically-linked upstream k0s binary
/usr/lib/systemd/system/k0scontroller.service        # Single-node controller + worker unit
/usr/lib/extension-release.d/extension-release.k0s   # sysext metadata (ID=_any, VERSION_ID, ARCHITECTURE)
/usr/lib/tmpfiles.d/k0s-manifests.conf               # systemd-tmpfiles seeding configuration
/usr/share/k0s/manifests/argocd/install.yaml         # Raw Argo CD declarative manifests
/usr/share/k0s/manifests/kubestellar/*.yaml          # Raw KubeStellar (KubeFlex, Postgres, Core, Console)
```

### 2. Runtime Boot & Manifest Seeding Flow

1. **Extension Discovery & Merge**:
   - `systemd-sysext.service` merges `/var/lib/extensions/k0s-*.raw` into `/usr`.
2. **Declarative Seeding (`systemd-tmpfiles`)**:
   - `/usr/lib/tmpfiles.d/k0s-manifests.conf` ensures:
     ```ini
     d /var/lib/k0s/manifests 0755 root root - -
     C+ /var/lib/k0s/manifests/argocd - - - - /usr/share/k0s/manifests/argocd
     C+ /var/lib/k0s/manifests/kubestellar - - - - /usr/share/k0s/manifests/kubestellar
     ```
   - On boot, `systemd-tmpfiles-setup.service` recursively copies the immutable manifests from `/usr/share/k0s/manifests/` into the mutable `/var/lib/k0s/manifests/` directory if not already present.
3. **Service Execution**:
   - `k0scontroller.service` starts `/usr/bin/k0s controller --enable-worker --single`.
4. **Autonomous Reconciliation**:
   - k0s's internal manifest deployer scans top-level stack directories under `/var/lib/k0s/manifests/` (`argocd/` and `kubestellar/`).
   - All `.yaml` resources are automatically applied to the cluster without Helm or manual `kubectl apply`.
   - Any administrator overrides dropped into `/var/lib/k0s/manifests/` take immediate effect and are preserved across OS updates.

---

## Detailed Component Specifications

### 1. Single Source of Truth (`include/k0s.yml`)

Replaces `include/k3s.yml`. Controls the k0s release axis independently of the OS release axis:

```yaml
variables:
  k0s-k8s-version: "1.36.4"
  k0s-patch: "0"

  k0s-upstream-tag: "v%{k0s-k8s-version}%2Bk0s.%{k0s-patch}"
  k0s-version: "%{k0s-k8s-version}-k0s.%{k0s-patch}"
```

### 2. Binary Import Element (`elements/k0s/k0s-bin.bst`)

Imports the upstream pre-built static binary `k0s-v1.36.4+k0s.0-amd64`:
- Remote URL: `github:k0sproject/k0s/releases/download/%{k0s-upstream-tag}/k0s-%{k0s-upstream-tag}-amd64`
- SHA256 ref: `ca1e9e68107335846e8296777fce2ccd654284e6265b4b5d32c34ead872af98f`
- Fails closed if `%{arch} != "x86_64"`.
- Installs to `%{install-root}/usr/bin/k0s` (mode `0755`).

### 3. Sysext Assembly Element (`elements/oci/k0s-sysext.bst`)

Builds the uncompressed EROFS raw disk image (`k0s-%{k0s-version}.raw`), compresses it with `zstd -T0 -19` (`k0s-%{k0s-version}.raw.zst`), and computes `SHA256SUMS`.
- Sources include local files in `files/k0s/sysext` and `files/k0s/manifests`.
- Writes extension release metadata with `ID=_any`, `VERSION_ID=%{k0s-version}`, and `ARCHITECTURE=%{systemd-arch}`.

### 4. Systemd Unit (`files/k0s/sysext/k0scontroller.service`)

```ini
[Unit]
Description=k0s - Zero Friction Kubernetes
Documentation=https://docs.k0sproject.io
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/k0s controller --enable-worker --single
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

### 5. Native Manifest Stacks (`files/k0s/manifests/`)

- `files/k0s/manifests/argocd/install.yaml`: Standard declarative manifests for Argo CD.
- `files/k0s/manifests/kubestellar/`:
  - `00-kubeflex-crds.yaml`
  - `10-kubeflex-operator.yaml`
  - `20-postgres.yaml`
  - `30-kubestellar-core.yaml`
  - `40-kubestellar-console.yaml`

### 6. Systemd-Sysupdate Transfer (`files/os/sysupdate.d/70-k0s.transfer`)

Replaces `70-k3s.transfer`:
```ini
[Transfer]
ProtectVersion=%A

[Source]
Type=url-file
Path=https://github.com/projectbluefin/server/releases/latest/download/
MatchPattern=k0s-@v.raw.zst

[Target]
Type=regular-file
Path=/var/lib/extensions
MatchPattern=k0s-@v.raw
Mode=0644
```

---

## Purge & Replacement Matrix

| Old k3s Component | Action | New k0s Component |
|---|---|---|
| `include/k3s.yml` | **Deleted** | `include/k0s.yml` |
| `elements/k3s/k3s-bin.bst` | **Deleted** | `elements/k0s/k0s-bin.bst` |
| `elements/oci/k3s-sysext.bst` | **Deleted** | `elements/oci/k0s-sysext.bst` |
| `files/k3s/` | **Deleted** | `files/k0s/` |
| `files/os/sysupdate.d/70-k3s.transfer` | **Deleted** | `files/os/sysupdate.d/70-k0s.transfer` |
| `.github/scripts/check-k3s-version.py` | **Deleted** | `.github/scripts/check-k0s-version.py` |
| `tests/unit/test_k3s_version.py` | **Deleted** | `tests/unit/test_k0s_version.py` |
| `docs/skills/k3s-sysext.md` | **Deleted** | `docs/skills/k0s-sysext.md` |
| `docs/skills/k3s-sysext-ops.md` | **Deleted** | `docs/skills/k0s-sysext-ops.md` |
| `Justfile` (`build-sysext`, `export-sysext`) | **Updated** | Refers to `oci/k0s-sysext.bst` |
| `.github/workflows/build.yml` | **Updated** | Builds and uploads k0s sysext |
| `AGENTS.md`, `README.md`, `docs/skills/index.md` | **Updated** | Updated skill routing and references |

---

## Verification & Testing Strategy

1. **Element Graph Validation (`just validate`)**:
   - Verifies all BST element references resolve cleanly with zero dangling k3s nodes.
2. **Unit Tests (`pytest tests/unit/`)**:
   - `test_k0s_version.py`: Verifies single-source-of-truth invariants across `include/k0s.yml`, `k0s-bin.bst`, and `k0s-sysext.bst`.
   - `test_build_depends.py`: Asserts `k0s-bin.bst` depends on `base/base-stack.bst`.
   - `test_k0s_manifests.py`: Verifies `tmpfiles.d/k0s-manifests.conf` matches stack directory names and YAML extensions.
3. **Sysext Build Verification (`just build-sysext && just export-sysext`)**:
   - Confirms `k0s-*.raw` and `k0s-*.raw.zst` build and export successfully into `dist/sysext/`.
4. **Bootstream & E2E Validation**:
   - KubeVirt VM boot test loading `k0s.raw` sysext.
   - Verification that `k0scontroller.service` starts and reaches `active (running)`.
   - Verification that Argo CD and KubeStellar pods reach `Running` via native manifest deployer.
