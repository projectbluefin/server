package main

import (
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
)

func certificateDiscoveryHash(body []byte) (string, error) {
	cert, err := parseCertificate(body)
	if err != nil {
		return "", err
	}
	spki, err := x509.MarshalPKIXPublicKey(cert.PublicKey)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(spki)
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}
func (e *Engine) hasWorkerIdentity() bool {
	for _, path := range []string{"/etc/kubernetes/kubelet.conf", "/var/lib/kubelet/pki/kubelet-client-current.pem"} {
		if _, err := os.Lstat(e.path(path)); !errors.Is(err, os.ErrNotExist) {
			return true
		}
	}
	return false
}
func (e *Engine) validatePartialJoin(join Join) (bool, error) {
	if e.State.Role != "worker" || e.State.ClusterID == "" || e.State.ClusterID != join.ClusterID {
		return false, errors.New("cluster_identity_changed")
	}
	if e.hasWorkerIdentity() {
		return false, errors.New("worker_identity_already_issued")
	}
	partial := false
	body, err := os.ReadFile(e.path("/etc/kubernetes/pki/ca.crt"))
	if err == nil {
		partial = true
		hash, err := certificateDiscoveryHash(body)
		if err != nil || hash != join.CAHash {
			return false, errors.New("partial_join_ca_mismatch")
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return false, err
	}
	path := e.path("/etc/kubernetes/bootstrap-kubelet.conf")
	if _, err = os.Stat(path); err == nil {
		partial = true
		out, err := command(nil, "kubectl", "--kubeconfig="+path, "config", "view", "--raw", "--minify", "-o", "json")
		if err != nil {
			return false, errors.New("partial_bootstrap_config_invalid")
		}
		var cfg struct {
			Clusters []struct {
				Cluster struct {
					CAData   string `json:"certificate-authority-data"`
					CAPath   string `json:"certificate-authority"`
					Insecure bool   `json:"insecure-skip-tls-verify"`
				} `json:"cluster"`
			} `json:"clusters"`
		}
		if err = json.Unmarshal(out, &cfg); err != nil || len(cfg.Clusters) != 1 {
			return false, errors.New("partial_bootstrap_config_invalid")
		}
		cluster := cfg.Clusters[0].Cluster
		if cluster.Insecure {
			return false, errors.New("partial_bootstrap_insecure")
		}
		ca, err := base64.StdEncoding.DecodeString(cluster.CAData)
		if cluster.CAData == "" {
			if cluster.CAPath != "/etc/kubernetes/pki/ca.crt" {
				return false, errors.New("partial_bootstrap_ca_path_invalid")
			}
			ca, err = os.ReadFile(e.path(cluster.CAPath))
		}
		if err != nil {
			return false, errors.New("partial_bootstrap_ca_invalid")
		}
		hash, err := certificateDiscoveryHash(ca)
		if err != nil || hash != join.CAHash {
			return false, errors.New("partial_bootstrap_ca_mismatch")
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return false, err
	}
	return partial, nil
}
func (e *Engine) executeJoin(join Join, path string) error {
	partial, err := e.validatePartialJoin(join)
	if err != nil {
		return err
	}
	if !partial {
		return run("kubeadm", "join", "--config="+path)
	}
	// kubeadm's discovery validates fresh signed cluster-info + CA pin. These
	// legitimate phases rewrite the bootstrap token/config and wait for TLS
	// issuance; no kubeadm reset, file deletion or ignore-all-preflights exists.
	for _, phase := range []string{"kubelet-start", "kubelet-wait-bootstrap"} {
		if err = run("kubeadm", "join", "phase", phase, "--config="+path); err != nil {
			return err
		}
	}
	return nil
}
