kind: script
description: |
  Stage the knuckle interactive installer binary at /opt/knuckle.

  knuckle is a Go TUI (Bubble Tea) installer that provides the interactive
  installation UI for Bluefin Server. It replaces the non-interactive
  bluefin-install bash script.

  The binary is fetched from the knuckle GitHub release and staged at
  /opt/knuckle, which is what installer.service ExecStart points to.

  Source: https://github.com/projectbluefin/knuckle/releases

# NOTE: Update url and ref after each knuckle release.
# To update ref: curl -sL <url> | sha256sum
sources:
  - kind: remote
    url: https://github.com/projectbluefin/knuckle/releases/download/v0.9.0/knuckle_linux_amd64
    # sha256 of knuckle_linux_amd64 — update after each release
    ref: 0019dfc4b32d63c1392aa264aed2253c1e0c2fb09216f8e2cc269bbfb8bb49b5
    filename: knuckle

config:
  commands:
    - install -Dm755 "%{sourcedir}/knuckle" "%{install-root}/opt/knuckle"
