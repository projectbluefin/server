package main

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func TestUploadedClusterConfigRemainsProxyDisabledOnPhaseResume(t *testing.T) {
	data, err := kubeadmInitConfiguration("192.168.1.2", "controller", "1.36.5")
	if err != nil {
		t.Fatal(err)
	}
	docs := strings.Split(string(data), "\n---\n")
	var cluster map[string]json.RawMessage
	for _, doc := range docs {
		var obj map[string]json.RawMessage
		if err = json.Unmarshal([]byte(doc), &obj); err != nil {
			t.Fatal(err)
		}
		var kind string
		json.Unmarshal(obj["kind"], &kind)
		if kind == "ClusterConfiguration" {
			cluster = obj
		}
	}
	var proxy struct {
		Disabled bool `json:"disabled"`
	}
	if err = json.Unmarshal(cluster["proxy"], &proxy); err != nil || !proxy.Disabled {
		t.Fatal("uploaded kubeadm config can reinstall kube-proxy", err)
	}
}
func TestInterruptedPersistedProxyEnableCannotReachUploadPhase(t *testing.T) {
	path := t.TempDir() + "/kubeadm-init.yaml"
	unsafe := `{"apiVersion":"kubeadm.k8s.io/v1beta4","kind":"ClusterConfiguration","kubernetesVersion":"1.36.5","proxy":{"disabled":false},"networking":{"serviceSubnet":"10.96.0.0/12"}}`
	if err := os.WriteFile(path, []byte(unsafe), 0600); err != nil {
		t.Fatal(err)
	}
	if err := ensureProxyDisabled(path); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var result struct {
		Proxy struct {
			Disabled bool `json:"disabled"`
		} `json:"proxy"`
		Networking struct {
			ServiceSubnet string `json:"serviceSubnet"`
		} `json:"networking"`
	}
	if err = json.Unmarshal(body, &result); err != nil {
		t.Fatal(err)
	}
	if !result.Proxy.Disabled || result.Networking.ServiceSubnet != "10.96.0.0/12" {
		t.Fatal("phased-init repair reenables proxy or overwrites existing cluster network")
	}
}
