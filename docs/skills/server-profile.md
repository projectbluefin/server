---
name: server-profile
description: Use when designing Server onboarding, local cluster identity, MCP operations, modular profile activation, or optional cloud integrations.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-01"
  context7-sources: [/argoproj/argo-cd]
---
# Bluefin Server Product Contract

This file separates approved product requirements from the current upstream-asset implementation. The appliance composes prebuilt upstream components; it does not ship a Console or Argo executor fork. Requirements below that stock components do not implement remain acceptance gaps, not claimed capabilities.

## Local-first and cluster identity contract

These are binding product requirements; the acceptance boundary distinguishes them from exercised release evidence.

- The owner authenticates with a **dedicated local cluster identity** shared across the dashboard, product API, and MCP access. It is not an OS user, root password, SSH identity, or mounted administrator kubeconfig.
- One machine is a complete locally managed homelab. First login, later login, ordinary LAN administration, and identity recovery require no GitHub/Tailscale account, hosted identity provider, or WAN access.
- Normal setup is install, open the discovered local web UI, confirm ownership once, and create the cluster account. The product handles cluster bring-up, networking, discovery, certificate/key generation, and enrollment. Owners do not configure Kubernetes, run a signing CLI, manage keys or certificate fingerprints, seal TPM credentials, install kc-agent, or log in to the OS. Physical-console/SSH break-glass recovery remains optional operator tooling, not the normal setup path.
- Local identity and authorization are real security controls. Provision the first cluster administrator privately, hash local passwords, generate session keys per installation, and keep credentials out of public images, Git, logs, and MCP results. Workload ServiceAccounts remain distinct from human identities and receive only required permissions.
- First setup assumes a trusted home LAN. Use a per-node HTTPS certificate with explicit trust on first use, not a claim of automatic authentication of an unseen server. Prefer private browser pairing when console output is available; otherwise a headless node permits its first LAN owner claim only inside a short enrollment window beginning when the UI is ready. Another LAN device can claim or intercept during that initial window; this is the owner-approved convenience/security trade-off. Claim is atomic and enrollment closes durably afterward. Codes expire and are single-use, with per-source throttling rather than a global lockout. Reopening recovery requires explicit physical-console authorization and preserves cluster/workload state. No new key tool, secret-on-ESP provisioning, or hosted identity is required.
- Provide authenticated HTTPS private-network access and owner-controlled local credential recovery. Protect dashboard/API/MCP access, including streaming connections; unauthenticated access, expired tokens, and insufficient privileges fail closed. Never use development-login bypass as authentication.
- Cloud identity, remote access, feedback, and AI providers are optional and off unless configured. Enabling them does not remove local access or recovery; provider outage does not lock out the owner.
- Locally stored data, configuration, and last usable desired state survive restarts and WAN outages. The owner connects an existing Git repository, including LAN-hosted Git; no Git-hosting service or hosted account is required. Product Git access is pull-only for this milestone: owners supply commits; the product does not push commits, create branches, or open repository changes. This does not make MCP cluster operations read-only. Unavailable update/Git sources remain visible without erasing working state or blocking local authentication.
- Local-first does not claim every image/asset is already offline. Document acquisition requirements separately. With assets present, acceptance blocks WAN while retaining LAN and proves first admin login, real cluster data, workflow execution, restart/session persistence, recovery, and unauthorized-request denial from a second LAN machine.

## Cluster operating interface

- Authenticated MCP is the normal cluster-operating interface, not a read-only diagnostics add-on. Dashboard, product API, and MCP share the dedicated local cluster identity; users do not authenticate to the OS.
- Provide authorized read/write operations for workloads and Argo resources. MCP may create or update explicitly designated top-level user Applications that are not owned by a Git-synced parent or another reconciler. Git-owned Applications, including app-of-apps children, change only through owner-supplied commits; missing tracking metadata alone is not permission to adopt them. Do not strip tracking/ownership metadata or patch managed child workloads into a competing loop. Argo Workflows executes automation; Argo CD maintains Git-owned desired state.
- Human authorization, workload ServiceAccounts, Kubernetes RBAC, and admission controls are separate layers. Apply explicit tool/resource/namespace scopes; never expose an administrator kubeconfig or equate a tool annotation with permission.
- Every destructive MCP create/edit/delete request requires fresh explicit owner confirmation in addition to permissions. Bind one-time request approval to the exact payload and targets, expire it, and reject replay or changed targets; an agent cannot approve itself. This includes indirect workflow and GitOps-pruning effects. The owner may explicitly authorize an immutable Cron/template revision and target set for its stated recurring controller runs under a fixed bounded executor. Edits to its schedule, resolved templates, source, or targets invalidate that schedule authorization before further execution. Schedule authorization does not approve unrelated actions or future MCP edits, and standing RBAC is never consent.
- Enforce owner intent at the authenticated product front end and enforce allowed effects through Kubernetes authorization/admission. A prompt, tool annotation, standing RBAC grant, or expiring bearer token is not proof of one-time confirmation. The normal operating identity cannot bypass the gate or acquire unrestricted destructive authority.
- No Helm or config/kubeconfig-view capability is exposed or invoked. Streamable HTTP MCP is distinct from a dashboard's REST endpoints and event streams. Optional transports/tools are not claimed to be absent from an upstream binary when merely disabled.
- Protect backend reachability with NetworkPolicy so workloads cannot bypass the authenticated front end and mint Console sessions. Authentication is not supplied by TLS alone, by developer login, or by merely supplying an OAuth bootstrap token.

## Acceptance boundaries

The product is not complete until an owner can authenticate locally, perform an authorized MCP mutation, run an Argo Workflow and retrieve its expected result, manage an authorized Argo CD Application, and recover/re-authenticate after restart without WAN identity services. Unauthorized callers, forbidden scopes, privileged workloads, unconfirmed destruction, and direct backend bypass must be rejected. Destructive-operation tests cover denial without approval, a correctly bound one-time approval, expired/replayed approval, changed targets, and indirect destructive effects.

Initial asset acquisition, version compatibility, update signing, and Kubernetes upgrades retain their existing contracts. See [systemd-sysext-extensions.md](systemd-sysext-extensions.md), [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md), and [kubeadm-sysext.md](kubeadm-sysext.md). Specific implementation sequencing belongs in the implementation plan, not a duplicate permanent policy.

## Upstream artifact integration and current gaps

- `include/server.yml` pins unchanged Flatcar runtime bytes. The canonical
  `files/server/manifests/source-lock.json` pins upstream container images and
  vendored resources. Its `maintained_resources` / `producer_sha256` fields
  also lock every `.yaml` / `.in` under `files/server/manifests` and
  `produce-baseline.py` itself: the build aborts with "maintained raw
  resources differ from source provenance lock" when they drift. After an
  intentional edit run `just relock-platform`
  (`produce-baseline.py --relock`), which rewrites only those two fields and
  re-validates the lock; upstream image/source pins stay a manual, reviewable
  change. Nodes pull those images at first use unless cached;
  the signed host inventory contains no custom Console/executor OCI archive.
- Native BuildStream elements assemble the immutable bare Git baseline and
  compile only Bluefin's stdlib lifecycle glue. They do not compile Console,
  Argo, Kubernetes, containerd, Cilium or MCP from upstream source.
  Snapshot production uses FSDK's minimal Git plumbing and `git fsck --full
  --strict`. The signed support extension carries `baseline-integrity.json`;
  native selection checks every copied/retained file against its SHA256
  inventory, rejects missing/extra files and symlinks, and binds HEAD to the
  profile commit. The node requires no host Git CLI.
- `just validate` checks version invariants and resolves the graph. Host
  `prepare-server.py` generates the baseline for inspection; `--verify` opts
  into a real disposable compatibility proof. Neither application builds nor
  kind proof are prerequisites for ordinary graph validation.
- Quotas and limit ranges are root bootstrap contracts, not public GitOps
  reconciliation inputs. The controller's read-only authority over them is
  intentional; the snapshot must not request permission to rewrite them.
  Workflow templates are bootstrapped before quota admission is applied;
  native handoff waits until all workflow/template/CronWorkflow usage counters
  exist. CRD Established alone does not mean quota-controller discovery finished.
- Explicit Complete initializes once, or joins a worker from valid private
  provisioning. Invalid join data never falls back to controller creation.
  Core/no-profile and existing cluster identity remain protected. Native
  installer intent is documented in [usb-installer.md](usb-installer.md); the
  request and credential schema that enroll a worker or drive a runtime
  transition are in [Root lifecycle control socket](#root-lifecycle-control-socket).
- Stock Console requires private `bluefin-console-oauth` keys `client-id`,
  `client-secret`, `frontend-url`, `allowed-logins` and `admin-logins`.
  Without them, Complete finishes with Console at zero replicas and native
  status `console_status: awaiting_oauth` (tty1: `Console awaiting OAuth`).
  Console is root-owned, excluded from mandatory readiness and public GitOps;
  missing OAuth never blocks the baseline, handoff, or cluster upgrades.
  After privately provisioning the Secret on an owned controller, use the
  physical `resume` operation. Native validation requires every field to be
  nonblank and the primary stock image to match before requesting one replica.
  This is optional operator configuration, not the planned local-owner flow.
  Its init guard rejects absent or empty configuration before the backend runs:
  the pinned upstream image otherwise mints a development-admin session when
  OAuth is absent, even with `DEV_MODE=false`. The guard checks configuration
  presence, not OAuth validity; operators must supply a working OAuth app.
  Console remains ClusterIP-only. It does not provide the planned dedicated
  local owner, browser pairing, physical account recovery, or custom root-backed
  product API. Development login/bootstrap bypass is not a substitute.
- Stock MCP is a separate core/read-only deployment using supported Kubernetes
  bearer authentication. Native confirmation elicitation is deny-by-default
  where configured, but an agent answering it is not proof of owner consent.
  The custom owner-bound destructive executor and shared local identity are
  not supplied by this stock cutover.
- Ordinary upstream workflows use task-result-only namespace authority, not
  arbitrary workload-delete authority. Stock Argo does not include the
  discarded fork's output-symlink confinement; sandbox credentials/results
  are an explicit isolation limitation, not a security guarantee.
- Runtime migration and manual per-node worker update semantics are canonical
  in [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md).
  No automated browser enrollment or remote worker updater is claimed.

## Root lifecycle control socket

Worker enrollment and runtime migration are operator actions on the node
itself; there is no LAN UI for them. The bootstrap daemon serves JSON over the
Unix socket `/run/bluefin-server/bootstrap.sock` (mode `0600`, and every
request whose `SO_PEERCRED` uid is not 0 is rejected with `peer_forbidden`).
The physical tty1 interface deliberately exposes only `status` and `resume`.

`GET /v1/status` returns the durable state: `schema`, `profile`, `role`,
`phase`, `ready`, `revision`, `cluster_id`, `runtime`, and when present
`error`, `upgrade_stage`, `upgrade_image_version`,
`pending_worker_upgrade_image_version`, `worker_upgrade_error` and
`console_status`.

Every mutating request is a `POST` carrying `expected_revision`, the
`revision` just read from `/v1/status`. A stale revision, a busy engine or a
state that does not allow the action answers `409`; nothing is retried
blindly. Each accepted request answers `202` and runs asynchronously, so poll
`/v1/status` for the outcome.

- `POST /v1/initialize` — `{"expected_revision": N}`. Resumes a **failed
  controller** only. It never initializes a fresh host: an unassigned host
  commits its role before the socket is served.
- `POST /v1/join` — `{"expected_revision": N, "join": {...}}`. Enrolls an
  unassigned host as a worker, or renews the credentials of a failed worker in
  the same cluster that has no kubelet identity yet. The accepted join object
  is persisted as `/var/lib/bluefin/server/private-join.json` and consumed by
  the join phase.
- `POST /v1/upgrade` — `{"expected_revision": N, "image_version": "..."}`.
  Starts, replaces or resumes a signed runtime transition. Semantics are
  canonical in
  [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md).

The join object (equally the on-disk `private-join.json`) has exactly these
fields, all required and all validated before any state is written:

| Field | Meaning | Accepted values |
| --- | --- | --- |
| `api_endpoint` | Controller API address | `host:6443`; host must be a private IP literal |
| `token` | kubeadm bootstrap token | `^[a-z0-9]{6}\.[a-z0-9]{16}$` |
| `ca_hash` | Cluster CA pin | `sha256:` plus 64 lowercase hex characters |
| `expires_at` | Credential expiry | RFC 3339 instant in the future, at most 15 minutes ahead |
| `cluster_id` | `kube-system` namespace UID of the controller | must equal the joining node's recorded cluster identity on renewal |

Unknown fields are rejected, so the request body carries no extra data. These
are short-lived private provisioning credentials: mint them on the controller
immediately before enrollment, deliver them over a private channel, and never
place them on installer media or in Git. The worker deletes
`private-join.json` once its kubelet identity exists.

Example, against a controller-minted join document:

```sh
revision=$(curl -sS --unix-socket /run/bluefin-server/bootstrap.sock \
  http://localhost/v1/status | jq .revision)
jq --argjson r "$revision" '{expected_revision: $r, join: .}' join.json |
  curl -sS --unix-socket /run/bluefin-server/bootstrap.sock \
    -H 'Content-Type: application/json' --data @- http://localhost/v1/join
```

## Existing-cluster compatibility checks

Do not run native Complete initialization on an already initialized cluster.
For application-only smoke, set the top-level Application's directory allowlist
before enabling automatic sync. A Core-only example is:

```yaml
directory:
  recurse: true
  include: '{argocd/10-core.yaml,argocd/40-valkey.yaml,argocd/50-network.yaml}'
  exclude: '**/kustomization.yaml'
```

Add only the application files being exercised. An unfiltered `platform` source
also selects Cilium and is not safe on a cluster with another CNI. Standard
NetworkPolicy objects alone do not prove enforcement by that existing CNI;
keep access private and do not claim backend isolation without runtime proof.

Verification: inspect the live directory filter, unchanged CNI pods and absence
of newly installed Cilium resources; verify the exact synced revision and actual
workflow/MCP results. Console readiness must not replace a real OAuth login test.

Source: [Argo CD directory selection](https://argo-cd.readthedocs.io/en/stable/user-guide/directory/)
(`context7: /argoproj/argo-cd`; include/exclude use brace-alternation glob patterns).
