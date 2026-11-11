#!/usr/bin/env bash
# Source this file on the remote Linux host before starting an experiment.
# It changes this shell and the user systemd manager, not running processes.
rpent_network() {
    if [[ $(uname -s) != Linux ]]; then
        echo 'Run this script on the remote Linux host.' >&2
        return 1
    fi
    local mode=${1:-status}
    local endpoint=${2:-}
    local key
    local keys=(HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy)
    case "$mode" in
        direct)
            systemctl --user unset-environment "${keys[@]}" || return
            for key in "${keys[@]}"; do unset "$key"; done
            export NO_PROXY=localhost,127.0.0.1,::1
            export no_proxy=$NO_PROXY
            systemctl --user import-environment NO_PROXY no_proxy || return
            ;;
        proxy)
            if [[ ! $endpoint =~ ^http://127\.0\.0\.1:[0-9]+$ ]]; then
                echo 'Supply the existing remote loopback HTTP proxy endpoint.' >&2
                return 1
            fi
            systemctl --user unset-environment "${keys[@]}" || return
            unset ALL_PROXY all_proxy
            export HTTP_PROXY=$endpoint HTTPS_PROXY=$endpoint
            export http_proxy=$endpoint https_proxy=$endpoint
            export NO_PROXY=localhost,127.0.0.1,::1
            export no_proxy=$NO_PROXY
            systemctl --user import-environment HTTP_PROXY HTTPS_PROXY http_proxy https_proxy NO_PROXY no_proxy || return
            ;;
        status) ;;
        *) echo 'Usage: source remote-network.sh direct|proxy URL|status' >&2; return 2 ;;
    esac
    echo "Shell proxy variable names (values withheld):"
    for key in "${keys[@]}"; do
        if [[ -n ${!key:-} ]]; then echo "$key"; fi
    done
    echo 'User systemd proxy variable names (values withheld):'
    systemctl --user show-environment | sed -nE 's/^((HTTP|HTTPS|ALL|NO)_PROXY|(http|https|all|no)_proxy)=.*/\1/p'
}
rpent_network "$@"
