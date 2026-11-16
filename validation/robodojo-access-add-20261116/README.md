# Add the current operator IP to RoboDojo access

The 8094 RoboDojo entry now permits both `10.230.32.89` and the current operator
address, `10.162.217.98`. The new address was confirmed by the live SSH source
and the entry's browser rejection logs. Existing access was retained.

The LAN relay accepts repeated `--allow` flags and matches complete source IPs.
Single-address use remains compatible; forwarded headers cannot grant access.
Tests cover both positions in the allowlist, nonmatching/prefix addresses,
bidirectional streaming and repeated CLI arguments.

Only `rpent-robodojo-lan-access.service` was restarted. Its working directory
now selects the updated relay in the isolated prompt-system checkout. The old
unit was backed up before adding the second `--allow` flag. Dashboard, robot,
model and other environment process IDs were unchanged. No Mac network, proxy
selection, other entry whitelist or robot RPC exposure was changed.

The current Mac received HTTP 200 from `/`, `/runs` and `/api/runs`; a historical
video Range request returned 206. The remote host's non-whitelisted source
`10.162.250.228` was rejected. Existing old-IP membership is covered by exact-IP
relay tests and the deployed configuration; the old client address was not
available for a separate live request.

Remote evidence and the service backup are in
`/home/zwy/work/embodied_harness/validation/robodojo-access-add-20261116/`.
`summary.json` records final checks. This is IP-based access restriction, not
device authentication. The public address remains
<http://10.162.250.228:8094/>.
