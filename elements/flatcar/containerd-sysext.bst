kind: manual
description: |
  Flatcar's containerd system extension, shipped as a second sysext alongside
  oci/kubernetes-sysext.bst.

  Output: /containerd-flatcar.raw — Flatcar's upstream image, repacked with one
  edited field in its extension-release (see "Version decoupling" below).

  The name is load-bearing and must not be shortened. systemd-sysext resolves an
  image's metadata by stem: an extension merged as <name>.raw is required to
  carry /usr/lib/extension-release.d/extension-release.<name>. This image ships
  extension-release.containerd-flatcar, so renaming it to containerd.raw makes
  systemd-sysext look for extension-release.containerd, fail to find it, and
  refuse the extension — silently, at boot, long after the build went green.
  tests/unit/test_sysupdate_transfers.py encodes the same invariant for the
  Kubernetes sysext, and tests/unit/test_seeded_sysext_names.py now covers the
  installer-seeded path this element feeds.

  Why import rather than build: FSDK 26.08 ships no containerd component at all
  (see docs/superpowers/specs/2026-09-19-flatcar-runtime-parity.md, which records
  `no elements/components/containerd.bst` in the pinned junction), so there is
  nothing to compose from. Flatcar publishes containerd as a systemd-sysext, the
  same delivery mechanism this repository already uses for Kubernetes, and the
  image is self-contained:

    /usr/bin/containerd, containerd-shim-runc-v2, ctr, runc
    /usr/lib/systemd/system/containerd.service
    /usr/lib/systemd/system/multi-user.target.wants/containerd.service
    /usr/lib/systemd/system/multi-user.target.d/10-containerd-service.conf
    /usr/lib/extension-release.d/extension-release.containerd-flatcar
    /usr/share/containerd/config.toml, config-cgroupfs.toml
    /usr/share/SLSA/*.json.zst                (containerd 2.1.5, runc 1.3.3)

  It carries its own `multi-user.target.wants` symlink, so containerd.service is
  enabled by the merge itself — no preset is needed on our side. That is what
  satisfies `Requires=containerd.service` in
  files/os/systemd/system/kubeadm-init.service.

  Version decoupling. Upstream's extension-release declares ID=flatcar and
  VERSION_ID=4593.2.5, and systemd-sysext refuses an extension whose ID/VERSION_ID
  do not match the host's os-release. elements/bluefin-server/os-release-flatcar.bst
  writes VERSION_ID=%{flatcar-version}, so they agree at install time — and stop
  agreeing the moment flatcar-version is bumped.

  That divergence is an OTA hazard, not a build-time one. A build-time mismatch
  is loud: the source URL embeds %{flatcar-version}, so bumping it changes the
  URL and the pinned ref below fails to resolve. The danger is an already
  installed machine. /var survives an A/B root update, so a host updated to a DDI
  built from a newer flatcar-version boots with a new os-release while
  /var/lib/extensions/containerd-flatcar.raw still declares the old VERSION_ID.
  systemd-sysext then refuses the merge, containerd.service disappears, and
  kubeadm-init.service fails — the cluster goes down after a routine OS update.
  kubernetes.raw is immune because 70-kubernetes.transfer replaces it in lockstep;
  containerd has no such transfer. That absence is also the runtime's patch path
  gap — a seeded image that never updates holds this containerd/runc until the
  host is reinstalled — and is tracked as open item 3 of
  docs/superpowers/specs/2026-09-19-kubernetes-cutover-design.md.

  So the image is repacked with a single field changed: ID=_any. That is the same
  decoupling files/kubernetes/sysext/extension-release.kubernetes uses, for the
  same stated reason — "the sysext ships independently of the host os-release
  version and would otherwise be rejected after an OS update"
  (tests/unit/test_sysupdate_transfers.py). Nothing else in the image is touched:
  the binaries, containerd.service, the target.wants symlink, the config.toml
  pair and the SLSA provenance documents are repacked byte-for-byte.

  elements/flatcar/container-runtime-reference-sysexts.bst also imports this file.
  That element is the parity oracle and additionally pulls podman and docker,
  which this image does not ship; no shipped target depends on it. This element
  exists so the shipped path imports exactly one runtime and nothing else.

(@):
  - include/arch.yml
  - include/flatcar.yml

build-depends:
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/squashfs-tools.bst

variables:
  strip-binaries: ""

sources:
  - kind: remote
    url: flatcar:stable/%{flatcar-board}/%{flatcar-version}/rootfs-included-sysexts/containerd-flatcar.raw
    filename: containerd-flatcar.raw
    ref: 78e38344ac490004b9fa4c7da38bbfcffc393146aa990379aff7b5c09589f809

config:
  install-commands:
    - |
      set -euo pipefail

      RELEASE="usr/lib/extension-release.d/extension-release.containerd-flatcar"

      unsquashfs -no-xattrs -d unpacked containerd-flatcar.raw

      # Fail loudly if upstream ever renames the metadata file: a silently
      # missing extension-release produces an image systemd-sysext refuses.
      test -f "unpacked/${RELEASE}"

      # NAME must equal the image stem, ID=_any decouples the merge from the
      # host's os-release version. SYSEXT_VERSION_ID keeps the Flatcar release
      # readable off a merged /usr for provenance.
      cat > "unpacked/${RELEASE}" <<EOF
      NAME=containerd-flatcar
      ID=_any
      ARCHITECTURE=%{systemd-arch}
      SYSEXT_VERSION_ID=%{flatcar-version}
      EOF

      mksquashfs unpacked repacked.raw -noappend -no-xattrs -comp zstd -b 524288

      install -D -m 0644 repacked.raw "%{install-root}/containerd-flatcar.raw"
