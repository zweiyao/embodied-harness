# Mac 代理转发至远程 RPent

2026-10-31 部署：远程原有 `127.0.0.1:7900` 代理访问 OpenAI 出现 TLS 连接失败，真机 RPent 改用 Mac 的代理。远程原代理保持运行。

## 连接与进程

Mac 发起 SSH 连接，远程仅监听回环地址：

```sh
ssh -NT -o BatchMode=yes -o ControlMaster=no -o ControlPath=none \
  -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes \
  -R 127.0.0.1:17997:127.0.0.1:7897 zwy@10.162.250.228
```

Mac 的 `~/Library/LaunchAgents/com.embodied-harness.mac-proxy.plist` 运行此命令；登录时启动，进程退出后由 launchd 重启，重启间隔至少 30 秒。日志在 `~/Library/Logs/embodied-harness/mac-proxy.log`。Mac 须保持联网、唤醒，并保持本机 7897 代理可用；SSH 进程存活不等于代理或模型服务可用。

查看或停止该隧道：

```sh
launchctl print gui/$(id -u)/com.embodied-harness.mac-proxy
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.embodied-harness.mac-proxy.plist
```

停止隧道前应结束依赖它的模型请求；恢复使用 `launchctl bootstrap` 加载同一文件。

## RPent 配置

远程 `/home/zwy/work/harnessvla/local-setup/flexiv-dashboard.sh` 设置：

```sh
unset ALL_PROXY all_proxy
export HTTP_PROXY=http://127.0.0.1:17997 HTTPS_PROXY=http://127.0.0.1:17997
export http_proxy="$HTTP_PROXY" https_proxy="$HTTPS_PROXY"
export NO_PROXY=localhost,127.0.0.1,.aliyuncs.com
export no_proxy="$NO_PROXY"
```

Codex SDK 子进程继承此代理。环境、机械臂和本地 MCP 通信绕过代理；阿里云 Qwen 域名也绕过代理。本次只切换真机 `harnessvla-flexiv-dashboard.service`，未修改其他实验服务或系统全局代理。

部署前确认网页空闲，保存并在网页服务重启后恢复模型、工具和预算配置；不重启机械臂服务、不自动启用或发送动作。备份及验证记录保存在远程 `/home/zwy/work/embodied_harness/validation/mac-proxy-20261031/`。回退时恢复其中的 `flexiv-dashboard.sh.before`，在无实验运行时重启网页服务并恢复实验配置。

## 验证

本机 launchd 状态、远程回环监听、网页健康及配置恢复已检查。经隧道请求 ChatGPT 返回 HTTP 403，说明此次 TLS/HTTP 通路已通，但不能据此判断模型授权成功。随后实际 Astra SDK 检查返回 `ok=true`、回复 `ok`，耗时 12.552 秒；结果保存在 `astra-check.json`。启动脚本通过 `bash -n`，LaunchAgent 通过 `plutil -lint`；本次未启动真机实验。
