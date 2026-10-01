# Bluefin Server Homelab Implementation Plan

> Implementation approved with `workflowz`. Use an isolated worktree and named worker pools; integrate and verify each wave. No mutation of existing live clusters.

**Goal:** Install -> open the local UI -> claim the server -> create an account -> use the homelab. One node is sufficient; Git and additional nodes are optional.

**Architecture:** The existing FSDK Core supplies the signed OS and native installer. Flatcar Kubernetes/containerd sysexts supply the runtime; kubeadm initializes or joins it. Cilium handles networking, Argo CD Core reconciles Git, Argo Workflows runs automation, and KubeStellar Console provides the UI. Authenticated MCP is the operating API.

**Contract:** [server-profile.md](../../skills/server-profile.md) owns identity, local-first operation, and permissions. The owner approved trusted-home-LAN first setup; implementation defaults and their verification are recorded below.

## Boundaries

- Keep the FSDK base/kernel, Secure Boot, dm-verity, partition identity, native sysinstall/repart, existing Ignition support, and A/B OS updates. The base/kernel pivot in [#249](https://github.com/projectbluefin/server/issues/249) is outside this milestone.
- Runtime binaries stay in compatible sysexts, never the base `/usr`. Use Flatcar's Kubernetes/containerd images; do not activate another Kubernetes binary provider alongside them.
- Maintain plain YAML/Kustomize. No Flux, Helm invocation/rendering, shell OS installer, generic module engine, or bundled Git hosting/writer.
- No Redis software, PostgreSQL/MySQL, MinIO, KubeFlex, or federation engine in the default profile. Etcd and Console SQLite are required state; Valkey is conditional and disposable. Workflows has no SQL archive/offload stack.
- Preserve existing installations and private provisioning. Updates must not initialize a new cluster or change a node's role. A worker adds capacity, not control-plane HA.
- Keep secrets off public images, installer ESPs, logs, and MCP results. Null-key ESP credentials are obfuscation, not confidential headless provisioning.
- Cloud identity, AI providers, and Tailscale are optional. GPU support and HA require separate verified work; neither is a milestone claim.

Initial candidate versions: Kubernetes 1.36.5, containerd 2.4.1, Cilium 1.20.2, Argo CD 3.5.3, Workflows 4.1.4, Console 0.3.42, Kubernetes MCP Server 0.0.67. Confirm compatibility and pin digests before locking the release; these are not a tested combination.

## Execution decisions

1. **First contact:** per-node HTTPS with explicit first-use trust; private console pairing when available, otherwise a short first-LAN-claim window after UI readiness. The owner explicitly accepted initial LAN interception/claim risk. Enrollment closes after claim; physical recovery is not an OS shell.
2. **Console identity:** patch/build the pinned Console source for real local users and sessions; remove development/demo fallback at backend and frontend. Reuse its store and session machinery, not a proxy login or another identity service.
3. **Ownership and recovery:** use an immutable build-produced baseline Git snapshot mounted read-only only into Argo repo-server; no hosted Git service. Prove exact-revision offline repair. Private worker pairing and physical account/state recovery must preserve roles and workloads.
4. **Scheduled destruction:** explicit consent binds the immutable Cron/template revision and target set for bounded runs under the fixed executor; edits revoke authorization. Each destructive MCP request still needs fresh request-bound confirmation. This is not blanket future consent.

## Task 1: Package the runtime

**Files:** `include/server.yml`, `elements/server/`, existing image/SBOM elements and runtime transfers.

- [ ] Import unchanged compatible Flatcar Kubernetes/containerd images into the signed Bluefin release inventory; verify publisher provenance, versions, architecture, and digests. No unchecked bakery updates.
- [ ] Reuse existing containerd/kubelet host integration: explicit `/etc` configuration, systemd cgroups, modules/sysctls, resolver setup, and writable CNI paths. Restart containerd before kubelet and verify fresh pod creation.
- [ ] Store payloads outside merge-search directories; activate only the selected runtime links. Keep the Core runtime opt-in and record the active profile persistently.

## Task 2: Package the platform

**Files:** `files/server/manifests/{cilium,argocd,workflows,dashboard,mcp,reboot}/`, `elements/oci/server-sysext.bst`; migrate shared assets from the existing KubeStellar sysext.

- [ ] Vendor complete pinned resources: Cilium with VXLAN, Kubernetes IPAM and kube-proxy replacement; Argo CD Core; namespace-scoped Workflows; standalone Console; native MCP; reboot coordination.
- [ ] Maintain Cilium/Console raw resources against the selected upstream releases. Share dashboard assets instead of copying the old federation stack or its Argo server-only manifest.
- [ ] Use single-node-compatible scheduling and bounded resources. Add a pinned Valkey cache only after real CD sync/drift/cache-loss/restart proof with unchanged clients; do not substitute Redis on failure.

## Task 3: Bootstrap once

**Files:** `files/server/bootstrap/`, `files/server/profile.yaml`, existing sysext activation integration.

- [ ] Fresh Complete installs initialize a schedulable standalone node. Private join configuration takes precedence and selects worker behavior; Core stays minimal. Invalid joins fail rather than fall back to initialization.
- [ ] Order activation: sysexts -> containerd/kubelet -> kubeadm init/join -> Cilium -> identity and platform services. Persist kube-proxy-disabled configuration and require persistent `/etc` and `/var` for controllers.
- [ ] Resume interrupted setup without resetting working clusters or regenerating identity. Publish actual status and the collision-safe local address; never mark missing networking or image pulls as success.
- [ ] Apply the bundled baseline, then hand off only to its agreed reconciler/source. Bootstrap must not compete with GitOps after handoff.

## Task 4: Provide one login and operating interface

**Files:** shared Console deployment/RBAC/secret generation, existing `issue.d` status surface, `files/server/manifests/mcp/`, Console browser checks.

- [ ] Implement named local accounts using Console's account/session machinery. Remove development-login fallback, demo data, self-upgrade behavior, and the injected browser-side kc-agent gate. Persist account state and per-node TLS/session keys.
- [ ] Reuse browser pairing and existing private console/status output. Codes expire and are single-use; rate limiting must not permanently lock out the owner. Keep codes out of discovery responses, URLs, and logs. Headless behavior follows the approved first-contact policy, not an invented preparation tool.
- [ ] Share identity across UI/API/MCP. Isolate private backends and enforce authorization there too; NetworkPolicy is defense in depth, not a replacement for authentication. Expose native Streamable HTTP, not dashboard REST presented as MCP.
- [ ] Use `containers/kubernetes-mcp-server`, core tools only, scoped ServiceAccounts and admission. No administrator kubeconfig, Secret/config-view/exec exposure, or Helm capabilities. Allow authorized workload and Argo operations without privileged-resource access.
- [ ] MCP may manage explicitly designated top-level user Applications, never Git-owned children or their managed workloads. Missing tracking metadata does not establish ownership. Product Git access remains pull-only.
- [ ] Bind destructive requests to explicit owner intent and exact targets, consume approval once, and execute through a fixed bounded executor. Reject replay/changed targets and bound indirect workflow/pruning effects; do not attempt a general shell/YAML safety classifier. Scheduled consent remains subject to the approval gate above.

## Task 5: Integrate the native installer

**Files:** existing image/boot elements, sysinstall drop-in, repart definitions, `scripts/dogfood-installer.sh`.

- [ ] One signed multi-profile installer UKI: Complete is default profile `@0`; Core-for-builders is `@1`. Derive both from the existing command line, retain signing/verity inputs, and forward the selection through native credentials. No custom sysinstall screen or role flag.
- [ ] Bundle host modules, bootstrap resources, and signed inventory. Suppress the inherited root-password prompt for Complete; Core may retain its builder login path. Provide product account recovery without a default root password or passwordless rescue shell.
- [ ] Keep private worker enrollment in the same product flow. Do not expose join tokens on generic media. Use the same profile/module lock for Booty and authenticated network provisioning.
- [ ] State acquisition honestly: OS/host installation can be offline; container pulls need registries unless cached. After acquisition, local use and recovery must not depend on WAN identity services.

## Task 6: Update without competing owners

**Files:** existing sysupdate/reboot integration, bootstrap upgrade handling, Argo Applications/AppProjects.

- [ ] Keep signed OS/runtime delivery and maintenance-window reboot coordination. Kubernetes upgrades are explicit kubeadm transactions, not binary swaps; retain runtime configuration and coordinate workers afterward.
- [ ] Preserve role, profile, sessions, workloads, and prior runtime state. Back up etcd before version transitions; OS rollback is not database rollback. Define recovery without relying on the installer's destructive erase path.
- [ ] Connect the owner's existing LAN/remote Git repository through authenticated UI configuration. Git failure leaves local login and last working state intact. Never expose fetch credentials or let MCP override Git-owned resources.

## Task 7: Publish the complete product

**Files:** publishing/build workflow, release verification, Justfile, README, affected Booty/factory consumers.

- [ ] Keep `ghcr.io/projectbluefin/bluefin-server` and `bluefin-server-installer_<ver>.raw` as the normal product. Offer the existing `bluefin-server_<ver>.raw` Core DDI under advanced downloads, not a second OS build, peer SKU, or update channel.
- [ ] Migrate all inventory, transfer, SBOM/provenance, OCI, dogfood, and provisioner consumers together. Preserve payload/partition identities and existing client behavior; no compatibility aliases or surprise controller activation.
- [ ] Put install/use/add-node guidance before build instructions. Keep Alpha and single-node downtime limitations visible; only claim verified capabilities.

## Task 8: Prove the user journey

Extend existing checks; prefer consumer behavior over source-string assertions. Product implementation runs `just validate`, docs checks, and the existing unit suite, plus these release proofs:

- [ ] Default USB install reaches a real LAN login, live local dashboard, application, and successful workflow through authenticated MCP; local use works with WAN blocked after acquisition.
- [ ] Core remains minimal; a privately enrolled second node joins as a worker and passes cross-node networking/scheduling.
- [ ] Git sync repairs drift; the selected cache survives loss/restart without changing CD's client contract.
- [ ] Reboot/update and recovery preserve identity and data, including fresh pod creation; failed bootstrap/update never silently resets the cluster.
- [ ] Unauthorized/bypass requests, bad signatures, expired joins, and unapproved or replayed destruction are rejected under the approved trust/consent model. The release inventory and OCI pull rehearsal pass.

For this documentation-only revision: run `python3 .github/scripts/docs-checks.py` and read through the plan. No runtime tests or live-cluster workflows during planning.

## References

- [Installer](../../skills/usb-installer.md), [runtime extensions](../../skills/systemd-sysext-extensions.md), [signed updates](../../skills/systemd-sysupdate-verification.md), [boot/install lifecycle](../../skills/ddi-installer.md), [Booty](../../skills/booty-integration.md).
- Upstream: [Flatcar Kubernetes](https://www.flatcar.org/docs/latest/orchestrate/kubernetes/getting-started-with-kubernetes/), [Argo CD Core](https://argo-cd.readthedocs.io/en/stable/operator-manual/core/), [KubeStellar Console](https://github.com/kubestellar/console), [Kubernetes MCP Server](https://github.com/containers/kubernetes-mcp-server).
