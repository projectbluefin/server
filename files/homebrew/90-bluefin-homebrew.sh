# shellcheck shell=sh
# Put Homebrew on PATH once the seed has been extracted.
if [ -x /home/linuxbrew/.linuxbrew/bin/brew ]; then
    eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
fi
