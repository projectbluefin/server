# KubeStellar Kiosk Client-Agent Gate

## Purpose

Bluefin Server's k0s workload is a dedicated KubeStellar/Kubernetes kiosk.
The Console must not show demo data or accept dashboard input before the
person using the kiosk connects a local `kc-agent` that can read their real
kubeconfig.

## Scope

The product uses a temporary, upstream-submittable Console derivative. The
derivative is packaged and deployed only through the k0s sysext; it does not
add Kubernetes, a GUI, or a shell to the base DDI.

The kiosk supports GitHub OAuth using a Kubernetes Secret supplied by the
operator. It does not claim support for other login providers because the
upstream Console currently implements GitHub OAuth only. A generic OIDC or
auth-proxy layer is separate future work, requiring its own provider
configuration and credentials.

## User Flow

1. The user reaches the authenticated Console.
2. Until a reachable local `kc-agent` reports healthy, a blocking setup modal
   covers the Console and prevents its controls from receiving input.
3. The modal explains that the agent runs on the user's client machine and
   supplies the existing upstream Homebrew installation command:

   ```sh
   brew tap kubestellar/tap && brew install kc-agent
   ```

4. It also supplies the existing origin-specific command:

   ```sh
   KC_ALLOWED_ORIGINS=<current-console-origin> kc-agent
   ```

5. The client starts `kc-agent` on the machine holding its kubeconfig. The
   kiosk detects its health endpoint and unlocks the Console only after a
   successful connection.
6. If the agent disconnects, the blocking modal returns. The Console does not
   fall back to sample data.

The browser connects directly to the client-local agent. The k0s workload
never receives the client's kubeconfig.

## Deployment Design

The vendored image starts from the currently pinned
`ghcr.io/kubestellar/console:v0.3.34` source revision and receives one narrow
`KIOSK_REQUIRE_AGENT` capability:

- The frontend reads the capability from the Console runtime configuration.
- When it is set, `AgentSetupDialog` opens automatically whenever local-agent
  state is not `connected`.
- Its close, snooze, and demo-data paths are not rendered in this mode.
- The modal uses the existing in-cluster Homebrew and origin-aware CORS
  instructions. It does not duplicate a separate Bluefin onboarding page.
- Once local-agent health is connected, existing Console data refetching loads
  the client cluster data.

Bluefin builds the derivative with BuildStream, not a Containerfile, publishes
it to the configured registry, and changes only
`files/k0s/manifests/kubestellar/40-kubestellar-console.yaml` to use it.

The manifest must:

- omit `DEV_MODE` and `ALLOW_DEV_MODE_IN_CLUSTER`;
- set `KIOSK_REQUIRE_AGENT=true`;
- reference a required Kubernetes Secret for `GITHUB_CLIENT_ID` and
  `GITHUB_CLIENT_SECRET`;
- retain the Console's existing `hostPort: 8080`.

The OAuth application's callback must equal the deployment's stable Console
origin. The application is not usable as an authenticated kiosk until an
operator provides that Secret and the matching callback registration.

## Security and Failure Behavior

- Demo mode is not a kiosk fallback. It deliberately suppresses real-agent
  discovery and is therefore excluded.
- The client agent runs on the client machine and must explicitly allow the
  Console's browser origin through `KC_ALLOWED_ORIGINS`.
- The credential Secret is referenced, never committed.
- A missing OAuth Secret leaves the Console deployment visibly unavailable;
  it does not silently start an unauthenticated dashboard.
- A missing or unreachable client agent leaves the setup modal active with
  the documented install and CORS commands available for copying.

## Verification

1. A Console-source test proves `KIOSK_REQUIRE_AGENT` opens a non-dismissible
   modal while agent status is disconnected, returns it on disconnect, and
   releases dashboard controls only after connection.
2. A BuildStream/manifest contract test proves the kiosk image is used, demo
   variables are absent, the capability is present, and OAuth comes only from
   the Secret reference.
3. A k0s integration test proves the Console starts without a client agent,
   the blocking setup modal appears, Homebrew-installed `kc-agent` connects
   with the displayed origin, and live kubeconfig-backed cluster data replaces
   demo data.

## Out of Scope

- Automatic Homebrew installation or automatic execution of commands on a
  client machine.
- Shipping or storing client kubeconfigs in Bluefin Server.
- Authentication providers beyond upstream GitHub OAuth.
- A generic ingress or production DNS setup.
