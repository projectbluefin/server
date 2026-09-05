### Story e03s01: Provision matching root and UKI slots

**type:** feat
**risk:** P0
**context:** infra

## Context

`50-root.transfer` names root A and B, but the installer only provisions root A
and the UKI transfer has no matching slot strategy. This is not rollback-safe.

## Requirements

- **MODIFIED** — Before: the installer provisions one root slot while sysupdate
  advertises two. After: installer partition labels, UKI entries, and transfer
definitions describe the same coupled A/B layout.
- **ADDED** — Boot identity uses GPT labels/PARTUUIDs, never device paths.

## Steps

1. Define the coupled root/UKI slot layout and repartition recipes → verify:
   `grep -RIn 'root-a\|root-b\|PARTUUID' files/installer elements files/os | head -120`
2. Provision both initial slots and matching boot entries → verify: `just validate`
3. Align sysupdate target patterns with the installed layout → verify:
   `grep -RIn 'MatchPattern' files/os/sysupdate.d`

## Out of scope

- Multi-architecture boot entries.

## Risks

- Independent root and UKI transfers can leave a non-bootable mixed-version
  system; the implementation must prove matching-slot activation.
