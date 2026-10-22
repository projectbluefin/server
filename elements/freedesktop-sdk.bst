kind: junction

sources:
- kind: git_repo
  url: gitlab:freedesktop-sdk/freedesktop-sdk.git
  track: freedesktop-sdk-26.08*
# renovate: datasource=git-refs depName=https://gitlab.com/freedesktop-sdk/freedesktop-sdk.git
  ref: freedesktop-sdk-26.08.3-0-gd0c0b597d58f8cc14ee26c427aec1be13c6a313e
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
