# bluefin-cluster

Multi-node homelab: control plane discovery and passphrase-authenticated
join tokens. One static Go binary in the homelab sysext
(`homelab/bluefin-cluster.bst`, FSDK Go, vendored modules, offline). Roles
come from `HOMELAB_ROLE` in `/etc/bluefin/homelab.conf`; every unit is a
no-op without that file or outside its role.

| Command | Unit | Role | Does |
|---|---|---|---|
| `prepare` | `bluefin-cluster-prepare.service` (wanted by `kubeadm-init`, `k0scontroller`) | control-plane | hostname `localhost` → `bluefin-<machine-id[:8]>` (`/usr/libexec/bluefin-hostname`, which the base OS already runs on first boot); adds `controlPlaneEndpoint: <host>.local:6443` and `apiServer.certSANs` (`<host>.local`, `<host>`, global addresses) to `/etc/kubernetes/bluefin/init.yaml` unless it already sets an endpoint |
| `serve` | `bluefin-cluster-serve.service` (wanted by `kubelet`, `k0scontroller`) | control-plane | passphrase, TLS key, `/run/systemd/dnssd/bluefin-cluster.dnssd`, join service on TCP 6447 |
| `join` | `bluefin-cluster-join.service` (wanted by `multi-user.target`) | node | discover, exchange, `kubeadm join` or `/etc/k0s/token` + `k0s-first-boot.service`; then `/var/lib/bluefin-cluster/joined` and the passphrase removed from `homelab.conf` |
| `hosts` | `bluefin-cluster-hosts.service` (`.timer`: 2 min after boot, then every 5 min) | both | resolves the control plane's `<host>.local` through resolved and pins it in a marked `/etc/hosts` block (also done by `prepare` and before `kubeadm join`) |
| `passphrase` | — | control-plane | prints the join passphrase |

## Passphrase

Unless `HOMELAB_JOIN_PASSPHRASE` is set on the control plane, `serve`
generates 4 words from the vendored EFF large wordlist (its 7772
unhyphenated words: 51.7 bits) with `crypto/rand` on first start. It is
stored in `/var/lib/bluefin-cluster/passphrase` (0600, state directory 0700),
written to `/run/issue.d/50-bluefin-cluster.issue` (0600; agetty shows it on
the local and serial consoles) and printed by `bluefin-cluster passphrase`.
An operator-chosen passphrase must have at least 4 distinct words of 3+
letters and 20+ characters (it cannot be entropy-checked; a generated one is
preferred and `serve` logs a warning). Both sides normalise: printable ASCII
only, lower case, every run of space, tab, `-` or `_` becomes one `-`.

A node reads `HOMELAB_JOIN_PASSPHRASE` from `homelab.conf` or the
`bluefin-cluster.passphrase` credential and deletes the line after it
joined.

## Discovery

`serve` writes a DNS-SD service (`Type=_bluefin-cluster._tcp`, port 6447,
`TxtText=v=1 cluster=<name> runtime=kubeadm|k0s`; nothing secret) to
`/run/systemd/dnssd` once the control plane exists, and reloads
systemd-resolved. The base OS turns on mDNS on its wired links ("Node name,
mDNS and prompt" in
[tpm2-credential-sealing.md](../../../docs/skills/tpm2-credential-sealing.md)). A node calls
`io.systemd.Resolve.BrowseServices` (`more`, 10 s window) and
`ResolveService` on resolved's varlink socket and tries every instance whose
runtime matches; `HOMELAB_CONTROL_PLANE=host[:port]` skips mDNS. Browsing is
per link: resolved needs the `ifindex` (and the mDNS flags) to pick its mDNS
scope, so the node browses every up, multicast-capable link at once. IPv4
addresses are tried first; link-local ones are skipped.

Nodes reach the API at `<cp>.local:6443`. kubelet, kubectl and kubeadm are
statically linked Go programs whose resolver ignores nss-resolve and would
ask unicast DNS for a `.local` name (and `/etc/resolv.conf` lists the
uplink servers), so `hosts` pins the name in `/etc/hosts`, which they read
first; the timer follows DHCP changes. mDNS answers are not authenticated:
discovery only finds candidates, the exchange below decides. The
`.dnssd` file and `/run/systemd/dnssd` are made world-readable explicitly
(the serve unit's `UMask=0077` would hide them from resolved's own user).

## Protocol (v1)

TLS 1.3 only, no session tickets. The server certificate is a self-signed
ECDSA P-256 certificate generated at first start
(`/var/lib/bluefin-cluster/tls.{crt,key}`); the node does not verify it
against any CA. Instead both sides compute the channel binding

    B = (E, C)    E = TLS-Exporter("EXPORTER-Channel-Binding", "", 32)  (RFC 9266)
                  C = SHA-256(server leaf certificate DER)

and run CPace (filippo.io/cpace: ristretto255, HKDF-SHA256) over it with
`idA = "bluefin-cluster node"`, `idB = "bluefin-cluster control-plane"`,
`ad = lp("bluefin-cluster/v1") || lp(E) || lp(C)` (`lp` = 4-byte big-endian
length prefix). Frames are a 4-byte big-endian length plus one JSON object
(at most 64 KiB, unknown fields rejected):

1. N→CP `{"v":1, "node":<hostname>, "runtime":"kubeadm"|"k0s", "pake":msgA}`
   (msgA: 16-byte salt + 32-byte element). The CP rejects a bad version,
   node name, length or runtime without charging a guess; otherwise it
   charges one (below) and runs `cpace.Exchange`.
2. CP→N `{"pake":msgB, "confirm":tagS}` with

       th = SHA-256(lp("bluefin-cluster/v1") lp(E) lp(C) lp(msgA) lp(msgB) lp(node) lp(runtime))
       PRK = HKDF-Extract(SHA-256, salt=nil, ISK)
       kS, kC, kE = HKDF-Expand(PRK, "bluefin-cluster/v1 " + label + " " + th, 32)
                    label = "server confirm" | "client confirm" | "payload"
       tagS = HMAC-SHA256(kS, th)

3. The node checks tagS in constant time. On mismatch it stops: wrong
   passphrase or not the control plane. Otherwise N→CP `{"confirm":tagC}`,
   `tagC = HMAC-SHA256(kC, th)`.
4. The CP checks tagC, refunds the charged guess, mints, and sends
   `{"sealed": nonce(12) || AES-256-GCM(kE, nonce, payload, ad=th)}` with
   payload `{"cluster":..., "grant":{"runtime", "endpoint", "token",
   "caCertHashes", "k0sToken", "ttlSeconds"}}`.
5. The node opens it, requires the runtime it asked for, validates every
   field by pattern (they end up in YAML and command lines) and a lifetime in
   (0, 15 min] (seconds, not a timestamp: a new node's clock may be wrong).

Refusals are `{"error": "rate-limited"|"busy"|"denied"|"bad-request"|"runtime-mismatch"|"unavailable", "retryAfter": s}`.

**Tokens.** kubeadm: `kubeadm token create --ttl 15m0s --description
"bluefin-cluster join: <node>"` (usages authentication+signing, group
`system:bootstrappers:kubeadm:default-node-token`), the CA hash
`sha256:<hex SHA-256 of /etc/kubernetes/pki/ca.crt's SubjectPublicKeyInfo>`
and the `admin.conf` server (`<cp>.local:6443`). The node writes a
`JoinConfiguration` (0600, `/run`) with `discovery.bootstrapToken`
`{apiServerEndpoint, token, caCertHashes}` (never
`unsafeSkipCAVerification`), enables containerd and kubelet and runs
`kubeadm join --config`; a failed join is reset and retried with a fresh
token. k0s: `k0s token create --role=worker --expiry=15m0s` (embeds the CA
and server); the node writes `/etc/k0s/token` (0600) and starts
`k0s-first-boot.service`, which starts `k0sworker`.

**Rate limits.** Server: every PAKE run is charged before `Exchange`, under
one lock with the limit check, to the source (IPv4 address, or IPv6 /64)
and globally: 5 per source per 15 min, 20 per hour in all. Only a verified
tagC refunds that one attempt. One connection per source at a time, 4 in
all, 10 s for the TLS handshake and hello, 30 s per connection. The failure
log persists in `/var/lib/bluefin-cluster/failures.json`, so a restart does
not reset it. At most 10 tokens are minted per hour. Node: one budget of 20
unrefunded guesses per hour across every candidate it tries (a guess is
spent only once the peer answered with msgB: msgA alone lets a peer test
nothing); exponential backoff from 5 s to 5 min.

## Threat model

Attacker on the LAN: sniffs, spoofs mDNS, relays or rewrites connections,
runs a rogue client or a rogue control plane; no access to either host.

- The passphrase never leaves either host; it is not in mDNS, logs or the
  image. CPace gives neither role an offline dictionary attack: each
  protocol run tests one guess.
- Rogue client: one guess per charged attempt, 20 per hour in all (about
  2^17.4 per year against 2^51.7 for a generated passphrase). It never
  receives sealed data or causes a mint without tagC.
- Rogue control plane: one guess per node attempt, bounded by the node's
  budget however many instances it advertises; the node never sends tagC
  unless tagS verified, so it cannot be steered to a cluster that does not
  know the passphrase. A spoofed `<cp>.local` cannot impersonate the API
  server: kubeadm pins the CA by hash; k0s's token carries the CA.
- Relay or replay: E differs per TLS connection, so a relayed or replayed
  exchange yields a different generator and transcript and fails as one
  wrong guess (unit-tested with a terminating relay and with replayed
  messages).
- Passive observer: sees TLS only.

Residual risks: anyone with the passphrase can add nodes (by design; a
joined node can also register under another node's name through the
bootstrap CSR flow, as with any kubeadm token holder); the console and serial
logs show the passphrase; an attacker on the LAN can exhaust the global
budget or connection slots and delay joins (denial of service, accepted);
each bootstrap token stays valid for 15 minutes; several control planes
sharing one passphrase multiply an attacker's budget; filippo.io/cpace is
an unaudited implementation of an older CPace draft (reviewed: prime-order
group, canonical decoding, identity check, length-prefixed context);
mDNS discovery can be blocked or poisoned, which only delays joining.

## Tests

`go test ./...` (also run by the element build): good and wrong passphrase,
no secrets on the wire or in logs, rogue server, relay with mismatched
binding, replay, forged confirmation, per-source and global limits,
persistence, refund accounting, client budget across candidates, grant TTL
and field validation, AEAD tampering, varlink browse/resolve against a fake
resolved, init-config patching, CA hash. `tests/unit/test_homelab_cluster.py`
checks the units and packaging; `scripts/dogfood-homelab-cluster.sh` (`just
dogfood-homelab-cluster`) boots a control plane, a node and a
wrong-passphrase node in QEMU on one L2 segment.
