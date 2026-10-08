---
name: homelab-profile
description: The Bluefin Server Homelab profile, i.e. the Ignition templates that turn a node into a homelab control plane or node (kubeadm, or k0s), how they pull in the sysexts, and how the USB installer's Homelab entries use them. Load when changing, publishing or testing the templates.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-10-02"
---
# Homelab profile

Bluefin Server stays an OS plus opt-in pieces. The Homelab profile is those
pieces turned on by **one Ignition template**: the kubeadm and homelab
sysexts, a cluster, the default homelab component set and, on a control
plane, the homelab add-ons (Argo Workflows, a Kubernetes MCP server and the
KubeStellar Console). Use a template
on any node (network boot, an installed disk, a VM), or pick a Homelab
entry in the USB installer's boot menu ([usb-installer.md](usb-installer.md)).

## When to Use

- Changing, publishing or testing the templates in `files/homelab/templates/`.
- Explaining what a template turns on, and what to edit before using it.

## When NOT to Use

- The components and the applier (`bluefin-homelab-apply`): every key and
  default is in `files/homelab/sysext/homelab.conf.example`, the sysext in
  [systemd-sysext-extensions.md](systemd-sysext-extensions.md).
- Joining and the passphrase protocol:
  [`files/homelab/cluster/README.md`](../../files/homelab/cluster/README.md).
- kubeadm itself: [kubeadm-sysext.md](kubeadm-sysext.md); k0s:
  [k0s-sysext.md](k0s-sysext.md).

## Templates

One template per runtime and role. Butane has no conditionals and the role
decides which units start (a node must never run `kubeadm init` or start a
k0s controller), so the role is the file you pick, and each file works
unmodified apart from the values below.

| Template | Runtime | Role | sysupdate features | Starts |
|---|---|---|---|---|
| `homelab-control-plane` | kubeadm | control-plane | `kubeadm`, `homelab`, the add-ons | `kubeadm-init.service` (link) |
| `homelab-node` | kubeadm | node | `kubeadm`, `homelab` | `bluefin-cluster-join.service` (from the sysext) |
| `homelab-k0s-control-plane` | k0s | control-plane | `homelab`, the add-ons (+ k0s component) | `k0s-first-boot.service`; `/etc/sysconfig/k0s` drops `--single` |
| `homelab-k0s-node` | k0s | node | `homelab` (+ k0s component) | `k0s-first-boot-fetch.service` (link); the join starts k0s |

Every template also enables `bluefin-sysext-fetch.service` and `sshd.service`
(key-only root login; the key line is an `authorized_keys` comment
placeholder) and writes `/etc/bluefin/homelab.conf.template` plus a tmpfiles
`C` rule that copies it to `/etc/bluefin/homelab.conf` only while that file
is absent. A control-plane template's copy is `homelab.conf.example` with
`HOMELAB_ROLE=control-plane` set: the default component set (monitoring off)
and every optional block commented (MetalLB pool, ACME email, Argo CD root
repository, NFS, democratic-csi, GPU Operator, monitoring, the add-on
keys). A node's sets
`HOMELAB_ROLE=node` with `HOMELAB_JOIN_PASSPHRASE` and
`HOMELAB_CONTROL_PLANE` commented. Nothing secret is in a template.

`files/homelab/templates/<name>.bu` is the source; `<name>.ign` is it
compiled to Ignition 3.6 by `just homelab-templates` (butane pinned by digest
in the Justfile; `just homelab-templates 1` fails on a stale `.ign`).
`tests/unit/test_homelab_templates.py` checks the `.ign` against the `.bu`
without butane, the units and features each one turns on, and that none
carries a secret or turns monitoring on. Both forms are release assets
(signed `SHA256SUMS`, `scripts/publish-release.sh` requires all eight),
unversioned, so `releases/latest/download/homelab-control-plane.bu` names
the newest.

**Edit before use:** replace the SSH key line, and on a control plane set
what you need in `homelab.conf.template` (at least
`HOMELAB_METALLB_ADDRESSES`: without a pool MetalLB assigns nothing and
LoadBalancer Services, Envoy Gateway's included, stay pending). Ignition
(v2.27) reads Butane YAML as is, so the edited `.bu` can be passed directly;
compile it with butane only for other consumers.

## Add-ons

Three more opt-in sysexts, version-locked to the image like `homelab` and
each with its own sysupdate feature (`argo-workflows`, `mcp`,
`kubestellar`); the control-plane templates enable all three, node
templates none (only the control plane applies them). An add-on carries
no binaries, only manifests under
`/usr/share/bluefin/homelab/addons.d/<NN-id>/`, rendered offline by
`scripts/render-homelab-manifests.py` into `files/homelab/addons/` (images
pinned by digest). Each directory has an `addon` file, `<default>
<runtimes>`. After the base components, `bluefin-homelab-apply` applies
every merged add-on in name order with the same rules (CRDs Established
first, rollout waits, `secrets` generators, files with unset inputs skipped,
never deleting); `HOMELAB_<ID>=yes|no` in `homelab.conf` overrides the
default. The UIs are HTTPRoutes on the default Gateway (`homelab`, HTTPS on
port 443 of its MetalLB address, see "TLS" below) by host name under
`HOMELAB_DOMAIN` (default `home.arpa`): point `argo.`, `mcp.` and
`kubestellar.<domain>` at that address.

| Directory (sysext) | Default | What |
|---|---|---|
| `10-argo-workflows` (`argo-workflows`) | on | Argo Workflows v4.1.4, namespace-scoped install in `argo`; the server runs `--auth-mode=client --secure=false`: every API call carries a Kubernetes token, e.g. `kubectl -n argo create token argo-server` (bind a Role for your own account). |
| `20-mcp` (`mcp`) | on | [kubernetes-mcp-server](https://github.com/containers/kubernetes-mcp-server) v0.0.67, Streamable HTTP at `https://mcp.<domain>/mcp`. Read-only (`read_only = true`, Secrets denied); `require_oauth` with token passthrough: a request without a bearer token gets 401, and the API server authenticates and authorizes every tool call. The client token is Kubernetes-generated, never logged: `kubectl -n mcp get secret mcp-client-token -o jsonpath='{.data.token}' \| base64 -d` (`mcp-client`, ClusterRole `view`). `HOMELAB_MCP_READ_WRITE=yes` turns the write tools on and binds `edit`; switching back hides the tools, and the binding stays until you delete `clusterrolebinding/mcp-client-edit`. |
| `30-kubestellar-console` (`kubestellar`) | on | KubeStellar Console v0.3.42, deployed as is: see "KubeStellar Console sign-in" below. |
| `31-kubestellar-full` (`kubestellar`) | off | `HOMELAB_KUBESTELLAR_FULL=yes`: KubeStellar core chart 0.30.0 (KubeFlex and the PostCreateHooks that install the KubeStellar controllers into the ITS/WDS control planes you create), with a pinned Postgres in place of KubeFlex's runtime Helm install. Not covered by the QEMU check. |

**TLS.** The add-on HTTPRoutes take only the Gateway's `https` listener
(`sectionName: https`), so a bearer token, the Console's login password and
its session cookie never cross the LAN in cleartext; on port 80 the add-on
names answer with a 301 to `https://` (`40-envoy-gateway/21-http-redirect.yaml`).
The certificate (`homelab-tls` in `envoy-gateway-system`, for `argo.`, `mcp.`
and `kubestellar.<domain>`) comes from the `homelab-ca` ClusterIssuer: a
self-signed CA that cert-manager creates once (ten years) and keeps in
`cert-manager/homelab-ca`; the leaf renews by itself and Envoy picks it up.
Browsers warn until you trust that CA, once per device:

```bash
kubectl -n cert-manager get secret homelab-ca -o jsonpath='{.data.ca\.crt}' | base64 -d > homelab-ca.crt
```

MCP clients and the `argo` CLI need it too (Go tools read `SSL_CERT_FILE`,
Node.js ones `NODE_EXTRA_CA_CERTS`). Trust the CA before the first visit:
the add-on routes send `Strict-Transport-Security: max-age=31536000`
(deliberately without `includeSubDomains`, which would pin every device
under the domain), and once a browser has that header it turns a
certificate warning for these names into a hard error with no
click-through. The Gateway does not use the `acme` ClusterIssuer:
HTTP-01 needs every name reachable from the internet, which a LAN domain
such as `home.arpa` never is, and a certificate that cannot be issued would
leave the add-ons unreachable. `HOMELAB_CERT_MANAGER=no` does the same:
the `https` listener has no certificate, and the applier warns for every
add-on it applies behind it.

**KubeStellar Console sign-in.** Without a GitHub OAuth app, the Console's
`GET /auth/github` signs in as its built-in admin (`dev-user`; upstream
kubestellar/console#20823) and sets the `kc_auth` session cookie (a JWT
signed with the generated `kubestellar-console-jwt` key) that every other
request needs; its in-cluster front end goes there by itself. `DEV_MODE` is
never set. `11-login-gate.yaml` is a second HTTPRoute for the same host that
takes `/auth/github`, `/auth/manifest/setup` and `/auth/manifest/callback`
(Exact matches, which outrank the Console route's `/` prefix, plus a
case-insensitive regular expression for the spellings the Console's router
also accepts) with an Envoy Gateway `SecurityPolicy` that adds HTTP basic
auth: the browser asks for user `admin` and the password the applier
generated (`@htpasswd:admin` in `secrets`: Secret `kubestellar-console-login`,
the `{SHA}` htpasswd line in `.htpasswd`, the password in `password`; made
once, never rotated, never logged). The control plane shows the address and
login next to the join passphrase, the same way
(`/run/issue.d/51-kubestellar-console.issue`, 0600); elsewhere: `kubectl -n
kubestellar-console get secret kubestellar-console-login -o
jsonpath='{.data.password}' | base64 -d`. The GitHub App manifest flow also
needs the generated `CONSOLE_BOOTSTRAP_TOKEN`, and
`IGNORE_PERSISTED_OAUTH_CREDENTIALS=true` ignores any app it stored. A
NetworkPolicy lets only the homelab Gateway's Envoy proxies (namespace
`envoy-gateway-system`) reach the Console's pods, so nothing in the cluster
gets around the gate through its Service; Cilium (kubeadm) and kube-router
(k0s, which runs it with `--run-firewall`) enforce it, another CNI might not.

GitHub sign-in instead: a GitHub OAuth app (callback
`https://kubestellar.<domain>/auth/github/callback`) with its client id and
secret in `/etc/bluefin/homelab.d/kubestellar-console/github-client-id` and
`github-client-secret` (no trailing newline, mode 0600). The next applier
run makes the Secret `kubestellar-console-github-oauth` and rolls the Console
(pod annotation `homelab.bluefin.dev/console-sign-in`). Limit it with
`HOMELAB_KUBESTELLAR_CONSOLE_ALLOWED_LOGINS` (comma separated; without it
any GitHub account can sign in, and the applier warns) and name admins with
`HOMELAB_KUBESTELLAR_CONSOLE_ADMIN_LOGINS`. The login password stays in
front of `/auth/github`. Back to password sign-in: remove both files and
`kubectl -n kubestellar-console delete secret
kubestellar-console-github-oauth` (the applier never deletes).

Mind that:
- everyone with the password is the same admin (`dev-user`): no personal
  identity or audit trail; GitHub sign-in gives one;
- the password and the session cookie are only as safe as the trust in the
  homelab CA: a browser that clicked through the certificate warning instead
  of trusting the CA cannot tell the Gateway from an impostor on the LAN;
- signing out ends the Console session, but the browser keeps the basic-auth
  login until it is closed, so signing in again does not ask for it;
- the gate covers the session-creating endpoints of Console v0.3.42 (its
  `/auth/*` routes, checked against its source): check them again, and run
  `just dogfood-homelab-templates`, when bumping the Console.

The `kubestellar` sysext used to be a k0s-only appliance (Argo CD,
KubeStellar and a loopback kiosk seeded into `/var/lib/k0s/manifests`).
That path is gone: a k0s node gets the Console through the homelab applier
(the `homelab` and `kubestellar` features and a `homelab.conf`), and Argo CD
comes from the base set. Manifests a node seeded before stay in
`/var/lib/k0s/manifests/` and k0s keeps applying them until removed.

## Using a template

Pass the file as the node's `ignition.config` system credential (SMBIOS type
11, QEMU fw_cfg, an encrypted `/loader/credentials/ignition.config.cred`), or
serve it as a network-booted node's `bluefin-node.ign`
([ddi-installer.md](ddi-installer.md), "Ignition (opt-in)"). On its first
boot (and on the first boot of each new image version)
`bluefin-sysext-fetch.service` installs the enabled features' sysexts for the
running version and merges them; how it finds them (the installer's copy on
the ESP, the boot server, or the release through `systemd-sysupdate`) is in
[systemd-sysext-extensions.md](systemd-sysext-extensions.md). On an installed
node the enabled features keep the sysexts in step with OS updates. The
cluster images are pulled from the internet at `kubeadm init` and by the
applier. A diskless node keeps `/var`, and so every image, in RAM: with
the default set kubelet reports DiskPressure and evicts pods unless the
node has a disk for `/var` (an Ignition `var.mount`, as in
`tests/fixtures/ignition/var-on-disk.ign`) or far more RAM.

**Joining.** The control plane generates a join passphrase and shows it on
its consoles (`bluefin-cluster passphrase`). Give it to a node as
`HOMELAB_JOIN_PASSPHRASE` in its template's `homelab.conf.template`, as the
`bluefin-cluster.passphrase` credential, or at the USB installer's prompt.
A node removes it from `homelab.conf` once joined; a copy you put into a
provisioning config stays wherever that config is kept.

**Ignition runs on every boot that carries the config** (always on a diskless
node; on a disk installed from the USB stick until the first OS update
replaces the boot entry that carries it). Every file a template writes is
rewritten then, so change those in the template; `homelab.conf` is the
exception, created once and yours to edit afterwards on an installed node.

**Access.** No identity layer: `ssh root@<node>` with your key; `kubectl` as
root uses kubeadm's `/etc/kubernetes/admin.conf` (k0s:
`/var/lib/k0s/pki/admin.conf`); Argo CD's built-in `admin` with the
password in `argocd-initial-admin-secret`; the KubeStellar Console's
`admin` login (above).

**k0s** is the alternative (the add-ons work the same on it): the two k0s templates, not offered by the USB
installer, which installs kubeadm only.

## Verify

- `python3 -m pytest tests/unit/test_homelab_templates.py tests/unit/test_sysext_fetch.py tests/unit/test_homelab_installer.py`
- `just homelab-templates 1` (podman)
- `python3 -m pytest tests/unit/test_homelab_addons.py` and
  `tests/unit/bluefin-homelab-apply_test.bats` (add-on discovery, order,
  gates)
- `python3 -m pytest tests/unit/test_render_homelab_manifests.py` after
  changing `scripts/render-homelab-manifests.py` (its transforms, offline)
- `just dogfood-homelab-templates`: a diskless control plane from
  `homelab-control-plane.bu` and a node from `homelab-node.ign` with the
  passphrase it showed; the default set applied (monitoring off, MetalLB
  without a pool), a local-path PVC bound, both nodes Ready; the Gateway
  serves the add-ons over HTTPS with a certificate that verifies against
  the homelab CA, and port 80 redirects without asking for the login; the
  add-ons: Argo Workflows answers 401 without a token
  and accepts a `kubectl create token` one, the MCP server answers 401
  without a token, reads with the `mcp-client` token and refuses a write
  tool; the Console is deployed without OAuth, `/auth/github` through the
  Gateway answers 401 without the login (and in another spelling) and,
  with the generated one, redirects with a `kc_auth` cookie that
  `/api/me` accepts as the admin; a pod in another namespace cannot reach
  the Console's Service (NetworkPolicy), and the login is on the console,
  not in the journal. Needs guest internet.
- `just dogfood-homelab-installer`: the same from the USB installer's Homelab
  entries, offline installs ([usb-installer.md](usb-installer.md)).
