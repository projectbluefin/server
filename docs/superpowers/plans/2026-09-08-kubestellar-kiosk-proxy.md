# KubeStellar Kiosk Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a first-boot KubeStellar kiosk whose authenticated Console
blocks dashboard access until a client-local `kc-agent` becomes healthy.

**Architecture:** Keep the upstream Console image unmodified. The k0s sysext
ships Nginx configuration and CSP-safe static assets, systemd-tmpfiles seeds
them to `/var/lib/k0s/kiosk`, and a single-node proxy Deployment mounts them
read-only, owns host port 8080, and reverse-proxies Console. A base-DI
first-boot service installs and merges the optional sysext before starting the
controller; an interactive VM recipe provides the local development journey.

**Tech Stack:** BuildStream, systemd-sysupdate, systemd-sysext,
systemd-tmpfiles, systemd services, k0s, Kubernetes, Nginx, JavaScript, CSS,
QEMU, just, pytest.

**Spec:** `docs/superpowers/specs/2026-09-08-kubestellar-kiosk-design.md`

## Global Constraints

- Keep k0s, KubeStellar, Nginx, and kiosk assets in the optional sysext; never
  add them to the base DDI.
- Do not add a shell to the target DDI. System services call native binaries
  directly.
- Do not add a Containerfile or an OCI-image publishing pipeline.
- The proxy must retain upstream production CSP headers and inject only
  same-origin external CSS and JavaScript.
- User-facing kiosk copy must come from the current upstream Console setup
  dialog; do not invent parallel onboarding copy.
- Omit `DEV_MODE` and `ALLOW_DEV_MODE_IN_CLUSTER`. The credential Secret is
  referenced, never committed.
- GitHub OAuth is the sole supported provider. The callback must be the
  deployed Console origin.
- The client agent runs on the client machine; it reads that machine's
  kubeconfig and is never deployed in k0s.
- The published Installer remains interactive. Its headless smoke target alone
  passes `unattended` through an exported PXE command line.
- The VM forwards only `127.0.0.1:8080` to guest port 8080; it is not
  production networking.
- Do not use `git add -A` or `git add .`. Every commit includes the required
  Copilot attribution trailers.

## File Structure

| Path | Responsibility |
|---|---|
| `files/k0s/kiosk/nginx.conf` | Reverse proxy, same-origin asset serving, and HTML-only asset injection. |
| `files/k0s/kiosk/kiosk-gate.js` | Session-aware local-agent health gate and copied upstream setup commands. |
| `files/k0s/kiosk/kiosk-gate.css` | Full-page input-blocking presentation for the gate. |
| `files/k0s/manifests/kubestellar/40-kubestellar-console.yaml` | Internal upstream Console plus required GitHub OAuth Secret references. |
| `files/k0s/manifests/kubestellar/41-kubestellar-kiosk-proxy.yaml` | Single-node public Nginx proxy Deployment that mounts kiosk assets read-only. |
| `files/k0s/sysext/k0s-manifests.conf` | Seeds kiosk runtime assets alongside manifests. |
| `elements/oci/k0s-sysext.bst` | Adds kiosk assets to the versioned EROFS sysext. |
| `files/os/systemd/system/k0s-first-boot.service` | Retry-safe sysext activation and controller startup. |
| `files/os/systemd/system-preset/zz-enable-k0s-first-boot.preset` | Enables that bootstrap unit on installed systems. |
| `elements/bluefin-server/os-k0s-first-boot.bst` | Imports first-boot unit files into the base DDI. |
| `Justfile` | Persistent interactive `install-vm` developer flow. |
| `tests/unit/test_kubestellar_kiosk.py` | Static asset, manifest, and secret-wiring contracts. |
| `tests/unit/test_k0s_first_boot.py` | First-boot retry/order contracts. |
| `tests/unit/test_vm_dashboard_contract.py` | VM forwarding and browser-readiness contracts. |

---

### Task 1: Package a CSP-safe kiosk proxy gate

**Files:**
- Create: `files/k0s/kiosk/nginx.conf`
- Create: `files/k0s/kiosk/kiosk-gate.js`
- Create: `files/k0s/kiosk/kiosk-gate.css`
- Modify: `files/k0s/sysext/k0s-manifests.conf`
- Modify: `elements/oci/k0s-sysext.bst`
- Create: `tests/unit/test_kubestellar_kiosk.py`

**Interfaces:**
- Consumes: upstream Console's production `Content-Security-Policy` with
  `script-src 'self'`, `style-src 'self'`, its localStorage
  `kc-has-session` marker, and the loopback agent health endpoint
  `http://127.0.0.1:8585/health`.
- Produces: `/var/lib/k0s/kiosk/nginx.conf`,
  `/var/lib/k0s/kiosk/kiosk-gate.js`, and
  `/var/lib/k0s/kiosk/kiosk-gate.css`, which Task 2 mounts read-only.

- [ ] **Step 1: Write failing proxy asset contracts**

Create `tests/unit/test_kubestellar_kiosk.py` with these assertions:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIOSK = ROOT / "files" / "k0s" / "kiosk"
KIOSK_CONF = KIOSK / "nginx.conf"
KIOSK_JS = KIOSK / "kiosk-gate.js"
KIOSK_CSS = KIOSK / "kiosk-gate.css"
TMPFILES = ROOT / "files" / "k0s" / "sysext" / "k0s-manifests.conf"
SYSEXT = ROOT / "elements" / "oci" / "k0s-sysext.bst"


def test_kiosk_assets_are_packaged_and_seeded() -> None:
    sysext = SYSEXT.read_text(encoding="utf-8")
    tmpfiles = TMPFILES.read_text(encoding="utf-8")

    assert KIOSK_CONF.is_file()
    assert KIOSK_JS.is_file()
    assert KIOSK_CSS.is_file()
    assert "path: files/k0s/kiosk" in sysext
    assert "directory: kiosk-src" in sysext
    assert "cp -a kiosk-src/. sysext/usr/share/k0s/kiosk/" in sysext
    assert (
        "C+ /var/lib/k0s/kiosk - - - - /usr/share/k0s/kiosk"
        in tmpfiles
    )


def test_proxy_injects_only_csp_safe_same_origin_assets() -> None:
    nginx = KIOSK_CONF.read_text(encoding="utf-8")

    assert "resolver kube-dns.kube-system.svc.cluster.local valid=10s;" in nginx
    assert 'set $console_upstream "kubestellar-console.kubestellar-console.svc.cluster.local:8080";' in nginx
    assert "proxy_pass http://$console_upstream;" in nginx
    assert 'proxy_set_header Accept-Encoding "";' in nginx
    assert "sub_filter_types text/html;" in nginx
    assert 'sub_filter \'</head>\' \'<link rel="stylesheet" href="/kiosk-gate.css"></head>\';' in nginx
    assert 'sub_filter \'</body>\' \'<script defer src="/kiosk-gate.js"></script></body>\';' in nginx
    assert "Content-Security-Policy" not in nginx


def test_gate_waits_for_session_and_blocks_until_agent_health() -> None:
    script = KIOSK_JS.read_text(encoding="utf-8")
    css = KIOSK_CSS.read_text(encoding="utf-8")

    assert "kc-has-session" in script
    assert "http://127.0.0.1:8585/health" in script
    assert "brew tap kubestellar/tap && brew install kc-agent && kc-agent" in script
    assert "KC_ALLOWED_ORIGINS=${window.location.origin} kc-agent" in script
    assert "aria-modal" in script
    assert "addEventListener('keydown'" in script
    assert "pointer-events: auto" in css
    assert "z-index: 2147483647" in css
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```sh
python3 -m pytest tests/unit/test_kubestellar_kiosk.py -q
```

Expected: FAIL because the kiosk asset directory, sysext source, and tmpfiles
copy rule do not exist.

- [ ] **Step 3: Add the proxy and gate assets**

Create `files/k0s/kiosk/nginx.conf`:

```nginx
pid /tmp/nginx.pid;

events {
  worker_connections 1024;
}

http {
  include /etc/nginx/mime.types;
  default_type application/octet-stream;
  resolver kube-dns.kube-system.svc.cluster.local valid=10s;

  server {
    listen 8080;
    set $console_upstream "kubestellar-console.kubestellar-console.svc.cluster.local:8080";

    location = /kiosk-gate.js {
      alias /etc/kubestellar-kiosk/kiosk-gate.js;
      add_header Cache-Control "no-store";
    }

    location = /kiosk-gate.css {
      alias /etc/kubestellar-kiosk/kiosk-gate.css;
      add_header Cache-Control "no-store";
    }

    location / {
      proxy_pass http://$console_upstream;
      proxy_http_version 1.1;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_set_header Accept-Encoding "";
      proxy_set_header Connection "";
      sub_filter_once on;
      sub_filter_types text/html;
      sub_filter '</head>' '<link rel="stylesheet" href="/kiosk-gate.css"></head>';
      sub_filter '</body>' '<script defer src="/kiosk-gate.js"></script></body>';
    }
  }
}
```

Create `files/k0s/kiosk/kiosk-gate.js`. Use only the upstream dialog's
existing title, description, and commands. The gate becomes visible only
after the Console sets `kc-has-session`, preventing it from obscuring OAuth:

```javascript
(() => {
  const sessionKey = 'kc-has-session'
  const healthURL = 'http://127.0.0.1:8585/health'
  const gateID = 'kubestellar-kiosk-gate'

  const hasSession = () => {
    try {
      return window.localStorage.getItem(sessionKey) === 'true'
    } catch {
      return false
    }
  }

  const removeGate = () => document.getElementById(gateID)?.remove()

  const showGate = () => {
    if (document.getElementById(gateID)) return

    document.body.insertAdjacentHTML('beforeend', `
      <section id="${gateID}" class="kiosk-gate" role="dialog" aria-modal="true">
        <div class="kiosk-gate__dialog">
          <h1>Connect the kc-agent</h1>
          <p>Monitor your real clusters from this console</p>
          <p>Run agent on machine access kubeconfig</p>
          <code>brew tap kubestellar/tap && brew install kc-agent && kc-agent</code>
          <code>KC_ALLOWED_ORIGINS=${window.location.origin} kc-agent</code>
        </div>
      </section>
    `)
  }

  const updateGate = async () => {
    if (!hasSession()) {
      removeGate()
      return
    }

    try {
      const response = await fetch(healthURL, { credentials: 'omit' })
      if (!response.ok) throw new Error(`kc-agent health: ${response.status}`)
      removeGate()
    } catch {
      showGate()
    }
  }

  document.addEventListener('keydown', (event) => {
    const gate = document.getElementById(gateID)
    if (gate && !gate.contains(event.target)) event.preventDefault()
  }, true)
  window.setInterval(() => void updateGate(), 2_000)
  void updateGate()
})()
```

Create `files/k0s/kiosk/kiosk-gate.css`:

```css
.kiosk-gate {
  position: fixed;
  inset: 0;
  z-index: 2147483647;
  display: grid;
  place-items: center;
  padding: 1rem;
  background: rgb(0 0 0 / 75%);
  pointer-events: auto;
}

.kiosk-gate__dialog {
  width: min(42rem, 100%);
  padding: 2rem;
  color: #fff;
  background: #171717;
  border: 1px solid #525252;
  border-radius: 0.5rem;
}

.kiosk-gate__dialog code {
  display: block;
  margin-top: 1rem;
  padding: 0.75rem;
  overflow-wrap: anywhere;
  background: #262626;
}
```

Add this source to `elements/oci/k0s-sysext.bst`:

```yaml
  - kind: local
    path: files/k0s/kiosk
    directory: kiosk-src
```

Create `sysext/usr/share/k0s/kiosk` and copy the assets exactly once:

```sh
mkdir -p sysext/usr/share/k0s/kiosk
cp -a kiosk-src/. sysext/usr/share/k0s/kiosk/
```

Append this tmpfiles rule to
`files/k0s/sysext/k0s-manifests.conf`:

```text
C+ /var/lib/k0s/kiosk - - - - /usr/share/k0s/kiosk
```

- [ ] **Step 4: Run proxy contracts and validate Nginx syntax**

Run:

```sh
python3 -m pytest tests/unit/test_kubestellar_kiosk.py tests/unit/test_k0s_manifests.py -q
podman run --rm \
  -v "$PWD/files/k0s/kiosk:/etc/kubestellar-kiosk:ro,Z" \
  nginx@sha256:62223d644fa234c3a1cc785ee14242ec47a77364226f1c811d2f669f96dc2ac8 \
  nginx -t -c /etc/kubestellar-kiosk/nginx.conf
just validate
```

The immutable Linux/amd64 Nginx digest exposes the stock `sub_filter` module.
Do not replace it with inline script injection or relax the Console CSP.

- [ ] **Step 5: Commit the kiosk proxy assets**

```sh
git add elements/oci/k0s-sysext.bst files/k0s/kiosk/nginx.conf files/k0s/kiosk/kiosk-gate.js files/k0s/kiosk/kiosk-gate.css files/k0s/sysext/k0s-manifests.conf tests/unit/test_kubestellar_kiosk.py
git commit -m "feat(k0s): add Kubestellar kiosk agent gate" \
  -m "Assisted-by: GPT-5.6 Terra via GitHub Copilot" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Wire the production Console and kiosk proxy Deployment

**Files:**
- Modify: `files/k0s/manifests/kubestellar/40-kubestellar-console.yaml`
- Create: `files/k0s/manifests/kubestellar/41-kubestellar-kiosk-proxy.yaml`
- Modify: `tests/unit/test_kubestellar_kiosk.py`
- Modify: `tests/unit/test_k0s_manifests.py`

**Interfaces:**
- Consumes: Task 1's `/var/lib/k0s/kiosk` asset directory and internal
  `kubestellar-console.kubestellar-console.svc.cluster.local:8080` Service.
- Produces: the only guest `hostPort: 8080`, served by Nginx, and an upstream
  Console deployment which receives its GitHub OAuth credentials from the
  required `kubestellar-console-github-oauth` Secret.

- [ ] **Step 1: Extend the manifest contracts**

Append these tests to `tests/unit/test_kubestellar_kiosk.py`:

```python
CONSOLE_MANIFEST = (
    ROOT / "files" / "k0s" / "manifests" / "kubestellar"
    / "40-kubestellar-console.yaml"
)
PROXY_MANIFEST = (
    ROOT / "files" / "k0s" / "manifests" / "kubestellar"
    / "41-kubestellar-kiosk-proxy.yaml"
)


def test_console_uses_required_github_oauth_secret_without_demo_mode() -> None:
    console = CONSOLE_MANIFEST.read_text(encoding="utf-8")

    assert "DEV_MODE" not in console
    assert "ALLOW_DEV_MODE_IN_CLUSTER" not in console
    assert "hostPort:" not in console
    assert "name: GITHUB_CLIENT_ID" in console
    assert "name: GITHUB_CLIENT_SECRET" in console
    assert "name: kubestellar-console-github-oauth" in console
    assert "key: client-id" in console
    assert "key: client-secret" in console
    assert "optional: false" in console


def test_proxy_is_the_only_public_console_endpoint() -> None:
    proxy = PROXY_MANIFEST.read_text(encoding="utf-8")

    assert "name: kubestellar-kiosk-proxy" in proxy
    assert "hostPort: 8080" in proxy
    assert "mountPath: /etc/kubestellar-kiosk" in proxy
    assert "hostPath:\n              path: /var/lib/k0s/kiosk" in proxy
    assert "readOnly: true" in proxy
    assert "nginx@sha256:62223d644fa234c3a1cc785ee14242ec47a77364226f1c811d2f669f96dc2ac8" in proxy
```

Extend `test_k0s_manifest_files()` to require
`41-kubestellar-kiosk-proxy.yaml`.

- [ ] **Step 2: Run the extended contracts and verify they fail**

Run:

```sh
python3 -m pytest tests/unit/test_kubestellar_kiosk.py tests/unit/test_k0s_manifests.py -q
```

Expected: FAIL because the Console still forces demo mode and owns host port
8080, does not require the OAuth Secret, and no proxy manifest exists.

- [ ] **Step 3: Make Console internal and deploy the proxy**

In `40-kubestellar-console.yaml`, remove both demo-mode environment entries
and the `hostPort` field. Add these required Secret references to the existing
Console container:

```yaml
        - name: GITHUB_CLIENT_ID
          valueFrom:
            secretKeyRef:
              name: kubestellar-console-github-oauth
              key: client-id
              optional: false
        - name: GITHUB_CLIENT_SECRET
          valueFrom:
            secretKeyRef:
              name: kubestellar-console-github-oauth
              key: client-secret
              optional: false
```

Create `41-kubestellar-kiosk-proxy.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kubestellar-kiosk-proxy
  namespace: kubestellar-console
  labels:
    app.kubernetes.io/name: kubestellar-kiosk-proxy
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app.kubernetes.io/name: kubestellar-kiosk-proxy
  template:
    metadata:
      labels:
        app.kubernetes.io/name: kubestellar-kiosk-proxy
    spec:
      containers:
      - name: kiosk-proxy
        image: nginx@sha256:62223d644fa234c3a1cc785ee14242ec47a77364226f1c811d2f669f96dc2ac8
        args:
        - nginx
        - -g
        - daemon off;
        - -c
        - /etc/kubestellar-kiosk/nginx.conf
        ports:
        - containerPort: 8080
          hostPort: 8080
          name: http
        volumeMounts:
        - name: kiosk-assets
          mountPath: /etc/kubestellar-kiosk
          readOnly: true
      volumes:
      - name: kiosk-assets
        hostPath:
          path: /var/lib/k0s/kiosk
          type: Directory
```

Do not create the Secret manifest. An absent Secret must prevent the upstream
Console Pod from starting instead of silently serving an unauthenticated or
demo Console. The operator registers GitHub's callback using the actual
stable public kiosk origin and creates the two-key Secret out of band.

- [ ] **Step 4: Run focused manifest validation**

Run:

```sh
python3 -m pytest tests/unit/test_kubestellar_kiosk.py tests/unit/test_k0s_manifests.py -q
just validate
```

- [ ] **Step 5: Commit the production kiosk wiring**

```sh
git add files/k0s/manifests/kubestellar/40-kubestellar-console.yaml files/k0s/manifests/kubestellar/41-kubestellar-kiosk-proxy.yaml tests/unit/test_k0s_manifests.py tests/unit/test_kubestellar_kiosk.py
git commit -m "feat(k0s): require agent connection in kiosk" \
  -m "Assisted-by: GPT-5.6 Terra via GitHub Copilot" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Activate the optional sysext on first boot

**Files:**
- Create: `files/os/systemd/system/k0s-first-boot.service`
- Create: `files/os/systemd/system-preset/zz-enable-k0s-first-boot.preset`
- Create: `elements/bluefin-server/os-k0s-first-boot.bst`
- Modify: `elements/bluefin-server/os-stack.bst`
- Create: `tests/unit/test_k0s_first_boot.py`

**Interfaces:**
- Consumes: the existing `70-k0s.transfer`, the sysext-provided
  `k0s-manifests.conf`, and `k0scontroller.service`.
- Produces: a preset-enabled base-DDI unit that retries activation until its
  controller starts and then records `/var/lib/k0s/.first-boot-complete`.

- [ ] **Step 1: Write failing first-boot contracts**

Create `tests/unit/test_k0s_first_boot.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "files" / "os" / "systemd" / "system" / "k0s-first-boot.service"
PRESET = ROOT / "files" / "os" / "systemd" / "system-preset" / "zz-enable-k0s-first-boot.preset"
ELEMENT = ROOT / "elements" / "bluefin-server" / "os-k0s-first-boot.bst"
STACK = ROOT / "elements" / "bluefin-server" / "os-stack.bst"


def test_k0s_first_boot_retries_until_controller_starts() -> None:
    service = SERVICE.read_text(encoding="utf-8")

    assert "ConditionPathExists=!/var/lib/k0s/.first-boot-complete" in service
    assert "Wants=network-online.target" in service
    assert "After=network-online.target" in service
    assert "Before=multi-user.target" not in service
    assert "Type=oneshot" in service
    assert "StateDirectory=k0s" in service
    assert "Restart=on-failure" in service
    assert "ExecStart=/usr/bin/systemd-sysupdate update" in service
    assert "ExecStart=/usr/bin/systemctl enable --now systemd-sysext.service" in service
    assert "ExecStart=/usr/bin/systemd-sysext merge" in service
    assert "ExecStart=/usr/bin/systemd-tmpfiles --create /usr/lib/tmpfiles.d/k0s-manifests.conf" in service
    assert "ExecStart=/usr/bin/systemctl daemon-reload" in service
    assert "ExecStart=/usr/bin/systemctl enable --now k0scontroller.service" in service
    assert "ExecStartPost=/usr/bin/touch /var/lib/k0s/.first-boot-complete" in service
    assert "ConditionFirstBoot" not in service


def test_k0s_first_boot_is_packaged_and_enabled() -> None:
    assert PRESET.read_text(encoding="utf-8") == "enable k0s-first-boot.service\n"
    assert "path: files/os/systemd/system" in ELEMENT.read_text(encoding="utf-8")
    assert "target: /usr/lib/systemd/system" in ELEMENT.read_text(encoding="utf-8")
    assert "bluefin-server/os-k0s-first-boot.bst" in STACK.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```sh
python3 -m pytest tests/unit/test_k0s_first_boot.py -q
```

Expected: FAIL because no first-boot service, import element, or preset exists.

- [ ] **Step 3: Add the retry-safe activation service**

Create `elements/bluefin-server/os-k0s-first-boot.bst`:

```yaml
kind: import
description: Install the first-boot k0s sysext activation unit.

sources:
  - kind: local
    path: files/os/systemd/system

config:
  target: /usr/lib/systemd/system
```

Add `bluefin-server/os-k0s-first-boot.bst` to the DDI stack near the existing
system-update and k0s-related base services.

Create `k0s-first-boot.service`:

```ini
[Unit]
Description=Activate k0s sysext after first installation
ConditionPathExists=!/var/lib/k0s/.first-boot-complete
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
StateDirectory=k0s
Restart=on-failure
RestartSec=30s
ExecStart=/usr/bin/systemd-sysupdate update
ExecStart=/usr/bin/systemctl enable --now systemd-sysext.service
ExecStart=/usr/bin/systemd-sysext merge
ExecStart=/usr/bin/systemd-tmpfiles --create /usr/lib/tmpfiles.d/k0s-manifests.conf
ExecStart=/usr/bin/systemctl daemon-reload
ExecStart=/usr/bin/systemctl enable --now k0scontroller.service
ExecStartPost=/usr/bin/touch /var/lib/k0s/.first-boot-complete

[Install]
WantedBy=multi-user.target
```

Create `zz-enable-k0s-first-boot.preset` containing:

```text
enable k0s-first-boot.service
```

The durable completion marker, written only after controller startup, permits
download, merge, seeding, and controller failures to retry on the current and
future boot. Do not use `ConditionFirstBoot=yes`: it would permanently skip a
transiently failed first activation.

- [ ] **Step 4: Run focused validation**

Run:

```sh
python3 -m pytest tests/unit/test_k0s_first_boot.py tests/unit/test_sysupdate_transfers.py tests/unit/test_k0s_manifests.py -q
just validate
```

- [ ] **Step 5: Commit the activation path**

```sh
git add elements/bluefin-server/os-k0s-first-boot.bst elements/bluefin-server/os-stack.bst files/os/systemd/system/k0s-first-boot.service files/os/systemd/system-preset/zz-enable-k0s-first-boot.preset tests/unit/test_k0s_first_boot.py
git commit -m "feat(k0s): activate sysext on first boot" \
  -m "Assisted-by: GPT-5.6 Terra via GitHub Copilot" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Provide a persistent interactive kiosk VM

**Files:**
- Modify: `Justfile`
- Create: `tests/unit/test_vm_dashboard_contract.py`

**Interfaces:**
- Consumes: interactive released Installer media, exported PXE inputs for the
  separate headless smoke target, and the proxy's guest `hostPort: 8080`.
- Produces: `just install-vm`, which persists a target disk and OVMF variables
  under `${XDG_STATE_HOME:-$HOME/.local/state}/bluefin-server/` and opens the
  host's default browser only when the kiosk responds.

- [ ] **Step 1: Write failing VM launcher contracts**

Create `tests/unit/test_vm_dashboard_contract.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JUSTFILE = ROOT / "Justfile"


def test_install_vm_keeps_state_and_forwards_only_loopback() -> None:
    justfile = JUSTFILE.read_text(encoding="utf-8")
    start = justfile.index("install-vm:")
    recipe = justfile[start:]

    assert "XDG_STATE_HOME" in recipe
    assert "qemu-system-x86_64" in recipe
    assert "hostfwd=tcp:127.0.0.1:8080-:8080" in recipe
    assert "curl --silent --show-error --max-time 2 --output /dev/null http://127.0.0.1:8080/" in recipe
    assert "xdg-open http://127.0.0.1:8080/" in recipe
    assert "unattended" not in recipe
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```sh
python3 -m pytest tests/unit/test_vm_dashboard_contract.py -q
```

Expected: FAIL because `install-vm` does not exist.

- [ ] **Step 3: Add the interactive VM recipe**

Add `install-vm` next to `show-me-the-future` in `Justfile`:

1. Define
   `STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/bluefin-server/vm-$(just version)"`.
2. Create its target disk and copied OVMF variables only when absent.
3. On the first invocation, run `just export-installer`, decompress the raw
   Installer into `STATE_DIR`, and boot it graphically with OVMF. Wait for
   the interactive systemd-sysinstall flow to power it off.
4. Boot the installed disk graphically with this user network argument:

   ```text
   -nic user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:8080-:8080
   ```

5. Start that QEMU process in the background, retain its PID, and poll the
   tested `curl` command. Before each retry, verify the PID is alive; if it
   died, wait for it and return its error instead of treating a fixed timeout
   as readiness.
6. On readiness, call `xdg-open http://127.0.0.1:8080/` exactly once and keep
   QEMU attached until the user exits it. Clean up only that retained PID.

Do not add `unattended` to this interactive recipe. Leave
`show-me-the-future` as the independent headless smoke install based on the
exported PXE kernel and initrd.

- [ ] **Step 4: Run focused validation**

Run:

```sh
python3 -m pytest tests/unit/test_installer_contract.py tests/unit/test_vm_dashboard_contract.py -q
just validate
```

- [ ] **Step 5: Commit the VM flow**

```sh
git add Justfile tests/unit/test_vm_dashboard_contract.py
git commit -m "feat(vm): launch the Kubestellar kiosk" \
  -m "Assisted-by: GPT-5.6 Terra via GitHub Copilot" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 5: Build, prove the product flow, then document it

**Files:**
- Modify: `docs/skills/k0s-sysext-ops.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1-4 and an operator-provided,
  non-committed `kubestellar-console-github-oauth` Secret with registered
  stable callback origin.
- Produces: the one canonical kiosk operation after the source and runtime
  flow are both proven.

- [ ] **Step 1: Run repository build and static gates**

Run:

```sh
just build-ddi
just build-installer
just build-sysext
just test-unit
just validate
python3 .github/scripts/docs-checks.py
```

- [ ] **Step 2: Prove the authenticated client-agent journey**

On a clean VM state directory, run:

```sh
just install-vm
```

Before starting the Console, have the operator create the required Secret out
of band and register GitHub's callback with the VM's actual kiosk origin. In
the browser:

1. Complete GitHub OAuth; verify the upstream Console sets
   `kc-has-session`.
2. Verify the kiosk modal covers all dashboard controls and presents the
   upstream Homebrew command and a `KC_ALLOWED_ORIGINS` command containing the
   exact browser origin.
3. On the client machine that holds a real kubeconfig, run that displayed
   command with the origin value. Confirm the agent health request succeeds,
   the gate disappears, and Console shows kubeconfig-backed cluster data
   rather than demo data.
4. Stop the client agent and confirm the gate returns.
5. In the guest, confirm `k0s-first-boot.service` succeeded only after
   `k0scontroller.service` and created `/var/lib/k0s/.first-boot-complete`.

- [ ] **Step 3: Document only the proven operation**

Update `docs/skills/k0s-sysext-ops.md` as the canonical kiosk runbook:

- Keep `just k8s` for existing installed hosts.
- Add the exact required Secret name and its `client-id` / `client-secret`
  keys without documenting any secret value.
- State that GitHub OAuth's callback is the actual stable kiosk origin.
- State that the setup screen supplies the client-local agent's existing
  Homebrew and CORS commands and that the server never receives the client
  kubeconfig.
- Add `just install-vm` and `http://127.0.0.1:8080/` for local development.

Add a README link to that one runbook section. Do not repeat its operational
instructions in README.

- [ ] **Step 4: Re-run final gates**

Run:

```sh
just test-unit
just validate
python3 .github/scripts/docs-checks.py
```

- [ ] **Step 5: Commit the proven documentation**

```sh
git add README.md docs/skills/k0s-sysext-ops.md
git commit -m "docs: describe Kubestellar kiosk operation" \
  -m "Assisted-by: GPT-5.6 Terra via GitHub Copilot" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Plan Review

- **Spec coverage:** Task 1 implements a same-origin, CSP-safe blocking gate
  and preserves OAuth reachability. Task 2 eliminates demo mode, wires GitHub
  credentials by Secret, and ensures only the proxy is public. Task 3 makes
  the optional payload first-boot usable without adding Kubernetes to the DDI.
  Task 4 provides the persistent local VM journey. Task 5 proves agent
  connect/disconnect behavior with real kubeconfig data, then documents it.
- **Boundary check:** The design uses the unmodified upstream Console image;
  it introduces neither a fork nor an OCI build/publish pipeline. Kubernetes
  and Nginx remain sysext-delivered, and the target DDI remains shell-free.
- **Failure behavior:** Missing OAuth credentials block the Console Pod;
  missing client agent blocks only dashboard input while retaining setup
  instructions; a first-boot failure retries until the controller starts.
- **Copy and CSP review:** The gate imports only same-origin external files,
  leaves the upstream CSP header untouched, and uses setup copy already
  present in upstream Console.
