# INSECURE dev kernel module key — public, non-release builds only

`INSECURE-dev-module-key.pem` is a **published private key**. Anyone can sign
a kernel module with it. Never trust it on a machine you care about.

What it is for: `just gen-dev-keys` (`scripts/gen-dev-keys.sh`) copies this
pair into `files/boot-keys/` as the module signing key of throwaway key sets
(pull requests, the nightly build, local builds). The kernel's cache key
depends on the module certificate it trusts, so a fixed dev certificate lets
those builds pull a kernel that `scripts/kernel-cache.sh seed dev` built once,
instead of compiling FSDK's kernel on every run.

What keeps it out of releases:

- Release builds install the project keys from `BOOT_KEYS_TARBALL` and run
  `scripts/check-release-keys.sh`, which fails the build when the staged
  module certificate or module key is this pair.
- `scripts/kernel-cache.sh seed release` runs the same check.
- The release kernel trusts only `files/release-keys/linux-module-cert.crt`,
  so modules signed with this key do not load on it under lockdown.

What a dev image trusts: its kernel trusts this certificate, so under
lockdown anyone with root on a dev image can load a module signed with this
key. Dev images are also signed with throwaway Secure Boot keys and are never
published. For a local image you boot on real hardware, generate a private
module key: `just gen-dev-keys --force --private-module-key` (that kernel is
then built locally).

Only the certificate reaches the kernel build (through
`bluefin-server/keys/linux-module-cert.bst`, which imports
`files/boot-keys/modules/`). The key reaches only the signing elements
through `bluefin-server/keys/boot-keys.bst`, which no pushed artifact
contains. Details: `docs/skills/secure-boot-keys.md`.
