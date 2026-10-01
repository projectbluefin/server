kind: collect_manifest
description: |
  SPDX 2.3 SBOM of one release set, written by the collect_manifest plugin
  that freedesktop-sdk uses for its own CVE manifests
  (buildstream-plugins-community, source provenance API).

  One SPDX package per source of every element in the runtime closure of
  the dependencies below: name, version (from the git-describe ref or the
  tarball name), download location and source kind. Local sources are
  listed by path.

  The dependencies are the payload of the release set, not the tools that
  assemble it: the /usr and initrd stacks, the kernel, and the sysext
  payloads. Build-only elements (signing keys, image tooling) are not
  runtime dependencies of these and never appear.

  A sysext only build-depends on the upstream binaries or source it
  stages, which the plugin does not follow, so each is listed twice: the
  oci/*-sysext.bst element for its own local sources (units,
  extension-release, config), and the element it stages them from.

  oci/bluefin-server-image.bst stamps creationInfo.created from the
  sandbox's fixed SOURCE_DATE_EPOCH (always 2011-11-11T11:11:11Z, a
  reproducibility placeholder rather than a build time) and ships the
  result as bluefin-server_<ver>.spdx.json inside the signed SHA256SUMS.

(@):
- include/image.yml

build-depends:
- bluefin-server/os-stack.bst
- bluefin-server/initrd/initrd-stack.bst
- freedesktop-sdk.bst:components/linux.bst
- oci/k0s-sysext.bst
- k0s/k0s-bin.bst
- oci/kubestellar-sysext.bst
- oci/kubeadm-sysext.bst
- kubeadm/kubeadm-bin.bst
- oci/zfs-sysext.bst
- zfs/openzfs.bst
- server/kubernetes-image.bst
- server/containerd-image.bst
- server/platform-payload.bst
- oci/server-sysext.bst
- oci/nvidia-open-595-sysext.bst
- nvidia/nvidia-open-595.bst
- oci/nvidia-container-toolkit-sysext.bst
- nvidia/nvidia-container-toolkit.bst

config:
  path: /bluefin-server.spdx.json
  output-type: spdx
  spdx-info:
    name: bluefin-server-%{image-version}
    data-license: CC0-1.0
    doc-namespace: https://github.com/projectbluefin/server/spdx/bluefin-server-%{image-version}
    creators:
    - "Organization: Project Bluefin"
    - "Tool: buildstream-plugins-community-collect_manifest"
