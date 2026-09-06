kind: manual
description: |
  Produce a systemd-sysext extension image for k3s.

  Output: k3s-<k3s-version>.raw, k3s-<k3s-version>.raw.zst, and
  SHA256SUMS, versioned on the k3s axis (include/k3s.yml) — not on the OS
  release axis. k3s is an independently-pinned third-party payload, and
  files/os/sysupdate.d/70-k3s.transfer treats this filename as its version
  oracle, so the filename must move exactly when the k3s binary moves.

  The image contains /usr/bin/k3s, systemd units, extension-release
  metadata, Bluefin tuning defaults, and a tmpfiles.d entry that seeds
  those defaults into /etc/rancher/k3s/config.yaml.d/.

# %{systemd-arch} — the extension-release ARCHITECTURE= value, derived from
# the `arch` option rather than hardcoded in the staged source file.
# %{k3s-version} — the asset/extension-release version, derived from the one
# pinned k3s release rather than restated per consumer.
(@):
  - include/arch.yml
  - include/k3s.yml

build-depends:
  # Core runtime for /bin/sh, coreutils, install, and sha256sum.
  - base/base-stack.bst
  # Filesystem tooling for the sysext image.
  - freedesktop-sdk.bst:components/erofs-utils.bst
  # liblzma runtime dependency of mkfs.erofs.
  - freedesktop-sdk.bst:components/xz.bst
  # Compression for the release asset.
  - freedesktop-sdk.bst:components/zstd.bst
  # The k3s binary itself.
  - filename: k3s/k3s-bin.bst
    config:
      location: /

sources:
  - kind: local
    path: files/k3s/sysext

variables:
  # The output is an erofs image, not ELF binaries; skip the FSDK stripper
  # (not present in this element's dependency set).
  strip-binaries: ""

config:
  install-commands:
    - |
      set -euo pipefail
      OUT="%{install-root}"
      # Version on the k3s axis: the sysupdate transfer reads this filename
      # as the version of the thing it delivers, which is k3s — not the OS.
      FNAME="k3s-%{k3s-version}.raw"

      # Fail closed on unsupported architectures: k3s binary import in
      # elements/k3s/k3s-bin.bst targets x86_64 only.
      if [ "%{arch}" != "x86_64" ]; then
        echo "ERROR: elements/oci/k3s-sysext.bst only supports x86_64 (got %{arch})" >&2
        exit 1
      fi

      mkdir -p sysext/usr/bin
      mkdir -p sysext/usr/lib/systemd/system
      mkdir -p sysext/usr/lib/extension-release.d
      mkdir -p sysext/usr/share/bluefin/k3s
      mkdir -p sysext/usr/lib/tmpfiles.d
      mkdir -p "${OUT}"

      # Stage the k3s binary.
      cp -a /usr/bin/k3s sysext/usr/bin/k3s
      chmod 0755 sysext/usr/bin/k3s

      # systemd units (not enabled; provisioning can enable them).
      cp -a k3s.service k3s-agent.service sysext/usr/lib/systemd/system/

      # Extension identity required by systemd-sysext. ARCHITECTURE= and
      # VERSION_ID= are generated from the build's `arch` option and the
      # pinned k3s version so they can never disagree with the binary staged
      # above or with the asset filename systemd-sysupdate compares.
      cp -a extension-release.k3s sysext/usr/lib/extension-release.d/
      echo "VERSION_ID=%{k3s-version}" >> sysext/usr/lib/extension-release.d/extension-release.k3s
      echo "ARCHITECTURE=%{systemd-arch}" >> sysext/usr/lib/extension-release.d/extension-release.k3s

      # Tuning defaults shipped in /usr and seeded into /etc via tmpfiles.
      cp -a 50-bluefin-tuning.yaml sysext/usr/share/bluefin/k3s/
      cp -a k3s-bluefin.conf sysext/usr/lib/tmpfiles.d/

      # Build a plain erofs sysext image.
      mkfs.erofs -d0 "${OUT}/${FNAME}" sysext

      # Compress the release asset; keep the uncompressed raw image too.
      zstd -T0 -19 -q "${OUT}/${FNAME}" -o "${OUT}/${FNAME}.zst"

      (
        cd "${OUT}"
        sha256sum --binary "${FNAME}.zst" > SHA256SUMS
      )
