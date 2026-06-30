kind: stack
description: |
  Lab runner: shell-enabled utility container for CI workflow steps.
  Replaces cgr.dev/chainguard/wolfi-base + apk add in Argo workflow
  templates. Shell is intentionally kept — this is not a distroless
  image. All tools are FSDK-built; no runtime package manager.

depends:
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/curl.bst
  - freedesktop-sdk.bst:components/git.bst
  - freedesktop-sdk.bst:components/jq.bst
  - freedesktop-sdk.bst:components/python3.bst
  - freedesktop-sdk.bst:components/openssh.bst
