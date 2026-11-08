# shellcheck shell=sh
# Put Homebrew on PATH once the seed has been extracted.
if [ "$(id -u)" -ne 0 ] &&
    [ -r /var/lib/bluefin-homebrew/seed-owner ] &&
    [ "$(id -u)" = "$(cut -d: -f1 /var/lib/bluefin-homebrew/seed-owner)" ] &&
    [ -x /home/linuxbrew/.linuxbrew/bin/brew ]; then
    eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
    bluefin_docker_backend=podman
    if systemctl --user is-active --quiet bluefin-docker.service; then
        bluefin_docker_backend=docker
    fi
    export CONTAINER_HOST="${CONTAINER_HOST:-unix:///run/user/$(id -u)/bluefin-podman/api.sock}"
    export DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/bluefin-$bluefin_docker_backend/api.sock}"
    unset bluefin_docker_backend
fi
