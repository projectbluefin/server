package main

import "errors"

type PodOwner struct {
	Kind string `json:"kind"`
}
type DrainedPod struct {
	Metadata struct {
		Labels          map[string]string `json:"labels"`
		Annotations     map[string]string `json:"annotations"`
		OwnerReferences []PodOwner        `json:"ownerReferences"`
	} `json:"metadata"`
	Status struct {
		Phase string `json:"phase"`
	} `json:"status"`
}

func drainedPodsSafe(pods []DrainedPod) error {
	for _, pod := range pods {
		if pod.Status.Phase == "Succeeded" || pod.Status.Phase == "Failed" || pod.Metadata.Annotations["kubernetes.io/config.mirror"] != "" {
			continue
		}
		daemon := false
		for _, owner := range pod.Metadata.OwnerReferences {
			if owner.Kind == "DaemonSet" {
				daemon = true
			}
		}
		// Deployment platform workloads are pinned to the controller by the
		// immutable policy. A user-controlled label never exempts worker data.
		if !daemon {
			return errors.New("worker_still_has_workloads")
		}
	}
	return nil
}
