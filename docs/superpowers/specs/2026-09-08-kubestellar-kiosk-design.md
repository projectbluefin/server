# KubeStellar Kiosk Client-Agent Gate

## Purpose

Bluefin Server's k0s workload is a dedicated KubeStellar/Kubernetes kiosk.
The Console must not show demo data or accept dashboard input before the
person using the kiosk connects a local `kc-agent` that can read their real
kubeconfig.

## Scope

The product vendors a temporary, upstream-submittable kiosk proxy layer. It is
packaged and deployed only through the k0s sysext; it does not add Kubernetes,
a GUI, a shell, a Containerfile, or a custom OCI-image publishing path to the
base DDI.

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

The vendored proxy is an Nginx Deployment that owns `hostPort: 8080` and
reverse-proxies the unmodified, internal `kubestellar-console` Service. The
sysext stages its configuration and assets in `/usr/share/k0s/kiosk`, and the
existing tmpfiles flow copies them to `/var/lib/k0s/kiosk` for the proxy to
mount read-only. The assets implement a narrow kiosk overlay:

- The proxy injects only same-origin CSS and JavaScript assets, retaining the
  upstream production Content Security Policy and its ban on inline scripts.
- The script waits for Console's `kc-has-session` marker before it activates,
  so the GitHub sign-in and callback flows remain usable.
- On those routes, the overlay covers the page and captures pointer and
  keyboard input while `http://127.0.0.1:8585/health` is unavailable.
- It displays the upstream Homebrew `kc-agent` and origin-aware CORS commands.
- On a successful local-agent health check, it removes itself and allows the
  Console's existing local-agent hook to fetch client-cluster data.
- If the agent disconnects, it returns and blocks Console input again.

This is a temporary integration seam, not a fork. The desired steady state is
an upstream `KIOSK_REQUIRE_AGENT` Console capability with the same behavior,
at which point the proxy can be removed.

The manifest must:

- omit `DEV_MODE` and `ALLOW_DEV_MODE_IN_CLUSTER`;
- reference a required Kubernetes Secret for `GITHUB_CLIENT_ID` and
  `GITHUB_CLIENT_SECRET`;
- remove `hostPort: 8080` from the Console Deployment;
- add the kiosk proxy and give only that Deployment `hostPort: 8080`.

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

1. An Nginx configuration test proves HTML injection targets only the Console
   page, upstream API and authentication paths are proxied unchanged, and the
   proxy syntax loads successfully.
2. A manifest contract test proves demo variables and the Console host port
   are absent, the proxy owns `hostPort: 8080`, and OAuth comes only from the
   Secret reference.
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
- A custom Console image or OCI-image publishing pipeline.
