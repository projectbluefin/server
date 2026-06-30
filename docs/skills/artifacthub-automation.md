---
name: artifacthub-automation
description: Automating ArtifactHub repository submission and Verified Publisher status via API. Use when publishing new OCI images or adding ArtifactHub metadata.
metadata:
  type: runbook
---

# Automating ArtifactHub Submissions

ArtifactHub does not support automatic registry-wide scanning to discover new OCI repositories. New container images (like `ghcr.io/projectbluefin/skopeo`) must be registered individually. However, this process can be fully automated in CI using ArtifactHub's REST API and `oras`.

## When to Use
- When adding a new container image to the repository that needs to be listed on ArtifactHub.
- When configuring CI/CD pipelines to publish ArtifactHub metadata.
- When you need to obtain the "Verified Publisher" badge for an OCI image.

## When NOT to Use
- When working with non-OCI artifacts (e.g., `brew` nspawn tarballs).
- When the image is an internal/testing image not meant for public registry listing.

## Core Process

### 1. OCI and ArtifactHub Labels
Before automating submissions, ensure the image is built with the required metadata. The `fsdk-containers` elements inject these directly into the `config.Labels` block of their `build-oci` script:

* `org.opencontainers.image.title`
* `org.opencontainers.image.description`
* `org.opencontainers.image.vendor`
* `io.artifacthub.package.readme-url` (Must point to raw Markdown, not an HTML page)
* `io.artifacthub.package.logo-url`
* `io.artifacthub.package.license`
* `io.artifacthub.package.category`

ArtifactHub parses these labels from the OCI image index to display full package metadata.

### 2. API Registration (GitHub Actions)
When a new image is added to the repository, it can be registered on ArtifactHub using an API call.
Store the API keys in GitHub Secrets as `ARTIFACT_HUB_KEY_ID` and `ARTIFACT_HUB_KEY_SECRET`.

Example `curl` step for the release pipeline:
```yaml
- name: Register Container on ArtifactHub
  run: |
    curl -s -X POST "https://artifacthub.io/api/v1/repositories/org/projectbluefin" \
      -H "Content-Type: application/json" \
      -H "X-API-KEY-ID: ${{ secrets.ARTIFACT_HUB_KEY_ID }}" \
      -H "X-API-KEY-SECRET: ${{ secrets.ARTIFACT_HUB_KEY_SECRET }}" \
      -d '{
        "name": "base",
        "display_name": "Base Distroless Image",
        "url": "oci://ghcr.io/projectbluefin/base",
        "kind": 12,
        "data": {
          "tags": [{"name": "latest", "mutable": true}]
        }
      }'
```

### 3. Verified Publisher Badge
To get the green "Verified Publisher" checkmark, push an ownership metadata file to the image registry.

1. **Get the Repository ID:** Generated when you register a repository via the API/UI.
2. **Create `artifacthub-repo.yml`:**
   ```yaml
   repositoryID: "your-artifacthub-repo-id"
   owners:
     - name: "Project Bluefin"
       email: "maintainers@projectbluefin.io"
   ```
3. **Push via `oras`:**
   ```bash
   oras push \
     ghcr.io/projectbluefin/base:artifacthub.io \
     --config /dev/null:application/vnd.cncf.artifacthub.config.v1+yaml \
     artifacthub-repo.yml:application/vnd.cncf.artifacthub.repository-metadata.layer.v1.yaml
   ```

## Common Rationalizations
- **"ArtifactHub will eventually scan the GitHub Container Registry."** -> Reality: OCI registries do not support global cataloging. You MUST register each repository via the API or UI.
- **"I can just add the labels and it will show up."** -> Reality: Labels only populate metadata *after* the repository is explicitly registered.

## Red Flags
- An OCI image is being built and pushed to GHCR, but no `curl` API call to ArtifactHub is in the release pipeline.
- The `io.artifacthub.package.readme-url` points to an HTML GitHub page instead of a raw Markdown file.
- No `oras push` step exists to push the `artifacthub-repo.yml` file.

## Verification
- [ ] `io.artifacthub.package.readme-url` is set and points to raw markdown.
- [ ] `io.artifacthub.package.logo-url` is set.
- [ ] `org.opencontainers.image.*` standard labels are present.
- [ ] CI pipeline contains a step to `POST` to `https://artifacthub.io/api/v1/repositories/org/projectbluefin`.
- [ ] CI pipeline contains an `oras push` step to the `artifacthub.io` tag.
