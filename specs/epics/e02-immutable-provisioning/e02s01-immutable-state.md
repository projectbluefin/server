### Story e02s01: Define and enforce the immutable runtime state model

**type:** refactor
**risk:** P0
**context:** infra

## Context

The current target UKI explicitly requests `rw`, while the architecture promises
an immutable image. Alpha 2 will use the narrower, supportable contract:
vendor `/usr` is immutable; `/etc`, `/var`, runtime credentials, and generated
host state use supported writable locations.

## Requirements

- **MODIFIED** — Before: the installed target boots with a writable root and
  readiness documents literal root read-only behavior inconsistently. After:
  the documented and tested invariant is immutable vendor `/usr` with writable
  supported state.

## Steps

1. Map all writes required during first boot and move or preserve them in
   supported writable state → verify: `grep -RIn 'sysusers\|tmpfiles\|host key\|/var' elements files docs | head -120`
2. Change target runtime configuration only after the state map is complete →
   verify: `just validate`
3. Extend the installed-system smoke test with `/usr` write rejection and
   `/var` write success → verify: `just test`

## Out of scope

- dm-verity or a new filesystem integrity layer.

## Risks

- A blind `rw` to `ro` change can break sysusers, SSH host-key generation, or
  credential delivery; implementation must follow the state map.
