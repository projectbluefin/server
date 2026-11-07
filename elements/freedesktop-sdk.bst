kind: junction

sources:
- kind: git_repo
  url: gitlab:freedesktop-sdk/freedesktop-sdk.git
  track: freedesktop-sdk-26.08*
# renovate: datasource=git-refs depName=https://gitlab.com/freedesktop-sdk/freedesktop-sdk.git
  ref: freedesktop-sdk-26.08.4-0-g114ae909ec9881958bd507c8b4414aa33f758d2b
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

  overrides:
    # Our public module signing certificate; FSDK's kernel trusts it and
    # turns on lockdown (see bluefin-server/keys/linux-module-cert.bst).
    components/linux-module-cert.bst: bluefin-server/keys/linux-module-cert.bst
