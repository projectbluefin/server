# shellcheck shell=bash
# Bluefin Server prompt for interactive bash: user@host:cwd$ (# for root),
# with only the @ in blue; plain with NO_COLOR or on a dumb terminal.
#
# /etc/profile sources profile.d first and then sets its own PS1, so the
# prompt is (re)applied from PROMPT_COMMAND, and only over the stock prompts:
# a PS1 the user sets (~/.bashrc, by hand) is left alone.
# Linked into /etc/profile.d by tmpfiles (50-bluefin-prompt.conf); to opt
# out, replace that link with an empty file.

[ -n "${BASH_VERSION:-}" ] || return 0
case $- in *i*) ;; *) return 0 ;; esac

__bluefin_prompt() {
    case "${PS1-}" in
        '[\u@\h \W]\$ ' | '\s-\v\$ ') ;;
        *) return 0 ;;
    esac
    if [ -n "${NO_COLOR:-}" ] || [ "${TERM:-dumb}" = dumb ]; then
        PS1='\u@\h:\w\$ '
    else
        PS1='\u\[\e[34m\]@\[\e[0m\]\h:\w\$ '
    fi
}

__bluefin_prompt
# Like systemd's 80-systemd-osc-context.sh: keep an empty slot for a legacy
# PROMPT_COMMAND= assignment, then append.
[ -n "$(declare -p PROMPT_COMMAND 2>/dev/null)" ] || PROMPT_COMMAND+=('')
PROMPT_COMMAND+=(__bluefin_prompt)
