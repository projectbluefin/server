## Target

Release identity, artifact publication, installer layout, first-boot provisioning,
and downstream boot verification for the Bluefin Server Alpha 2 release.

## Dependents

- `Justfile`: version derivation and validation entry point.
- `project.conf`: BuildStream artifact version input.
- `.github/workflows/build.yml`: graph validation, signing, and GitHub Release upload.
- `.github/scripts/verify-release.py`: release asset contract.
- `files/os/sysupdate.d/*.transfer`: OTA filename and target contracts.
- `elements/oci/bluefin-server-installer.bst`: installer and target UKI generation.
- `files/installer/repart.d/*.conf`: installed disk layout.
- `elements/bluefin-server/os-stack.bst`: runtime composition and credential consumers.
- Downstream `projectbluefin/lab` Argo templates: cluster build and boot-test gates.

## Affected Stories

- e01s01/e01s02: release identity and signed manifest verification.
- e02s01/e02s02: immutable runtime and first-boot credentials.
- e03s01/e03s02: coupled A/B root/UKI slots and rollback.
- e04s01: downstream installer boot gate.
- e05s01: release evidence and publication.

## Test Coverage

- Existing: `actionlint`, docs checks, `just test`.
- Added: `just check-version` and standard-library release artifact verifier.
- Gap: no local automated A/B, rollback, credential-login, or downstream boot-test evidence yet.

## Risk: High

The release workflow, boot layout, update targets, and downstream factory workflow
form a shared external contract; partial changes can publish artifacts that install
but cannot update or recover safely.

## Recommended action

Keep e01 as the first executable slice. Do not publish a new release until the
A/B, immutable-state, credential, and factory-gate stories have passing evidence.
