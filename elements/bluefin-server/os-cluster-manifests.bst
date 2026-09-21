kind: manual
description: |
  Stage the cluster bootstrap seed and the Argo CD-owned manifest tree.

  Output:
    /usr/share/bluefin/seed/     four kustomize phases applied by
                                 bluefin-cluster-bootstrap.service
    /usr/share/bluefin/cluster/  the tree bluefin-cluster-repo.service commits
                                 to /var/lib/bluefin/cluster.git, served to Argo
                                 by the in-cluster git-daemon

  Two upstream manifests are fetched and sha256-pinned here rather than vendored
  into the repository. Both are large machine-generated files that no reviewer
  reads on a bump, and a stale hand-copy silently drops CRDs and RBAC. Their
  kustomization.yaml lives in files/cluster/, so the customisation is reviewable
  even though the payload is not.

build-depends:
  # Base runtime providing /bin/sh, install and cp in the sandbox.
  - base/base-stack.bst

sources:
  - kind: local
    path: files/cluster/seed
    directory: seed-src
  - kind: local
    path: files/cluster/manifests
    directory: cluster-src

  # Argo CD Core. core-install.yaml, not install.yaml: Core drops argocd-server,
  # argocd-dex-server and argocd-notifications-controller, which removes a second
  # authenticated web surface from the appliance.
  - kind: remote
    url: githubraw:argoproj/argo-cd/v3.5.3/manifests/core-install.yaml
    filename: core-install.yaml
    directory: argocd-src
    ref: 1a87025d8eb2eae621653fd312fb9ca51df1b4b3b6992a030e3a9ef38e45c448

  # cert-manager. Issues the appliance's certificates in-cluster, replacing the
  # build-time self-signed key that used to be generated into the sysext.
  - kind: remote
    url: github:cert-manager/cert-manager/releases/download/v1.21.2/cert-manager.yaml
    filename: cert-manager.yaml
    directory: certmanager-src
    ref: e03b668ec8675214af6b0a671699d088f2601fa3878e0dbe1b41d3feafd1879f

# This element stages YAML only. FSDK's default strip-commands shell out to
# freedesktop-sdk-stripper, which base/base-stack.bst does not provide, so the
# default turns a no-op into `command not found` (exit 127). Same contract as
# os-countme.bst, os-image-info.bst and os-release-flatcar.bst.
variables:
  strip-binaries: ""

config:
  install-commands:
    - |
      set -euo pipefail
      SEED="%{install-root}/usr/share/bluefin/seed"
      CLUSTER="%{install-root}/usr/share/bluefin/cluster"

      mkdir -p "${SEED}" "${CLUSTER}"

      # Seed phases, applied in name order by bluefin-cluster-bootstrap.service.
      cp -a seed-src/. "${SEED}/"

      # Argo CD-owned tree, committed to the bare repo on first boot.
      cp -a cluster-src/. "${CLUSTER}/"

      # Drop the pinned upstream manifests next to the kustomization.yaml that
      # patches them. Each is named by its kustomization's resources: entry.
      install -m 0644 argocd-src/core-install.yaml "${SEED}/10-argocd-core/core-install.yaml"
      install -m 0644 certmanager-src/cert-manager.yaml "${CLUSTER}/cert-manager/cert-manager.yaml"
