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
    url: github:projectbluefin/knuckle/releases/download/v0.9.2/knuckle-linux-amd64
    # sha256 of knuckle-linux-amd64 — update after each release
    ref: 86ffc55ffef59fac13e1c61204a112a10491ba34d856b8a81a4caadf9e295eb0
    filename: knuckle

config:
  install-commands:
    - install -Dm755 knuckle "%{install-root}/opt/knuckle"
  strip-commands: []
