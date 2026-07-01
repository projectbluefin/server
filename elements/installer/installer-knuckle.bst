kind: manual
description: |
  Stage the knuckle interactive installer binary at /opt/knuckle.

  knuckle is a Go TUI (Bubble Tea) installer that provides the interactive
  installation UI for Bluefin Server. It replaces the non-interactive
  bluefin-install bash script.

  The binary is fetched from the knuckle GitHub release and staged at
  /opt/knuckle, which is what installer.service ExecStart points to.

  Source: https://github.com/projectbluefin/knuckle/releases

build-depends:
  - base/base-stack.bst

# NOTE: Update url and ref after each knuckle release.
# To update ref: curl -sL <url> | sha256sum
sources:
  - kind: remote
    url: https://github.com/projectbluefin/knuckle/releases/download/v0.9.0/knuckle-linux-amd64
    # sha256 of knuckle-linux-amd64 — update after each release
    ref: ddaa1d67eb1422d76a1d1e2bc2fad3936b9da136f416d4da12c88f7311226693
    filename: knuckle

config:
  install-commands:
    - install -Dm755 knuckle "%{install-root}/opt/knuckle"
  strip-commands: []
