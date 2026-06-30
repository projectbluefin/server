kind: manual
description: |
  Stage the Homebrew file tree into the linuxbrew prefix without running
  install.sh (which needs network, unavailable in the BST sandbox). Homebrew
  supports an "untar in place" install: the brew.git checkout IS the install.
  Creates the prefix skeleton brew expects on first run; Cellar/opt/lib stay
  empty until the user installs formulas at runtime.

sources:
  - kind: git_repo
    url: github:Homebrew/brew.git
    track: 6.0.3
    ref: 5c38c6b3fc42281af432cda526dd0509172f681b

depends:
  # coreutils + bash to run the install-commands.
  - freedesktop-sdk.bst:public-stacks/runtime-minimal.bst

variables:
  # Brew ships ruby/bash/perl scripts; nothing to strip and stripping can
  # corrupt the vendored portable-ruby shims.
  strip-binaries: ""

config:
  install-commands:
    - |
      prefix="%{install-root}/home/linuxbrew/.linuxbrew"
      mkdir -p "$prefix/Homebrew" "$prefix/bin" "$prefix/etc" "$prefix/share" \
               "$prefix/Cellar" "$prefix/opt" "$prefix/lib" "$prefix/var/homebrew"
      # The git_repo source is checked out at the build root; it is the brew tree.
      cp -a . "$prefix/Homebrew/"
      # Canonical entrypoint symlink: <prefix>/bin/brew -> <prefix>/Homebrew/bin/brew
      ln -sf ../Homebrew/bin/brew "$prefix/bin/brew"
