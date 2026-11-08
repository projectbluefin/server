kind: manual
description: |
  The Homebrew seed: /usr/share/homebrew/brew.tar.zst, a reproducible archive
  of the Homebrew/brew tree at a pinned release tag (with a local git
  repository whose origin is Homebrew/brew, so `brew update` works) and the
  portable-ruby that tag vendors, under a single top-level .linuxbrew
  directory. bluefin-homebrew-seed.service extracts it to
  /home/linuxbrew/.linuxbrew on first boot. No compiler, make or system ruby
  ships; bottles need only the base's git, curl, bash, file, zstd, tar, xz
  and gzip. Pins live in include/homebrew.yml.

(@):
- include/arch.yml
- include/homebrew.yml

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:components/git.bst
- freedesktop-sdk.bst:components/tar.bst
- freedesktop-sdk.bst:components/zstd.bst

sources:
- kind: git_repo
  url: github:Homebrew/brew.git
  ref: "%{homebrew-version}-0-g%{homebrew-commit}"
  directory: brew
- kind: tar
  url: github:Homebrew/homebrew-portable-ruby/releases/download/%{homebrew-portable-ruby-version}/portable-ruby-%{homebrew-portable-ruby-version}.%{ruby-tag}.bottle.tar.gz
  ref: "%{ruby-sha256}"
  base-dir: portable-ruby/%{homebrew-portable-ruby-version}
  directory: ruby
- kind: local
  path: files/homebrew
  directory: files

variables:
  strip-binaries: ""
  ruby-tag: x86_64_linux
  ruby-sha256: "%{homebrew-portable-ruby-x86-64-sha256}"

(?):
- arch == "aarch64":
    variables:
      ruby-tag: arm64_linux
      ruby-sha256: "%{homebrew-portable-ruby-arm64-sha256}"

config:
  install-commands:
  - |
    set -euo pipefail
    stage=seed/.linuxbrew
    repo=$stage/Homebrew
    mkdir -p "$stage"
    mv brew "$repo"
    for d in bin sbin etc include lib opt share var/homebrew/linked Cellar; do
      mkdir -p "$stage/$d"
    done
    ln -s ../Homebrew/bin/brew "$stage/bin/brew"
    vendor=$repo/Library/Homebrew/vendor/portable-ruby
    mkdir -p "$vendor"
    mv ruby "$vendor/%{homebrew-portable-ruby-version}"
    ln -s "%{homebrew-portable-ruby-version}" "$vendor/current"
    # A local repository so `brew update` can fetch and reset. The commit is
    # synthetic but fixed, so the archive is reproducible.
    export GIT_AUTHOR_NAME=bluefin GIT_AUTHOR_EMAIL=bluefin@localhost
    export GIT_COMMITTER_NAME=bluefin GIT_COMMITTER_EMAIL=bluefin@localhost
    export GIT_AUTHOR_DATE="2026-01-01T00:00:00Z" GIT_COMMITTER_DATE="2026-01-01T00:00:00Z"
    git -C "$repo" init -q -b main
    git -C "$repo" remote add origin https://github.com/Homebrew/brew
    git -C "$repo" add -A
    git -C "$repo" -c core.fileMode=true commit -q -m "Homebrew %{homebrew-version}"
    git -C "$repo" tag "%{homebrew-version}"
    mkdir -p "%{install-root}%{datadir}/homebrew"
    tar --sort=name --mtime=@1767225600 --owner=0 --group=0 --numeric-owner \
      --format=posix --pax-option=delete=atime,delete=ctime \
      -C seed -cf - .linuxbrew | zstd -19 -T1 -q -o "%{install-root}%{datadir}/homebrew/brew.tar.zst"
    install -Dm0755 files/bluefin-homebrew-seed -t "%{install-root}%{libexecdir}/"
    install -Dm0644 files/bluefin-homebrew-seed.service files/bluefin-homebrew-seed.path \
      -t "%{install-root}%{indep-libdir}/systemd/system/"
    install -Dm0644 files/80-bluefin-homebrew.preset \
      "%{install-root}%{indep-libdir}/systemd/system-preset/80-bluefin-homebrew.preset"
    install -Dm0644 files/bluefin-homebrew.tmpfiles \
      "%{install-root}%{indep-libdir}/tmpfiles.d/50-bluefin-homebrew.conf"
    install -Dm0644 files/90-bluefin-homebrew.sh \
      "%{install-root}%{indep-libdir}/bluefin/profile.d/90-bluefin-homebrew.sh"
