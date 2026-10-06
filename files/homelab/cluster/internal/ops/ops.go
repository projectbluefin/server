// Package ops are the host-side steps around the join exchange: unique
// hostnames, the control plane's kubeadm init config, minting join tokens
// on the control plane and joining on a node.
package ops

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/pem"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

const (
	KubeadmInitConfig = "/etc/kubernetes/bluefin/init.yaml"
	KubeadmAdminConf  = "/etc/kubernetes/admin.conf"
	KubeadmCACert     = "/etc/kubernetes/pki/ca.crt"
	KubeadmKubelet    = "/etc/kubernetes/kubelet.conf"
	K0sAdminConf      = "/var/lib/k0s/pki/admin.conf"
	K0sTokenFile      = "/etc/k0s/token"
	CRISocket         = "unix:///run/containerd/containerd.sock"

	RuntimeKubeadm = "kubeadm"
	RuntimeK0s     = "k0s"

	// TokenTTL bounds every token the join service hands out.
	TokenTTL = 15 * time.Minute
)

var (
	hostnameRE = regexp.MustCompile(`^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`)
	tokenRE    = regexp.MustCompile(`^[a-z0-9]{6}\.[a-z0-9]{16}$`)
	caHashRE   = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
	endpointRE = regexp.MustCompile(`^[A-Za-z0-9.-]+:[0-9]{1,5}$|^\[[0-9A-Fa-f:.]+\]:[0-9]{1,5}$`)
	k0sTokenRE = regexp.MustCompile(`^[A-Za-z0-9+/=]{16,}$`)
)

// Root prefixes every host path; tests point it at a temporary directory.
var Root = ""

// Run executes host commands; tests replace it.
var Run = func(ctx context.Context, name string, args ...string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = os.Stderr
	err := cmd.Run()
	return out.Bytes(), err
}

func path(p string) string { return filepath.Join(Root, p) }

// Grant is what the control plane hands an authenticated node.
type Grant struct {
	Runtime      string   `json:"runtime"`
	Endpoint     string   `json:"endpoint,omitempty"`
	Token        string   `json:"token,omitempty"`
	CACertHashes []string `json:"caCertHashes,omitempty"`
	K0sToken     string   `json:"k0sToken,omitempty"`
	// TTLSeconds rather than an expiry time: a fresh node's clock may not
	// be synchronised yet.
	TTLSeconds int `json:"ttlSeconds"`
}

// Validate rejects a grant a node must not act on: unknown runtime,
// malformed fields (they end up in YAML and command lines), or a lifetime
// outside (0, TokenTTL].
func (g Grant) Validate() error {
	if g.TTLSeconds <= 0 || time.Duration(g.TTLSeconds)*time.Second > TokenTTL {
		return fmt.Errorf("grant lifetime %ds is outside (0, %s]", g.TTLSeconds, TokenTTL)
	}
	switch g.Runtime {
	case RuntimeKubeadm:
		if !endpointRE.MatchString(g.Endpoint) || !tokenRE.MatchString(g.Token) || len(g.CACertHashes) == 0 {
			return errors.New("kubeadm grant is incomplete or malformed")
		}
		for _, h := range g.CACertHashes {
			if !caHashRE.MatchString(h) {
				return errors.New("kubeadm grant has a malformed CA hash")
			}
		}
	case RuntimeK0s:
		if len(g.K0sToken) > 16384 || !k0sTokenRE.MatchString(g.K0sToken) {
			return errors.New("k0s grant has a malformed token")
		}
	default:
		return fmt.Errorf("unknown runtime %q", g.Runtime)
	}
	return nil
}

// ValidHostname reports whether s is usable as a node name and mDNS label.
func ValidHostname(s string) bool { return hostnameRE.MatchString(s) }

// HostnameHelper is the base OS's naming helper (bluefin-hostname.service
// runs it on first boot): a node without a static hostname becomes
// bluefin-<first 8 of machine-id>.
const HostnameHelper = "/usr/libexec/bluefin-hostname"

// EnsureHostname names a node still called localhost with the base OS's
// helper, before kubeadm init or join registers it. The OS already does
// this on first boot; this covers a node installed before it did.
func EnsureHostname(ctx context.Context) (string, error) {
	current, err := os.Hostname()
	if err != nil {
		return "", err
	}
	short, _, _ := strings.Cut(strings.ToLower(current), ".")
	if short != "" && short != "localhost" {
		return current, nil
	}
	if _, err := Run(ctx, HostnameHelper); err != nil {
		return "", fmt.Errorf("%s: %w", HostnameHelper, err)
	}
	return os.Hostname()
}

// ShortHostname is the first label of the hostname, which is also the
// name resolved announces as <name>.local.
func ShortHostname() (string, error) {
	h, err := os.Hostname()
	if err != nil {
		return "", err
	}
	short, _, _ := strings.Cut(strings.ToLower(h), ".")
	if !ValidHostname(short) {
		return "", fmt.Errorf("hostname %q is not a valid node name", h)
	}
	return short, nil
}

// PatchInitConfig makes a seeded single-node init config multi-node: the
// ClusterConfiguration gets controlPlaneEndpoint <host>.local:6443, so
// nodes reach the API by mDNS name, and certSANs for that name, the
// hostname and addrs. A config that already sets controlPlaneEndpoint is
// left alone (idempotent, and the operator's choice wins).
func PatchInitConfig(host string, addrs []string) (bool, error) {
	file := path(KubeadmInitConfig)
	data, err := os.ReadFile(file)
	if err != nil {
		return false, err
	}
	docs := strings.Split(string(data), "\n---\n")
	idx := -1
	for i, d := range docs {
		if topLevel(d, "kind") == "ClusterConfiguration" {
			idx = i
		}
	}
	if idx < 0 {
		return false, errors.New("init config has no ClusterConfiguration")
	}
	doc := docs[idx]
	if topLevel(doc, "controlPlaneEndpoint") != "" {
		return false, nil
	}
	if hasKey(doc, "apiServer") {
		return false, errors.New("init config already has an apiServer section; set controlPlaneEndpoint and apiServer.certSANs in it yourself")
	}
	var b strings.Builder
	b.WriteString(strings.TrimRight(doc, "\n"))
	b.WriteString("\n# bluefin-cluster (HOMELAB_ROLE=control-plane): nodes reach the API\n# server by its mDNS name.\n")
	fmt.Fprintf(&b, "controlPlaneEndpoint: %s.local:6443\napiServer:\n  certSANs:\n  - %s.local\n  - %s\n", host, host, host)
	for _, a := range addrs {
		fmt.Fprintf(&b, "  - %q\n", a)
	}
	docs[idx] = b.String()
	out := strings.Join(docs, "\n---\n")
	if !strings.HasSuffix(out, "\n") {
		out += "\n"
	}
	return true, writeFileAtomic(file, []byte(out), 0o644)
}

func topLevel(doc, key string) string {
	for _, line := range strings.Split(doc, "\n") {
		if v, ok := strings.CutPrefix(line, key+":"); ok {
			return strings.TrimSpace(v)
		}
	}
	return ""
}

func hasKey(doc, key string) bool {
	for _, line := range strings.Split(doc, "\n") {
		if strings.HasPrefix(line, key+":") {
			return true
		}
	}
	return false
}

// GlobalAddrs lists the host's global unicast addresses (certSANs).
func GlobalAddrs() []string {
	ifaces, err := net.Interfaces()
	if err != nil {
		return nil
	}
	var out []string
	for _, ifc := range ifaces {
		if ifc.Flags&net.FlagUp == 0 || ifc.Flags&net.FlagLoopback != 0 {
			continue
		}
		addrs, _ := ifc.Addrs()
		for _, a := range addrs {
			ipn, ok := a.(*net.IPNet)
			if ok && ipn.IP.IsGlobalUnicast() {
				out = append(out, ipn.IP.String())
			}
		}
	}
	return out
}

// LocalRuntime is the control-plane runtime whose admin kubeconfig exists.
func LocalRuntime() string {
	if _, err := os.Stat(path(KubeadmAdminConf)); err == nil {
		return RuntimeKubeadm
	}
	if _, err := os.Stat(path(K0sAdminConf)); err == nil {
		return RuntimeK0s
	}
	return ""
}

// NodeRuntime is the runtime a node can join with: the kubeadm sysext if
// merged, else k0s (the sysext image k0s-first-boot.service activates).
func NodeRuntime() string {
	if _, err := os.Stat(path("/usr/bin/kubeadm")); err == nil {
		return RuntimeKubeadm
	}
	for _, p := range []string{"/usr/bin/k0s", "/var/lib/k0s/k0s.raw"} {
		if _, err := os.Stat(path(p)); err == nil {
			return RuntimeK0s
		}
	}
	return ""
}

// Minter creates join credentials on the control plane.
type Minter interface {
	Mint(ctx context.Context, node string) (Grant, error)
}

// HostMinter mints with the control plane's own tools: `kubeadm token
// create` / `k0s token create`, both with TokenTTL.
type HostMinter struct{}

func (HostMinter) Mint(ctx context.Context, node string) (Grant, error) {
	ctx, cancel := context.WithTimeout(ctx, time.Minute)
	defer cancel()
	ttl := int(TokenTTL / time.Second)
	switch LocalRuntime() {
	case RuntimeKubeadm:
		return mintKubeadm(ctx, node, ttl)
	case RuntimeK0s:
		out, err := Run(ctx, "k0s", "token", "create", "--role=worker", "--expiry="+TokenTTL.String())
		if err != nil {
			return Grant{}, fmt.Errorf("k0s token create: %w", err)
		}
		return Grant{Runtime: RuntimeK0s, K0sToken: strings.TrimSpace(string(out)), TTLSeconds: ttl}, nil
	}
	return Grant{}, errors.New("no control plane on this host yet")
}

func mintKubeadm(ctx context.Context, node string, ttl int) (Grant, error) {
	endpoint, err := kubeconfigServer(path(KubeadmAdminConf))
	if err != nil {
		return Grant{}, err
	}
	caHash, err := CACertHash(path(KubeadmCACert))
	if err != nil {
		return Grant{}, err
	}
	out, err := Run(ctx, "kubeadm", "token", "create",
		"--kubeconfig", path(KubeadmAdminConf),
		"--ttl", TokenTTL.String(),
		"--description", "bluefin-cluster join: "+node)
	if err != nil {
		return Grant{}, fmt.Errorf("kubeadm token create: %w", err)
	}
	lines := strings.Fields(string(out))
	if len(lines) == 0 {
		return Grant{}, errors.New("kubeadm token create printed nothing")
	}
	return Grant{
		Runtime:      RuntimeKubeadm,
		Endpoint:     endpoint,
		Token:        lines[len(lines)-1],
		CACertHashes: []string{"sha256:" + caHash},
		TTLSeconds:   ttl,
	}, nil
}

var serverRE = regexp.MustCompile(`(?m)^\s*server:\s*https://([^\s/]+)`)

func kubeconfigServer(file string) (string, error) {
	data, err := os.ReadFile(file)
	if err != nil {
		return "", err
	}
	m := serverRE.FindSubmatch(data)
	if m == nil {
		return "", fmt.Errorf("%s has no https server", file)
	}
	return string(m[1]), nil
}

// CACertHash is kubeadm's --discovery-token-ca-cert-hash: the hex SHA-256
// of the CA certificate's SubjectPublicKeyInfo.
func CACertHash(file string) (string, error) {
	data, err := os.ReadFile(file)
	if err != nil {
		return "", err
	}
	block, _ := pem.Decode(data)
	if block == nil || block.Type != "CERTIFICATE" {
		return "", fmt.Errorf("%s: no PEM certificate", file)
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(cert.RawSubjectPublicKeyInfo)
	return hex.EncodeToString(sum[:]), nil
}

// JoinConfiguration renders the kubeadm config for a validated grant.
func JoinConfiguration(g Grant) string {
	var b strings.Builder
	b.WriteString("apiVersion: kubeadm.k8s.io/v1beta4\nkind: JoinConfiguration\ndiscovery:\n  bootstrapToken:\n")
	fmt.Fprintf(&b, "    apiServerEndpoint: %q\n    token: %q\n    caCertHashes:\n", g.Endpoint, g.Token)
	for _, h := range g.CACertHashes {
		fmt.Fprintf(&b, "    - %q\n", h)
	}
	fmt.Fprintf(&b, "nodeRegistration:\n  criSocket: %s\n", CRISocket)
	return b.String()
}

// Join acts on a validated grant: kubeadm join with token discovery
// pinned to the CA hash, or the k0s worker token for k0s-first-boot.
func Join(ctx context.Context, g Grant) error {
	switch g.Runtime {
	case RuntimeKubeadm:
		return joinKubeadm(ctx, g)
	case RuntimeK0s:
		if err := os.MkdirAll(path("/etc/k0s"), 0o755); err != nil {
			return err
		}
		if err := writeFileAtomic(path(K0sTokenFile), []byte(g.K0sToken+"\n"), 0o600); err != nil {
			return err
		}
		if _, err := Run(ctx, "systemctl", "enable", "--now", "k0s-first-boot.service"); err != nil {
			return fmt.Errorf("starting k0s-first-boot.service: %w", err)
		}
		return nil
	}
	return fmt.Errorf("unknown runtime %q", g.Runtime)
}

func joinKubeadm(ctx context.Context, g Grant) error {
	if _, err := Run(ctx, "systemctl", "enable", "--now", "containerd.service"); err != nil {
		return fmt.Errorf("starting containerd: %w", err)
	}
	if _, err := Run(ctx, "systemctl", "enable", "kubelet.service"); err != nil {
		return fmt.Errorf("enabling kubelet: %w", err)
	}
	dir := path("/run/bluefin-cluster")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	cfg := filepath.Join(dir, "join.yaml")
	if err := writeFileAtomic(cfg, []byte(JoinConfiguration(g)), 0o600); err != nil {
		return err
	}
	defer os.Remove(cfg)
	if _, err := Run(ctx, "kubeadm", "join", "--config", cfg); err != nil {
		_, _ = Run(ctx, "kubeadm", "reset", "--force", "--cri-socket", CRISocket)
		return fmt.Errorf("kubeadm join: %w", err)
	}
	return nil
}

func writeFileAtomic(file string, data []byte, mode os.FileMode) error {
	tmp, err := os.CreateTemp(filepath.Dir(file), "."+filepath.Base(file)+".")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if err := tmp.Chmod(mode); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), file)
}

// WriteFile is writeFileAtomic for the command layer.
func WriteFile(file string, data []byte, mode os.FileMode) error {
	return writeFileAtomic(path(file), data, mode)
}

const (
	hostsFile  = "/etc/hosts"
	hostsBegin = "# bluefin-cluster begin: control plane mDNS name for statically linked programs"
	hostsEnd   = "# bluefin-cluster end"
)

// PinHost keeps one "<addr> <name>" line in a marked block of /etc/hosts
// (created if absent; a symlink is replaced by a copy of its content).
func PinHost(name string, addr netip.Addr) (bool, error) {
	file := path(hostsFile)
	data, err := os.ReadFile(file)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return false, err
	}
	var kept []string
	inBlock := false
	for _, line := range strings.Split(strings.TrimRight(string(data), "\n"), "\n") {
		switch {
		case line == hostsBegin:
			inBlock = true
		case line == hostsEnd:
			inBlock = false
		case !inBlock && (line != "" || len(kept) > 0):
			kept = append(kept, line)
		}
	}
	block := []string{hostsBegin, addr.String() + " " + name, hostsEnd}
	out := strings.Join(append(kept, block...), "\n") + "\n"
	if out == string(data) {
		return false, nil
	}
	return true, writeFileAtomic(file, []byte(out), 0o644)
}

// APIServerHost is the host of the API server the node's kubelet talks to.
func APIServerHost() (string, error) {
	hp, err := kubeconfigServer(path(KubeadmKubelet))
	if err != nil {
		return "", err
	}
	host, _, err := net.SplitHostPort(hp)
	return host, err
}
