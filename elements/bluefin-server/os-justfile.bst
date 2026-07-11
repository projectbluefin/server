kind: import
description: Install system-wide justfile into target OS image.

sources:
  - kind: local
    path: files/os/justfile

config:
  target: /etc
