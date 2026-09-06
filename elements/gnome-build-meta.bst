kind: junction

sources:
- kind: git_repo
  url: gnome:gnome-build-meta.git
  track: gnome-50
# renovate: datasource=git-refs depName=https://gitlab.gnome.org/GNOME/gnome-build-meta.git
  ref: 50.4-1-gec28a45a6fcd99195ebc39c1aeda78fd6fe27b8f
- kind: patch_queue
  path: patches/gnome-build-meta

config:
  options:
    arch: '%{arch}'

  overrides:
    # This along with the patches is required and has to match what gnome-build-meta is using
    freedesktop-sdk.bst: freedesktop-sdk.bst

    plugins/buildstream-plugins.bst: plugins/buildstream-plugins.bst
    plugins/buildstream-plugins-community.bst: plugins/buildstream-plugins-community.bst
