package main

import (
	"encoding/json"
	"errors"
	"net"
	"os"
	"strings"
)

func kubeadmInitConfiguration(address, name, version string) ([]byte, error) {
	documents := []any{
		map[string]any{"apiVersion": "kubeadm.k8s.io/v1beta4", "kind": "InitConfiguration", "localAPIEndpoint": map[string]any{"advertiseAddress": address, "bindPort": 6443}, "nodeRegistration": map[string]any{"name": name, "criSocket": "unix:///run/containerd/containerd.sock", "taints": []any{}}},
		map[string]any{"apiVersion": "kubeadm.k8s.io/v1beta4", "kind": "ClusterConfiguration", "kubernetesVersion": version, "proxy": map[string]bool{"disabled": true}, "apiServer": map[string]any{"extraArgs": []any{map[string]string{"name": "api-audiences", "value": "https://kubernetes.default.svc,https://kubernetes.default.svc.cluster.local"}}}, "networking": map[string]string{"podSubnet": "10.244.0.0/16", "serviceSubnet": "10.96.0.0/12"}},
		map[string]any{"apiVersion": "kubelet.config.k8s.io/v1beta1", "kind": "KubeletConfiguration", "cgroupDriver": "systemd"},
	}
	var encoded []string
	for _, document := range documents {
		body, err := json.Marshal(document)
		if err != nil {
			return nil, err
		}
		encoded = append(encoded, string(body))
	}
	return []byte(strings.Join(encoded, "\n---\n") + "\n"), nil
}

// The cluster's API address is the persisted control-plane advertise address,
// never a fresh interface scan: by the time the platform is reconciled the host
// also carries cilium_host and other virtual addresses, and any of them could
// otherwise be published to the CNI as the API server host.
func apiAdvertiseAddress(path string) (string, error) {
	body, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	for _, document := range strings.Split(string(body), "\n---\n") {
		address, ok := initAdvertiseAddress(document)
		if !ok {
			continue
		}
		ip := net.ParseIP(address)
		if ip == nil || ip.To4() == nil || !ip.IsPrivate() {
			return "", errors.New("invalid_api_advertise_address")
		}
		return ip.String(), nil
	}
	return "", errors.New("init_configuration_missing")
}

func initAdvertiseAddress(document string) (string, bool) {
	var object struct {
		Kind             string `json:"kind"`
		LocalAPIEndpoint struct {
			AdvertiseAddress string `json:"advertiseAddress"`
		} `json:"localAPIEndpoint"`
	}
	if err := json.Unmarshal([]byte(document), &object); err == nil {
		if object.Kind != "InitConfiguration" {
			return "", false
		}
		return object.LocalAPIEndpoint.AdvertiseAddress, true
	}
	// Read only the previously generated v1beta4 YAML shape; this is not a
	// generic YAML endpoint.
	if !strings.HasPrefix(document, "apiVersion: kubeadm.k8s.io/v1beta4\nkind: InitConfiguration\n") {
		return "", false
	}
	for _, line := range strings.Split(document, "\n") {
		field := strings.TrimSpace(line)
		if strings.HasPrefix(field, "advertiseAddress:") {
			return strings.Trim(strings.TrimSpace(strings.TrimPrefix(field, "advertiseAddress:")), `"'`), true
		}
	}
	return "", true
}

func ensureProxyDisabled(path string) error {
	body, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	documents := strings.Split(string(body), "\n---\n")
	for i, document := range documents {
		var object map[string]json.RawMessage
		if err = json.Unmarshal([]byte(document), &object); err == nil {
			var kind string
			if err = json.Unmarshal(object["kind"], &kind); err != nil {
				return errors.New("invalid_init_configuration")
			}
			if kind != "ClusterConfiguration" {
				continue
			}
			object["proxy"] = json.RawMessage(`{"disabled":true}`)
			body, err = json.Marshal(object)
			if err != nil {
				return err
			}
			documents[i] = string(body)
			return writeConfiguration(path, strings.Join(documents, "\n---\n")+"\n", true)
		}
		// Migrate only the previously generated v1beta4 YAML shape, preserving
		// its original addresses/keys. This is not a generic caller YAML endpoint.
		if strings.HasPrefix(document, "apiVersion: kubeadm.k8s.io/v1beta4\nkind: ClusterConfiguration\n") {
			if strings.Contains(document, "\nproxy:\n") {
				if !strings.Contains(document, "\nproxy:\n  disabled: true\n") {
					return errors.New("unsupported_proxy_configuration")
				}
				return nil
			}
			documents[i] = strings.Replace(document, "\napiServer:\n", "\nproxy:\n  disabled: true\napiServer:\n", 1)
			if documents[i] == document {
				return errors.New("unsupported_init_configuration")
			}
			return writeConfiguration(path, strings.Join(documents, "\n---\n"), true)
		}
	}
	return errors.New("cluster_configuration_missing")
}
