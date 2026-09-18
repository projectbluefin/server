kind: junction

sources:
- kind: git_repo
  url: gitlab:freedesktop-sdk/freedesktop-sdk.git
  track: freedesktop-sdk-26.08*
# renovate: datasource=git-refs depName=https://gitlab.com/freedesktop-sdk/freedesktop-sdk.git
  ref: freedesktop-sdk-26.08.1-0-gb02b59ffe19a49a402f357fd5fcb1d552ebc50d7
- kind: patch_queue
  path: patches/freedesktop-sdk

config:
  options:
    target_arch: '%{arch}'
    (?):
    - arch == 'x86_64':
        bootstrap_build_arch: 'x86_64'
    - arch == 'aarch64':
        bootstrap_build_arch: 'aarch64'
    - arch == "ppc64le":
        bootstrap_build_arch: "ppc64le"
    - arch == "riscv64":
        bootstrap_build_arch: "x86_64"

  # FSDK 26.08 dropped components/systemd-base.bst, and gnome-build-meta
  # (gnome-50 / master) is still pinned to FSDK 25.08 and still depends on it,
  # so overriding FSDK's systemd onto gnome-build-meta's fails to load.
  # Use FSDK 26.08's own systemd until gnome-build-meta tracks 26.08.
  # NOTE: re-evaluate for brew-deps.bst (nspawn machine image), which wanted
  # gnome-build-meta's nspawn/container patches.
