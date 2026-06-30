# brew-nspawn container spec

## What this is

A systemd-nspawn machine image — a rootfs tarball suitable for `machinectl import-tar` — that provides the full Homebrew developer environment for Project Bluefin/Dakota.

**This is NOT a distroless image.** It is a full dev environment container. The distroless rules (no shells, strip locales, etc.) do NOT apply. This container needs bash, a package manager runtime, compilers, and a real init.

Updated independently via `systemd-sysupdate`. Also installable standalone on any systemd distro as `bluefin-cli`.

## Output format

A `.tar.zst` rootfs archive (zstd compression — 3-5x faster decompression than gzip on modern CPUs; systemd-sysupdate supports it natively), NOT an OCI image. The BST element chain must produce a tarball that `machinectl import-tar` accepts — i.e., a complete Linux rootfs with `/etc`, `/usr`, `/bin`, `/lib`, etc.

Published to GitHub Releases at `https://github.com/projectbluefin/bluefin-cli/releases/download/<ver>/homebrew-env-<ver>.tar.zst`.

A `SHA256SUMS` file **must** be published alongside the tarball at the same URL prefix — `systemd-sysupdate url-tar` requires it. GitHub Releases does not generate this automatically; it must be produced and uploaded in CI.

## Required contents

### Init system
Must have a working init so `machinectl start homebrew` succeeds. FSDK's `components/systemd.bst` if it exists, otherwise a minimal init. The container runs long-lived (always-on, started at boot via `systemd-nspawn@homebrew.service`).

### Runtime dependencies brew needs to operate
```
components/ruby.bst          # brew is written in Ruby — required at runtime
components/git.bst           # brew uses git for taps and self-update
components/curl.bst          # brew downloads bottles via curl
components/gcc.bst           # needed for source builds; also what the user gets for free
components/ca-certificates.bst  # HTTPS cert verification for brew downloads
```

### Brew itself
Stage the brew prefix into `/home/linuxbrew/.linuxbrew` during build.

Use the existing dakota pattern from `elements/bluefin/brew.bst` as reference — it pulls from `github:ublue-os/brew.git` using `kind: git_repo`. Adapt that source reference. The key is to install brew's file tree (not run install.sh at build time — that requires network in the BST sandbox).

Brew's minimal structure needed on first run:
```
/home/linuxbrew/.linuxbrew/Homebrew/          ← brew.git contents
/home/linuxbrew/.linuxbrew/bin/brew           ← symlink to Homebrew/bin/brew
/home/linuxbrew/.linuxbrew/Cellar/            ← empty dir (brew populates at runtime)
/home/linuxbrew/.linuxbrew/opt/               ← empty dir
/home/linuxbrew/.linuxbrew/lib/               ← empty dir
```

### User account
The container runs brew as the `linuxbrew` user (uid 1001, gid 1001). Create this user in `/etc/passwd` and `/etc/group` during the build. The nspawn config uses `PrivateUsers=no`, so this uid must match across host and container.

```
/etc/passwd:  linuxbrew:x:1001:1001::/home/linuxbrew:/bin/bash
/etc/group:   linuxbrew:x:1001:
/etc/subuid:  linuxbrew:100000:65536
/etc/subgid:  linuxbrew:100000:65536
```

### Shell
`bash` must be present and at `/bin/bash` — brew requires it. Do NOT strip the shell.

### Locale
Keep `en_US.UTF-8` as minimum. Brew and some formulas assume a UTF-8 locale.

## What to exclude

No desktop stack. No Wayland/Mesa/PipeWire/GTK (hard rule #1 from AGENTS.md — don't pull `platform.bst`). No X11. No audio. No printing.

No package manager (apt/dnf/etc) — brew IS the package manager for this container.

## BST element structure (suggested)

```
elements/
  brew/
    brew-deps.bst        # kind: stack — FSDK ruby, git, curl, gcc, ca-certs, systemd, bash
    brew-runtime.bst     # kind: compose — carve brew-deps to runtime domains (keep shells)
    brew-prefix.bst      # kind: manual — stage brew git repo into /home/linuxbrew prefix
    brew-users.bst       # kind: manual — /etc/passwd, /etc/group, /etc/subuid entries
  oci/
    brew-nspawn.bst      # kind: script — assemble rootfs tar (NOT OCI image)
```

## The output element (brew-nspawn.bst)

This is where it diverges from all other fsdk-containers outputs. Instead of `build-oci`, the script element must produce a `.tar.gz` of the rootfs:

```yaml
kind: script
build-depends:
  - brew/brew-runtime.bst  # filename: ..., config: location: /layer
  - brew/brew-prefix.bst   # filename: ..., config: location: /layer
  - brew/brew-users.bst    # filename: ..., config: location: /layer
config:
  commands:
    - |
      # Produce machinectl-compatible rootfs tarball
      tar -czf "%{install-root}/homebrew-env-%{version}.tar.gz" \
        -C /layer .
    - |
      # SHA256SUMS for systemd-sysupdate
      cd "%{install-root}"
      sha256sum --binary homebrew-env-%{version}.tar.gz > SHA256SUMS
```

## Performance requirements

The container image must support these performance optimizations. They are not optional:

1. **zstd compression** — use `.tar.zst` not `.tar.gz`. Decompresses 3-5x faster on pull.

2. **virtiofs compatibility (no DAX for writable prefix)** — the rootfs must make no
   assumptions about direct `/dev` access or host-specific paths. For the VM tier,
   `/home/linuxbrew` is shared via virtiofs in **non-DAX mode** (default). DAX has
   known truncation/page-fault pathologies for mutable data. Do NOT use `cache=always`
   DAX for the writable brew prefix.

3. **`HOMEBREW_NO_AUTO_UPDATE=1`** and **`HOMEBREW_NO_INSTALL_CLEANUP=1`** must be set
   in `/etc/environment` inside the container. Brew checks for updates on every
   `install`/`search` by default. Updates are handled by the container image cycle,
   not by brew's self-update.

4. **`/tmp` on tmpfs** — ensure the container's `/tmp` is backed by tmpfs (standard
   systemd behavior). Bottle installs untar to temp before moving.

5. **btrfs NOCOW for hot-write dirs** — `HOMEBREW_CACHE` and `HOMEBREW_TEMP` inside
   the container (which map to host-side bind mounts) should be on btrfs subvolumes
   with `chattr +C` (NoDataCoW). btrfs CoW is expensive for sqlite, git ref writes,
   and download cache churn. Keep CoW on Cellar for snapshot value.

6. **Bubblewrap (bwrap) must work inside the container.** Homebrew 6 on Linux uses
   bubblewrap for formula build sandboxing. The container kernel and nspawn syscall
   filter must allow: `clone3`, `mount`, `pivot_root`, `open_tree`, `move_mount`,
   `unshare`. Do NOT add `@mount` to any syscall deny list. Validate with:
   `brew install hello` (forces a source build + bwrap, not just bottle install).

## Security tiers (for reference / docs)

The container image is the same for all tiers. The consuming side selects the tier at install time by deploying the appropriate config file and enabling the right systemd unit.

**Tier 1 — hardened nspawn (default):** namespace isolation + capability drop + syscall filter + NoNewPrivileges. ~35MB RAM, zero VM overhead. Not a hard security boundary (shared kernel), but meaningful defense-in-depth.

**Tier 2 — Cloud Hypervisor + kata-kernel (opt-in):**
- **VMM:** Cloud Hypervisor (Rust, Intel/Microsoft) — not QEMU (too heavy), not Firecracker (no virtiofs DAX), not the Kata runtime (wrong layer — Kata is a runtime, not a VMM)
- **Kernel:** kata-kernel from the `kata-containers` package — a stripped LTS kernel with minimal attack surface. Borrowed standalone; the Kata runtime itself is NOT needed
- **virtiofs DAX:** `/home/linuxbrew` shared into the VM via virtiofsd with DAX (shared memory mapping, zero-copy). ~95% native random read, ~90% write, ~85% metadata ops
- **Landlock:** the Cloud Hypervisor VMM process itself is Landlock-sandboxed — can only access `/home/linuxbrew` and the kernel image on the host
- **~55MB RAM, ~125ms cold boot** (amortized to zero with always-on model)
- **Genuine hypervisor boundary** — equivalent to macOS VMs, stronger VMM security story (Rust + Landlock vs QEMU's C codebase)

Security stack for Tier 2 (bottom to top):
```
host kernel
  ← seccomp: VMM syscall filter on virtio devices
    ← Landlock: VMM process restricted to /home/linuxbrew + kernel image
      ← Cloud Hypervisor VMM (Rust, memory-safe)
        ← KVM hardware boundary
          ← kata-kernel (stripped LTS, minimal attack surface)
            ← brew process
```

The container image must be compatible with virtiofs — no assumptions about direct `/dev` access or host-specific paths baked in at image build time.

## Working nspawn config (for reference / docs)

The consuming side (Dakota/bluefin-cli) uses this config. The container image must be compatible with it:

```ini
# /etc/systemd/nspawn/homebrew.nspawn
[Exec]
PrivateUsers=no
ResolvConf=bind-host
DropCapability=CAP_SYS_ADMIN CAP_SYS_PTRACE CAP_NET_ADMIN CAP_SYS_RAWIO CAP_SYS_MODULE CAP_AUDIT_CONTROL
SystemCallFilter=~@mount @reboot @swap @obsolete
NoNewPrivileges=yes

[Files]
Bind=/home/linuxbrew

[Network]
VirtualEthernet=no
```

`PrivateUsers=no` — host and container share UIDs. `linuxbrew` at uid 1001 in the container must match what the host bind-mounts at `/home/linuxbrew` (owned by uid 1001).

## Host wrapper (for reference)

Shipped at `/usr/bin/brew` in the Dakota OCI image. The wrapper sets `HOMEBREW_NO_AUTO_UPDATE=1` to suppress brew's per-command update check.

```bash
#!/usr/bin/env bash
set -euo pipefail
MACHINE=homebrew
BREW_BIN=/home/linuxbrew/.linuxbrew/bin/brew

if ! machinectl list --no-legend | grep -q "^${MACHINE}\b"; then
    if machinectl list-images --no-legend | grep -q "^${MACHINE}\b"; then
        machinectl start "$MACHINE" 1>&2
        sleep 0.5
    else
        echo "bluefin-cli: homebrew container not installed. Run: ujust setup-bluefin-cli" >&2
        exit 1
    fi
fi

exec systemd-run --quiet --pipe --wait --machine="$MACHINE" --uid=linuxbrew \
    --setenv=HOMEBREW_NO_AUTO_UPDATE=1 --setenv=HOMEBREW_NO_INSTALL_CLEANUP=1 \
    -- "$BREW_BIN" "$@"
```

A future compiled wrapper (Rust + Varlink PID lookup + nsenter) will cut the ~50-100ms dbus overhead to ~3ms. The bash wrapper is correct for initial implementation.

## systemd-sysupdate transfer config (for reference)

Pulls versioned tarballs from GitHub Releases. A `SHA256SUMS` file must exist at the same path.

```ini
# /usr/lib/sysupdate.d/homebrew-container.transfer
[Transfer]
ProtectVersion=%A

[Source]
Type=url-tar
Path=https://github.com/projectbluefin/bluefin-cli/releases/download/
MatchPattern=homebrew-env-@v.tar.zst

[Target]
Type=directory
Path=/var/lib/bluefin-cli
MatchPattern=homebrew-env-@v.tar.zst
CurrentSymlink=/var/lib/bluefin-cli/homebrew-env.tar.zst
```

## Prototype reference (ubuntu baseline)

A working ubuntu:24.04-based prototype is running on exo-1. The BST version should produce equivalent behavior. Key facts from the prototype:

- Ubuntu slim + systemd + brew bootstrap → 530MB tar (acceptable; FSDK-based should be smaller)
- `machinectl import-tar` creates btrfs subvolume automatically on btrfs hosts
- `brew install cowsay` works end-to-end through the host wrapper
- DNS: `ResolvConf=bind-host` in nspawn config handles it — no manual resolv.conf bind needed
- UID: `PrivateUsers=no` is the correct setting; `PrivateUsersOwnership=auto` does NOT fix bind-mount ownership for external paths

## Questions for the implementer

1. Does FSDK have `components/systemd.bst`? If not, what init is available?
2. Does FSDK's `components/ruby.bst` include the full runtime needed by brew, or is it split?
3. Is there a BST pattern in this repo for producing a tar output instead of OCI? If not, the `brew-nspawn.bst` script element above is the pattern to add.
4. Should the brew git ref track dakota's `elements/bluefin/brew.bst` ref, or be independently pinned?
