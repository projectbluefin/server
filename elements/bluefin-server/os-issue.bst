kind: import
description: |
  Install console issue banner displaying KubeStellar dashboard URL and IP.

sources:
  - kind: local
    path: files/os/issue.d

config:
  target: /usr/lib/issue.d
