kind: junction

sources:
- kind: git_repo
  url: https://github.com/projectbluefin/fsdk-containers.git
  track: main
  ref: b79382bd18aebbe805f018cf9d777a4492f92ce8

config:
  options:
    arch: '%{arch}'
  overrides:
    freedesktop-sdk.bst: freedesktop-sdk.bst
    plugins/buildstream-plugins-community.bst: plugins/buildstream-plugins-community.bst
