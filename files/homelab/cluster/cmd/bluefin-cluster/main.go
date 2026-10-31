// Command bluefin-cluster forms a multi-node homelab: on the control plane
// it prepares kubeadm's init config and serves join tokens to nodes that
// know the join passphrase; on a node it discovers the control plane over
// mDNS and joins it. Protocol and threat model: README.md in this module.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/netip"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/projectbluefin/server/files/homelab/cluster/internal/conf"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/discover"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/join"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/ops"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/passphrase"
)

const (
	stateDir      = "/var/lib/bluefin-cluster"
	passFile      = stateDir + "/passphrase"
	joinedMarker  = stateDir + "/joined"
	failureLog    = stateDir + "/failures.json"
	issueFile     = "/run/issue.d/50-bluefin-cluster.issue"
	dnssdFile     = "/run/systemd/dnssd/bluefin-cluster.dnssd"
	passKey       = "HOMELAB_JOIN_PASSPHRASE"
	credentialKey = "bluefin-cluster.passphrase"
)

var log = slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{
	ReplaceAttr: func(_ []string, a slog.Attr) slog.Attr {
		if a.Key == slog.TimeKey {
			return slog.Attr{}
		}
		return a
	},
}))

func usage() {
	fmt.Fprintln(os.Stderr, `usage: bluefin-cluster <command>
  prepare     control plane: unique hostname, mDNS API endpoint in kubeadm's init config
  serve       control plane: publish the join service over mDNS and serve join tokens
  join        node: find the control plane, get a join token, join (once)
  hosts       pin the control plane's mDNS name in /etc/hosts (for statically linked programs)
  passphrase  control plane: print the join passphrase`)
	os.Exit(2)
}

func main() {
	if len(os.Args) != 2 {
		usage()
	}
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()
	var err error
	switch os.Args[1] {
	case "prepare":
		err = prepare(ctx)
	case "serve":
		err = serve(ctx)
	case "join":
		err = runJoin(ctx)
	case "hosts":
		err = pinHosts(ctx)
	case "passphrase":
		err = printPassphrase()
	default:
		usage()
	}
	if err != nil {
		log.Error(err.Error())
		os.Exit(1)
	}
}

func loadConf() (conf.Config, error) {
	c, err := conf.Load(conf.DefaultPath)
	if errors.Is(err, os.ErrNotExist) {
		return conf.Config{}, nil
	}
	return c, err
}

func prepare(ctx context.Context) error {
	c, err := loadConf()
	if err != nil {
		return err
	}
	if c.Role() != conf.RoleControlPlane {
		log.Info("not a homelab control plane (HOMELAB_ROLE); nothing to prepare")
		return nil
	}
	if _, err := ops.EnsureHostname(ctx); err != nil {
		return err
	}
	host, err := ops.ShortHostname()
	if err != nil {
		return err
	}
	if err := pin(ctx, host+".local"); err != nil {
		return err
	}
	if _, err := os.Stat(ops.KubeadmInitConfig); err != nil {
		return nil
	}
	changed, err := ops.PatchInitConfig(host, ops.GlobalAddrs())
	if err != nil {
		return err
	}
	if changed {
		log.Info("kubeadm init config: control plane endpoint " + host + ".local:6443")
	}
	return nil
}

// pin resolves name through resolved (mDNS) and pins it in /etc/hosts:
// kubelet, kubectl and kubeadm are statically linked Go programs whose
// resolver skips nss-resolve and would send <name>.local to unicast DNS.
func pin(ctx context.Context, name string) error {
	if !strings.HasSuffix(name, ".local") {
		return nil
	}
	var addr netip.Addr
	var err error
	for i := 0; i < 30; i++ {
		rctx, cancel := context.WithTimeout(ctx, 5*time.Second)
		addr, err = discover.ResolveHost(rctx, discover.ResolveSocket, name)
		cancel()
		if err == nil {
			break
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(2 * time.Second):
		}
	}
	if err != nil {
		return fmt.Errorf("resolving %s over mDNS: %w", name, err)
	}
	changed, err := ops.PinHost(name, addr)
	if changed {
		log.Info("pinned " + name + " to " + addr.String() + " in /etc/hosts")
	}
	return err
}

// pinHosts refreshes the pin (bluefin-cluster-hosts.timer), so a control
// plane whose DHCP address changed stays reachable.
func pinHosts(ctx context.Context) error {
	c, err := loadConf()
	if err != nil {
		return err
	}
	switch c.Role() {
	case conf.RoleControlPlane:
		host, err := ops.ShortHostname()
		if err != nil {
			return err
		}
		return pin(ctx, host+".local")
	case conf.RoleNode:
		host, err := ops.APIServerHost()
		if err != nil {
			return nil
		}
		return pin(ctx, host)
	}
	return nil
}

// controlPlanePassphrase is HOMELAB_JOIN_PASSPHRASE if set (strength
// checked), else the one generated on first start.
func controlPlanePassphrase(c conf.Config) (string, error) {
	if v := c[passKey]; v != "" {
		p, err := passphrase.Normalize(v)
		if err != nil {
			return "", fmt.Errorf("%s: %w", passKey, err)
		}
		if err := passphrase.CheckStrength(p); err != nil {
			return "", fmt.Errorf("%s: %w", passKey, err)
		}
		log.Warn("using the operator-chosen join passphrase from " + passKey + "; a generated one is stronger")
		return p, ops.WriteFile(passFile, []byte(p+"\n"), 0o600)
	}
	if data, err := os.ReadFile(passFile); err == nil {
		return passphrase.Normalize(string(data))
	}
	p, bits, err := passphrase.Generate(passphrase.DefaultWords)
	if err != nil {
		return "", err
	}
	if err := ops.WriteFile(passFile, []byte(p+"\n"), 0o600); err != nil {
		return "", err
	}
	log.Info(fmt.Sprintf("generated a %d-word join passphrase (%.1f bits); show it with `bluefin-cluster passphrase`", passphrase.DefaultWords, bits))
	return p, nil
}

func serve(ctx context.Context) error {
	c, err := loadConf()
	if err != nil {
		return err
	}
	if c.Role() != conf.RoleControlPlane {
		log.Info("not a homelab control plane (HOMELAB_ROLE); not serving joins")
		return nil
	}
	if err := os.MkdirAll(stateDir, 0o700); err != nil {
		return err
	}
	pass, err := controlPlanePassphrase(c)
	if err != nil {
		return err
	}
	cert, err := join.LoadOrCreateCert(stateDir)
	if err != nil {
		return err
	}
	if err := writeIssue(pass); err != nil {
		log.Warn("could not show the passphrase on the console: " + err.Error())
	}

	runtime := ""
	for runtime == "" {
		if runtime = ops.LocalRuntime(); runtime != "" {
			break
		}
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(10 * time.Second):
		}
	}
	host, err := ops.ShortHostname()
	if err != nil {
		return err
	}
	cluster := c.Get("HOMELAB_CLUSTER_NAME", host)
	if !ops.ValidHostname(cluster) {
		return fmt.Errorf("HOMELAB_CLUSTER_NAME=%q: use lower-case letters, digits and '-'", cluster)
	}
	port := c.Get("HOMELAB_JOIN_PORT", fmt.Sprint(discover.DefaultPort))
	ln, err := net.Listen("tcp", ":"+port)
	if err != nil {
		return err
	}
	if err := publish(cluster, runtime, port); err != nil {
		ln.Close()
		return err
	}
	log.Info("serving joins", "port", port, "runtime", runtime, "cluster", cluster)
	srv := &join.Server{
		Passphrase: pass,
		Cluster:    cluster,
		Cert:       cert,
		Runtime:    ops.LocalRuntime,
		Minter:     ops.HostMinter{},
		Limiter:    join.NewLimiter(join.DefaultServerLimits, failureLog, nil),
		Log:        log,
	}
	err = srv.Serve(ctx, ln)
	_ = os.Remove(dnssdFile)
	return err
}

// publish advertises the join service; the TXT record carries no secrets.
func publish(cluster, runtime, port string) error {
	body := fmt.Sprintf("# bluefin-cluster serve: the homelab join service (no secrets here).\n[Service]\nName=%%H\nType=%s\nPort=%s\nTxtText=v=1 cluster=%s runtime=%s\n",
		discover.ServiceType, port, cluster, runtime)
	// Explicit modes: the unit's UMask=0077 would hide both from
	// systemd-resolved, which runs as its own user.
	dir := filepath.Dir(dnssdFile)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	if err := os.Chmod(dir, 0o755); err != nil {
		return err
	}
	if err := os.WriteFile(dnssdFile, []byte(body), 0o644); err != nil {
		return err
	}
	if err := os.Chmod(dnssdFile, 0o644); err != nil {
		return err
	}
	return exec.Command("systemctl", "reload", "systemd-resolved.service").Run()
}

func writeIssue(pass string) error {
	if err := os.MkdirAll(filepath.Dir(issueFile), 0o755); err != nil {
		return err
	}
	text := fmt.Sprintf("Homelab join passphrase: %s\nSet HOMELAB_JOIN_PASSPHRASE to it on each node (bluefin-cluster passphrase).\n\n", pass)
	return os.WriteFile(issueFile, []byte(text), 0o600)
}

func printPassphrase() error {
	data, err := os.ReadFile(passFile)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return errors.New("no join passphrase yet: this is not a homelab control plane, or bluefin-cluster-serve.service has not started")
		}
		return err
	}
	fmt.Print(string(data))
	return nil
}

func nodePassphrase(c conf.Config) (string, error) {
	raw := c[passKey]
	if dir := os.Getenv("CREDENTIALS_DIRECTORY"); raw == "" && dir != "" {
		if data, err := os.ReadFile(filepath.Join(dir, credentialKey)); err == nil {
			raw = string(data)
		}
	}
	if raw == "" {
		return "", fmt.Errorf("no join passphrase: set %s in %s (or the %s credential)", passKey, conf.DefaultPath, credentialKey)
	}
	return passphrase.Normalize(raw)
}

// joined is true once this node is in a cluster: the marker, or the kubelet
// kubeconfig kubeadm join or the k0s worker writes after bootstrapping. A
// k0s join token alone is no evidence: Join writes it before it starts
// k0s-first-boot.service, so a failed start, or a token that expired before
// k0sworker used it, would otherwise pass for a join and stop retrying.
func joined() bool {
	for _, p := range []string{joinedMarker, ops.KubeadmKubelet, ops.K0sKubelet} {
		if _, err := os.Stat(filepath.Join(ops.Root, p)); err == nil {
			return true
		}
	}
	return false
}

func runJoin(ctx context.Context) error {
	c, err := loadConf()
	if err != nil {
		return err
	}
	if c.Role() != conf.RoleNode {
		log.Info("not a homelab node (HOMELAB_ROLE); nothing to join")
		return nil
	}
	if joined() {
		log.Info("already joined")
		return ops.WriteFile(joinedMarker, nil, 0o644)
	}
	pass, err := nodePassphrase(c)
	if err != nil {
		return err
	}
	if _, err := ops.EnsureHostname(ctx); err != nil {
		return err
	}
	node, err := ops.ShortHostname()
	if err != nil {
		return err
	}
	runtime := ops.NodeRuntime()
	if runtime == "" {
		return errors.New("neither the kubeadm sysext nor k0s is on this node")
	}
	cl := &join.Client{
		Passphrase: pass,
		Node:       node,
		Runtime:    runtime,
		Budget:     join.NewClientBudget(join.DefaultServerLimits.Global, join.DefaultServerLimits.GlobalWindow, nil),
	}
	manual := c["HOMELAB_CONTROL_PLANE"]
	backoff := 5 * time.Second
	for {
		p, err := attempt(ctx, cl, manual)
		if err == nil {
			log.Info("got a join token", "cluster", p.Cluster, "runtime", p.Grant.Runtime, "endpoint", p.Grant.Endpoint)
			if host, _, herr := net.SplitHostPort(p.Grant.Endpoint); herr == nil && p.Grant.Runtime == ops.RuntimeKubeadm {
				if err := pin(ctx, host); err != nil {
					log.Warn("could not pin the control plane address", "error", err)
				}
			}
			if err := ops.Join(ctx, p.Grant); err != nil {
				log.Error("joining failed; retrying with a fresh token", "error", err)
			} else {
				if err := ops.WriteFile(joinedMarker, []byte(p.Cluster+"\n"), 0o644); err != nil {
					return err
				}
				if err := conf.RemoveKey(conf.DefaultPath, passKey); err != nil {
					log.Warn("could not remove " + passKey + " from " + conf.DefaultPath + ": " + err.Error())
				}
				log.Info("joined cluster " + p.Cluster)
				return nil
			}
		} else {
			log.Warn("join attempt failed", "error", err)
		}
		wait := backoff
		var be *join.ErrBudget
		var se *join.ServerError
		switch {
		case errors.As(err, &be):
			wait = be.RetryAfter
		case errors.As(err, &se) && se.RetryAfter > 0:
			wait = max(wait, time.Duration(se.RetryAfter)*time.Second)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(wait):
		}
		backoff = min(backoff*2, 5*time.Minute)
	}
}

func attempt(ctx context.Context, cl *join.Client, manual string) (join.Payload, error) {
	var cands []discover.Candidate
	if manual != "" {
		cand, err := discover.Manual(ctx, manual)
		if err != nil {
			return join.Payload{}, err
		}
		cands = []discover.Candidate{cand}
	} else {
		found, err := discover.MDNS(ctx, discover.ResolveSocket, discover.Links(), 10*time.Second)
		if err != nil {
			return join.Payload{}, fmt.Errorf("mDNS browse: %w", err)
		}
		for _, cand := range found {
			if rt := cand.TXT["runtime"]; rt == "" || rt == cl.Runtime {
				cands = append(cands, cand)
			}
		}
		if len(cands) == 0 {
			return join.Payload{}, fmt.Errorf("no %s control plane advertised %s on the local network yet", cl.Runtime, discover.ServiceType)
		}
	}
	return tryCandidates(ctx, cl.Join, cands)
}

// tryCandidates asks each candidate in turn. One that cannot prove the
// passphrase (an impostor, or another cluster's control plane) is skipped
// rather than ending the round: its other addresses would only spend guesses
// on the same answer, and stopping would let whichever instance is listed
// first hide the real control plane for good. Only the guess budget, shared
// by every candidate, ends the round early.
func tryCandidates(ctx context.Context, joinAt func(context.Context, netip.AddrPort) (join.Payload, error), cands []discover.Candidate) (join.Payload, error) {
	var errs []error
	for _, cand := range cands {
		for _, addr := range cand.Addrs {
			p, err := joinAt(ctx, addr)
			if err == nil {
				return p, nil
			}
			errs = append(errs, fmt.Errorf("%s (%s): %w", cand.Name, addr, err))
			var be *join.ErrBudget
			if errors.As(err, &be) {
				return join.Payload{}, errors.Join(errs...)
			}
			if errors.Is(err, join.ErrNotProven) {
				break
			}
		}
	}
	return join.Payload{}, errors.Join(errs...)
}
