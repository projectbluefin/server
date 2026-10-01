package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

var safeVersion = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`)
var hashPattern = regexp.MustCompile(`^[a-f0-9]{64}$`)
var tokenPattern = regexp.MustCompile(`^[a-z0-9]{6}\.[a-z0-9]{16}$`)

type Runtime struct {
	ImageVersion     string `json:"image_version"`
	Kubernetes       string `json:"kubernetes"`
	Containerd       string `json:"containerd"`
	KubernetesFile   string `json:"kubernetes_file"`
	ContainerdFile   string `json:"containerd_file"`
	KubernetesSHA256 string `json:"kubernetes_sha256"`
	ContainerdSHA256 string `json:"containerd_sha256"`
}
type Profile struct {
	Schema                int     `json:"schema"`
	Runtime               Runtime `json:"runtime"`
	PauseImage            string  `json:"pause_image"`
	BaselineCommit        string  `json:"baseline_commit"`
	ConsoleImage          string  `json:"console_image"`
	HealthImage           string  `json:"health_image"`
	WorkflowExecutorImage string  `json:"workflow_executor_image"`
}

func (p Profile) validate() error {
	if p.Schema != 1 || !safeVersion.MatchString(p.Runtime.ImageVersion) || len(p.BaselineCommit) != 40 {
		return errors.New("invalid_packaged_profile")
	}
	for _, c := range p.BaselineCommit {
		if !strings.ContainsRune("0123456789abcdef", c) {
			return errors.New("invalid_baseline_commit")
		}
	}
	for _, ref := range []string{p.ConsoleImage, p.WorkflowExecutorImage, p.HealthImage, p.PauseImage} {
		parts := strings.Split(ref, "@sha256:")
		if len(parts) != 2 || parts[0] == "" || strings.ContainsAny(parts[0], " \t\n") || !hashPattern.MatchString(parts[1]) {
			return errors.New("invalid_stock_image_reference")
		}
	}
	return nil
}

type Transaction struct {
	Target    Runtime   `json:"target"`
	Stage     string    `json:"stage"`
	Snapshot  string    `json:"snapshot,omitempty"`
	StartedAt time.Time `json:"started_at"`
}
type State struct {
	Schema             int          `json:"schema"`
	Profile            string       `json:"profile"`
	Role               string       `json:"role"`
	Phase              string       `json:"phase"`
	Revision           uint64       `json:"revision"`
	ClusterID          string       `json:"cluster_id,omitempty"`
	ClusterCAHash      string       `json:"cluster_ca_hash,omitempty"`
	Active             Runtime      `json:"runtime"`
	Prior              *Runtime     `json:"prior_runtime,omitempty"`
	Upgrade            *Transaction `json:"upgrade,omitempty"`
	BaselineCommit     string       `json:"baseline_commit,omitempty"`
	Handoff            bool         `json:"handoff"`
	Error              string       `json:"error,omitempty"`
	PendingWorkers     *Runtime     `json:"pending_worker_upgrade,omitempty"`
	WorkerUpgradeError string       `json:"worker_upgrade_error,omitempty"`
	ConsoleStatus      string       `json:"console_status,omitempty"`
}

func (s State) status() any {
	stage, image, pending := "", "", ""
	if s.Upgrade != nil {
		stage = s.Upgrade.Stage
		image = s.Upgrade.Target.ImageVersion
	}
	if s.PendingWorkers != nil {
		pending = s.PendingWorkers.ImageVersion
	}
	return struct {
		Schema                           int     `json:"schema"`
		Profile                          string  `json:"profile"`
		Role                             string  `json:"role"`
		Phase                            string  `json:"phase"`
		Ready                            bool    `json:"ready"`
		Revision                         uint64  `json:"revision"`
		ClusterID                        string  `json:"cluster_id,omitempty"`
		Runtime                          Runtime `json:"runtime"`
		Error                            string  `json:"error,omitempty"`
		UpgradeStage                     string  `json:"upgrade_stage,omitempty"`
		UpgradeImageVersion              string  `json:"upgrade_image_version,omitempty"`
		PendingWorkerUpgradeImageVersion string  `json:"pending_worker_upgrade_image_version,omitempty"`
		WorkerUpgradeError               string  `json:"worker_upgrade_error,omitempty"`
		ConsoleStatus                    string  `json:"console_status,omitempty"`
	}{s.Schema, s.Profile, s.Role, s.Phase, s.Phase == "ready", s.Revision, s.ClusterID, s.Active, s.Error, stage, image, pending, s.WorkerUpgradeError, s.ConsoleStatus}
}
func (s State) upgradeAction(image string) string {
	if s.Profile != "complete" || (s.Role != "controller" && s.Role != "worker") {
		return ""
	}
	if s.Phase == "ready" && s.Upgrade == nil {
		return "start"
	}
	if s.Phase != "failed" || s.Upgrade == nil {
		return ""
	}
	switch s.Upgrade.Stage {
	case "verify_payloads", "staged":
		return "replace"
	case "snapshot", "control_plane", "runtime_switch", "runtime", "healthy":
		if s.Upgrade.Target.ImageVersion == image {
			return "resume"
		}
	}
	return ""
}
func (s State) initializeAction() string {
	if s.Profile != "complete" || s.Upgrade != nil {
		return ""
	}
	if s.Role == "unassigned" {
		return "start"
	}
	if s.Role == "controller" && s.Phase == "failed" {
		return "resume"
	}
	return ""
}
func (s State) joinAction(clusterID string, hasKubeletIdentity bool) string {
	if s.Profile != "complete" || s.Upgrade != nil {
		return ""
	}
	if s.Role == "unassigned" {
		return "start"
	}
	if s.Role == "worker" && s.Phase == "failed" && s.ClusterID != "" && s.ClusterID == clusterID && !hasKubeletIdentity {
		return "renew"
	}
	return ""
}
func (s *State) commitRole(role string, revision uint64) error {
	if s.Profile != "complete" {
		return errors.New("profile_inert")
	}
	if revision != s.Revision {
		return errors.New("stale_revision")
	}
	if role != "controller" && role != "worker" {
		return errors.New("invalid_role")
	}
	if s.Role != "unassigned" {
		return errors.New("role_already_committed")
	}
	s.Role = role
	s.Phase = "pending"
	s.Revision++
	return nil
}

type Join struct {
	APIEndpoint string    `json:"api_endpoint"`
	Token       string    `json:"token"`
	CAHash      string    `json:"ca_hash"`
	ExpiresAt   time.Time `json:"expires_at"`
	ClusterID   string    `json:"cluster_id"`
}

func privateIP(ip net.IP) bool {
	return ip != nil && (ip.IsPrivate() || ip.IsLinkLocalUnicast()) && !ip.IsUnspecified()
}
func (j Join) validate(now time.Time) error {
	host, port, err := net.SplitHostPort(j.APIEndpoint)
	if err != nil || port != "6443" || !privateIP(net.ParseIP(host)) {
		return errors.New("invalid_api_endpoint")
	}
	if !tokenPattern.MatchString(j.Token) || !strings.HasPrefix(j.CAHash, "sha256:") || !hashPattern.MatchString(strings.TrimPrefix(j.CAHash, "sha256:")) {
		return errors.New("invalid_join_credentials")
	}
	if !j.ExpiresAt.After(now) || j.ExpiresAt.After(now.Add(15*time.Minute)) {
		return errors.New("join_expired_or_excessive")
	}
	if !safeVersion.MatchString(j.ClusterID) {
		return errors.New("invalid_cluster_identity")
	}
	return nil
}

type RevisionRequest struct {
	ExpectedRevision uint64 `json:"expected_revision"`
}

func decodeJSON(r io.Reader, v any) error {
	d := json.NewDecoder(io.LimitReader(r, 65537))
	d.DisallowUnknownFields()
	if err := d.Decode(v); err != nil {
		return err
	}
	var extra any
	if err := d.Decode(&extra); err != io.EOF {
		return errors.New("trailing_input")
	}
	return nil
}
func loadJSON(path string, v any) error {
	f, e := os.Open(path)
	if e != nil {
		return e
	}
	defer f.Close()
	return decodeJSON(f, v)
}
func saveJSON(path string, v any) error {
	b, e := json.Marshal(v)
	if e != nil {
		return e
	}
	b = append(b, '\n')
	if e = os.MkdirAll(filepath.Dir(path), 0700); e != nil {
		return e
	}
	f, e := os.CreateTemp(filepath.Dir(path), ".state-")
	if e != nil {
		return e
	}
	name := f.Name()
	defer os.Remove(name)
	if e = f.Chmod(0600); e == nil {
		_, e = f.Write(b)
	}
	if e == nil {
		e = f.Sync()
	}
	closeErr := f.Close()
	if e != nil {
		return e
	}
	if closeErr != nil {
		return closeErr
	}
	if e = os.Rename(name, path); e != nil {
		return e
	}
	dir, e := os.Open(filepath.Dir(path))
	if e != nil {
		return e
	}
	defer dir.Close()
	return dir.Sync()
}
func version(v string) ([3]int, error) {
	var out [3]int
	parts := strings.Split(strings.TrimPrefix(v, "v"), ".")
	if len(parts) != 3 {
		return out, errors.New("invalid_version")
	}
	for i, p := range parts {
		n, e := strconv.Atoi(p)
		if e != nil || n < 0 {
			return out, errors.New("invalid_version")
		}
		out[i] = n
	}
	return out, nil
}
func checkSkew(current, next string) error {
	a, e := version(current)
	if e != nil {
		return e
	}
	b, e := version(next)
	if e != nil {
		return e
	}
	if a[0] != b[0] || b[1] < a[1] || b[1] > a[1]+1 || (b[1] == a[1] && b[2] < a[2]) {
		return fmt.Errorf("unsupported_kubernetes_skew")
	}
	return nil
}
