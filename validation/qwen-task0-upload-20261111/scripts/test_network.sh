#!/usr/bin/env bash
set -euo pipefail
script=$1
# Fake only systemd operations; no actual manager or network changes in this test.
systemctl() { [[ $1 == --user ]]; return 0; }
export HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9
export ALL_PROXY=http://127.0.0.1:9 http_proxy=http://127.0.0.1:9
export https_proxy=http://127.0.0.1:9 all_proxy=http://127.0.0.1:9
source "$script" direct >/dev/null
for key in HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy; do
    [[ ! -v $key ]]
done
[[ $NO_PROXY == localhost,127.0.0.1,::1 && $no_proxy == "$NO_PROXY" ]]
source "$script" proxy http://127.0.0.1:17997 >/dev/null
[[ $HTTP_PROXY == http://127.0.0.1:17997 && $https_proxy == "$HTTP_PROXY" ]]
[[ ! -v ALL_PROXY && ! -v all_proxy ]]
if source "$script" proxy invalid >/dev/null 2>&1; then exit 1; fi
[[ $HTTP_PROXY == http://127.0.0.1:17997 ]]
source "$script" status >/dev/null
[[ $HTTP_PROXY == http://127.0.0.1:17997 ]]
echo '{"passed":true,"cases":["direct removes inherited proxies","proxy sets both cases","invalid mode preserves state","status is read-only"],"real_network_changes":false}'
