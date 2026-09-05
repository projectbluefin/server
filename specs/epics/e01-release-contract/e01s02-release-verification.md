### Story e01s02: Verify signed release manifests before upload

**type:** feat
**risk:** P0
**context:** infra

## Context

The release workflow signs a combined manifest, but previously did not verify
that the local release directory contained exactly the expected versioned
artifact set before upload.

## Requirements

- **ADDED** — CI verifies the exact DDI, installer, UKI, and k3s artifact set
  for the resolved version before signing or uploading.
- **ADDED** — CI verifies SHA256 entries and the detached signature with the
  public key shipped in the OS image before publishing.
- **MODIFIED** — Before: release creation errors were masked with `|| true`.
  After: only an explicitly absent release is created; other errors fail CI.

## Steps

1. Add the standard-library release asset verifier → verify:
   `python3 .github/scripts/verify-release.py --help`
2. Run filename-set, checksum, and signature verification in CI → verify:
   `actionlint .github/workflows/build.yml`
3. Exercise the verifier with the expected artifact names (SBOMs included —
   they ship inside the signed manifest) → verify:
   `tmp=$(mktemp -d); touch "$tmp/bluefin-server-26.08.0.efi" "$tmp/bluefin-server-ddi-26.08.0.raw.zst" "$tmp/bluefin-server-ddi-26.08.0.spdx.json" "$tmp/bluefin-server-installer-26.08.0.raw.zst" "$tmp/bluefin-server-installer-26.08.0.spdx.json" "$tmp/k3s-26.08.0.raw.zst" "$tmp/k3s-26.08.0.spdx.json"; python3 .github/scripts/verify-release.py --version 26.08.0 --directory "$tmp"; rm -rf "$tmp"`

## Verification Script

Run the commands above, then inspect the published release manifest with the
public key using `gpgv`.

## Out of scope

- Signing-key rotation.

## Risks

- The release key must remain available as `SYSUPDATE_SIGNING_KEY`; missing
  secrets correctly stop publication.
