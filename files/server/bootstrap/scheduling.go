package main

import (
	"encoding/json"
	"errors"
)

type NodeTaint struct {
	Key    string `json:"key"`
	Effect string `json:"effect"`
}

func controllerSchedulingTaint(taints []NodeTaint) bool {
	for _, taint := range taints {
		if taint.Key == "node-role.kubernetes.io/control-plane" && taint.Effect == "NoSchedule" {
			return true
		}
	}
	return false
}
func ensureSchedulableController(name string) error {
	inspect := func() (bool, error) {
		out, err := kube("get", "node", name, "-o", "json")
		if err != nil {
			return false, err
		}
		var node struct {
			Spec struct {
				Taints []NodeTaint `json:"taints"`
			} `json:"spec"`
		}
		if err = json.Unmarshal(out, &node); err != nil {
			return false, err
		}
		return controllerSchedulingTaint(node.Spec.Taints), nil
	}
	blocked, err := inspect()
	if err != nil {
		return err
	}
	if !blocked {
		return nil
	}
	if _, err = kube("taint", "node", name, "node-role.kubernetes.io/control-plane:NoSchedule-"); err != nil {
		return err
	}
	blocked, err = inspect()
	if err != nil {
		return err
	}
	if blocked {
		return errors.New("controller_remains_unschedulable")
	}
	return nil
}
