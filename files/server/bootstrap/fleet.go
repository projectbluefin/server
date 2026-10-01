package main

import (
	"encoding/json"
	"errors"
)

type RegisteredNode struct {
	Name           string
	KubeletVersion string
}

func registeredNodes() ([]RegisteredNode, error) {
	out, err := kube("--request-timeout=3s", "get", "nodes", "-o", "json")
	if err != nil {
		return nil, err
	}
	var list struct {
		Items []struct {
			Metadata struct {
				Name string `json:"name"`
			} `json:"metadata"`
			Status struct {
				NodeInfo struct {
					KubeletVersion string `json:"kubeletVersion"`
				} `json:"nodeInfo"`
			} `json:"status"`
		} `json:"items"`
	}
	if err = json.Unmarshal(out, &list); err != nil {
		return nil, err
	}
	nodes := make([]RegisteredNode, 0, len(list.Items))
	for _, item := range list.Items {
		nodes = append(nodes, RegisteredNode{Name: item.Metadata.Name, KubeletVersion: item.Status.NodeInfo.KubeletVersion})
	}
	return nodes, nil
}

func supportedWorkerSkew(controlPlane, worker string) error {
	api, err := version(controlPlane)
	if err != nil {
		return err
	}
	node, err := version(worker)
	if err != nil {
		return err
	}
	if node[0] != api[0] || node[1] > api[1] || node[1] < api[1]-3 {
		return errors.New("unsupported_fleet_worker_skew")
	}
	return nil
}
func (e *Engine) preflightFleet(target Runtime) error {
	nodes, err := registeredNodes()
	if err != nil {
		return err
	}
	for _, node := range nodes {
		if err = supportedWorkerSkew(target.Kubernetes, node.KubeletVersion); err != nil {
			return err
		}
		if err = checkSkew(node.KubeletVersion, target.Kubernetes); err != nil {
			return errors.New("fleet_requires_intermediate_worker_release")
		}
	}
	return nil
}
func (s *State) commitHealthyRuntime(hasWorkers bool) error {
	if s.Upgrade == nil || s.Upgrade.Stage != "healthy" {
		return errors.New("runtime_not_verified_healthy")
	}
	prior := s.Active
	target := s.Upgrade.Target
	s.Prior = &prior
	s.Active = target
	s.Upgrade = nil
	s.Phase = "ready"
	s.Error = ""
	s.Revision++
	if s.Role == "controller" {
		if hasWorkers {
			s.PendingWorkers = &target
			s.WorkerUpgradeError = "automatic_worker_updates_unavailable"
		} else {
			s.PendingWorkers = nil
			s.WorkerUpgradeError = ""
		}
	}
	return nil
}
