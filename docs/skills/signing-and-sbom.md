---
name: signing-and-sbom
description: >
  Guides supply chain security implementation for fsdk-containers, focusing on
  BuildStream-native SBOM generation (via buildstream-sbom) and keyless image/SBOM
  signing with Sigstore Cosign.
---

# Supply Chain Security: Keyless Signing and SBOMs

Use this skill when auditing, debugging, or extending fsdk-containers' supply chain security, specifically image signing, SBOM generation, or ORAS attachment/verification pipelines.

## Context: Why Standard Scanners Fail
Since `fsdk-containers` OCI images are strictly distroless with no package manager databases (no RPM or dpkg database present in the rootfs), standard post-build scanners like Syft or Trivy cannot accurately map the packages. They will report 0 or 1 package.
To produce authoritative, high-integrity SBOMs, we generate them directly from BuildStream's build-graph using `buildstream-sbom`. This captures all 500+ package definitions, point-release versions, and patch levels from upstream freedesktop-sdk metadata.

---

## Signing and SBOM Architecture

The pipeline consists of three phases:

```
[Build & Verify] ──> [Assemble Manifests] ──> [Sign Manifest] ──> [Attach SBOM] ──> [Sign SBOM]
```

1. **SBOM Generation:** Runs `just sbom <image>` locally or in CI. This runs `buildstream-sbom` inside the cached `bst2` builder container and writes `<image>.spdx.json`.
2. **Keyless Signing:** Uses Sigstore Cosign in keyless mode (OIDC via GitHub Actions as the issuer with `id-token: write` permissions).
3. **ORAS Attachment:** Binds the SPDX SBOM to the published OCI multi-arch manifest list as a referrer.
4. **Referrer Signing:** Signs the attached SBOM OCI artifact, ensuring the entire graph (image + metadata) is cryptographically bound and verifiable.

---

## Local Verification Runbook

To generate and inspect a BuildStream-native SBOM locally:

```bash
# 1. Generate the SBOM for an image (e.g. base)
just sbom base

# 2. Check JSON validity and package counts
jq '.packages | length' base.spdx.json

# 3. Check for specific FSDK components (e.g. glibc, openssl)
jq -r '.packages[].name' base.spdx.json | grep -E "glibc|openssl"
```

To verify a published image and its signature/attestation from the command line:

```bash
# Verify the keyless signature of an image
cosign verify \
  --certificate-identity-regexp="https://github.com/projectbluefin/fsdk-containers/.github/workflows/" \
  --certificate-oidc-issuer="https://token.actions.githubusercontent.com" \
  ghcr.io/projectbluefin/base:latest

# Discover and retrieve the attached SBOM
oras discover ghcr.io/projectbluefin/base:latest
```

---

## CI / CD Pipeline Requirements

When modifying `.github/workflows/build.yml` or write new publish jobs, maintain these strict standards:

### 1. Workflow Permissions
The job performing the signing must explicitly request:
```yaml
permissions:
  contents: read
  packages: write
  id-token: write      # Crucial for Fulcio keyless OIDC token generation
```

### 2. Compatibility Auth File (Blocking Gotcha)
`podman login` writes credentials to podman's container storage, but the `oras` CLI relies on `~/.docker/config.json`. You **must** populate the compat auth file:
```yaml
- name: Log in to ghcr
  run: |
    mkdir -p ~/.docker
    echo "${{ secrets.GITHUB_TOKEN }}" | podman login ghcr.io -u "${{ github.actor }}" --password-stdin
    echo "${{ secrets.GITHUB_TOKEN }}" | podman login ghcr.io -u "${{ github.actor }}" --password-stdin --compat-auth-file ~/.docker/config.json
```

### 3. Signing the Manifest List (Index) Digest (Blocking Gotcha)
Always resolve and sign the manifest list/index digest, not just the mutable tag. Tag signing is vulnerable to TOCTOU race conditions. Resolve the canonical digest using `skopeo inspect`:
```bash
DIGEST=$(skopeo inspect --creds "${{ github.actor }}:${{ secrets.GITHUB_TOKEN }}" "docker://${REPO}:${t}" | jq -r '.Digest')
cosign sign -y "${REPO}@${DIGEST}"
```

### 4. Pip Wheel Cache
Always cache the pip wheel for `buildstream-sbom` in CI, pinned to the exact commit hash:
```yaml
- name: Restore pip cache for buildstream-sbom
  uses: actions/cache@2c8a9bd7457de244a408f35966fab2fb45fda9c8 # v6
  with:
    path: ~/.cache/pip
    key: pip-sbom-0706fec3bedf6f73bd9d2fed32c2aed585feef8d
    restore-keys: pip-sbom-
```

### 5. Multi-image SBOM Optimization (Speed + Uniqueness)
To generate SBOMs for multiple images efficiently and correctly in CI:
- **Avoid calling `pip install` inside GHA loops.** Running `pip install` inside a loop for each container spins up the container multiple times and repeats dependency resolution.
- Use `just sboms` (plural) to spin up the BuildStream container **once**, install `buildstream-sbom` **once**, and generate SBOMs for all target images in a single run.
- **Enforce Unique SPDX Namespaces.** Ensure each image variant receives a unique SPDX document namespace (as required by the SPDX spec) by appending the image name to the namespace URL: `https://github.com/projectbluefin/fsdk-containers/sbom/${GIT_SHA}/${SPDX_NAME}`.

