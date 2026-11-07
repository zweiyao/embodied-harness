# Remote proxy disabled

User explicitly requested disabling the remote proxy. Removed HTTP_PROXY, HTTPS_PROXY, ALL_PROXY and lowercase equivalents from the LIBERO service drop-in and the UniVTAC/Flexiv dashboard launch scripts. The exact scoped changes are in changes.patch; original files are backed up under `/home/zwy/work/embodied_harness/backups/disable-remote-proxy-20261107/`. Independent file content was preserved.

Stopped the remote Clash Verge application scope and its proxy core. The remote desktop proxy mode, TUN mode and Clash auto-launch were already disabled. Booted out and persistently disabled the Mac LaunchAgent `com.embodied-harness.mac-proxy`, which forwarded remote port 17997 to the Mac proxy; the Mac proxy application and plist contents were not changed.

Confirmed all three dashboards idle before restarting only their web/planner processes. Afterwards all are ready, operator inactive, no pending task, environment pending, and have no nonempty proxy environment variables. Remote proxy listeners 7900 and 17997 are closed. Mac access to 8092/8093/8083 returns HTTP 200. Flexiv RDK, RGB-D, tactile and environment service PIDs are unchanged; RDK remains connected and armed=false. No task, reset, gripper or motion command was issued.

Existing provider client, direct Qwen short request with no retries: success in 0.659 seconds, 30 input tokens and 1 output token. This is connectivity verification, not a multimodal speed or task-success benchmark. Other model providers were not called.

Validation: `bash -n` for both changed shell scripts; running process environments, readiness endpoints, closed proxy ports, protected PIDs, RDK health, Mac page access and disabled LaunchAgent state. The first readiness check was made during service startup and was repeated successfully after startup. The Mac Homebrew Python could not import plistlib due to its libexpat linkage; system Python completed the LaunchAgent operation without modifying Python installations. No harness-core code, prompt, experience, tool or task-budget changes; full unit/Sphinx suites not rerun for these operational network changes.
