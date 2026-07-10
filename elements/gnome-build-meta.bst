kind: junction

sources:
- kind: git_repo
  url: gnome:gnome-build-meta.git
  track: gnome-50
# renovate: datasource=git-refs depName=https://gitlab.gnome.org/GNOME/gnome-build-meta.git
  ref: 50.2-1-gcc8cb59e7413a373a582204a3bed53ac7ac756f8
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
