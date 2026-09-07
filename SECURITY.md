# Security Policy

## Reporting a Vulnerability

Report security vulnerabilities privately through
[GitHub Private Vulnerability Reporting](https://github.com/projectbluefin/server/security/advisories/new).
Do **not** open a public GitHub issue for an unpatched vulnerability.

You can also reach the projectbluefin maintainers at **bluefin@projectbluefin.io**
(the org-wide contact published in
[`projectbluefin/dakota`](https://github.com/projectbluefin/dakota/blob/main/SECURITY.md)),
but the GitHub advisory flow is preferred.

Please include:

- A description of the vulnerability and its impact.
- Reproduction steps or a proof of concept.
- The affected artifact, stream, or release.
- A suggested mitigation, if available.

## Response

We follow coordinated disclosure:

- Reports are acknowledged within a few business days.
- We aim to complete an initial assessment within 7 days.
- Fix and disclosure timing depends on severity and on coordination with
  affected upstreams; we keep the reporter informed of progress.
- Reporters are credited in release notes unless they prefer to remain
  anonymous.

## Supported Versions

Bluefin Server has no long-term support branches. Versioning is derived from
the pinned freedesktop-sdk release (run `just version` / `just tags`), and
`systemd-sysupdate` pulls updates exclusively from the **latest** GitHub
Release. Only the latest release receives fixes; older point releases are not
maintained. If you are running an older release, update before reporting — the
issue may already be fixed.

## Verifying Release Artifacts

Every GitHub Release contains a single combined `SHA256SUMS` manifest and its
detached, ASCII-armored GPG signature `SHA256SUMS.gpg`, produced by the
`build-and-release` workflow. Verify a downloaded artifact set with the public
keyring shipped in this repository:

```sh
# Download SHA256SUMS and SHA256SUMS.gpg from the release, then:
gpg --no-default-keyring \
    --keyring files/os/sysupdate-keys/import-pubring.gpg \
    --verify SHA256SUMS.gpg SHA256SUMS
sha256sum --check SHA256SUMS
```

Running systems verify the same manifest automatically via `systemd-sysupdate`.
For the full trust model, key rotation, and transfer configuration, see
[`docs/skills/systemd-sysupdate-verification.md`](docs/skills/systemd-sysupdate-verification.md).

## Scope

This policy covers everything this repository produces and its build pipeline:

- The OS DDI payload, the offline installer disk image, and the k0s
  `systemd-sysext`.
- BuildStream elements, build tooling, and GitHub Actions workflows.
- Release signing and the `systemd-sysupdate` update/verification flow.

**Out of scope:** vulnerabilities in upstream components such as
freedesktop-sdk, GNOME build metadata, systemd, or k0s itself. Report those to
the respective upstream project; report to this repository only when the issue
is introduced by our integration, build, signing, or packaging of the
component.
