# 可选 Qwen Mac 出口：待批准的接入范围

本草案只调整网络出口，不改变模型、思考模式、提示词、经验、工具、图像、上下文或实验预算。原 Qwen 配置保留。先接入和验证，不开始任务实验。

## 1. 独立网络进程

拟新增本地工作区 `native-rpent/qwen-mac-egress/relay.py`，完整草稿见 [mac_relay.py](mac_relay.py)。它监听 Mac `127.0.0.1:18090`，只接受原 chat/completions 路径，将请求字节原样发送到已配置的阿里云北京域名，返回流式响应。每次建立独立上游 HTTPS 连接，避免依赖上游空闲连接寿命。它不保存 API key、请求正文、响应正文或图片；不自动重发已发送的请求。

拟新增同目录 `start.sh`，完整草稿：

```bash
#!/bin/bash
set -euo pipefail
relay_root="$(cd -- "$(dirname -- "$0")" && pwd)"
relay_pid=""
tunnel_pid=""
cleanup() {
  if [[ -n "$tunnel_pid" ]]; then kill "$tunnel_pid" 2>/dev/null || true; fi
  if [[ -n "$relay_pid" ]]; then kill "$relay_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM
python3 "$relay_root/relay.py" &
relay_pid=$!
ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 \
  -o ServerAliveCountMax=3 -N \
  -R 127.0.0.1:18091:127.0.0.1:18090 zwy@10.162.250.228 &
tunnel_pid=$!
while kill -0 "$relay_pid" 2>/dev/null && kill -0 "$tunnel_pid" 2>/dev/null; do
  sleep 1
done
exit 1
```

两端均只监听回环，不开公网入口、不改全局代理或防火墙。不设系统开机自启，不修改 Mac 睡眠设置。Mac 断网/休眠时该配置不可用，停止使用并明确记录；不得静默换出口继续同一实验。

## 2. 远程模型配置：只追加一个条目

文件：`/home/zwy/work/embodied_harness/native-rpent/workbench.json` 的 `models` 数组。
修改前没有此 id；修改后追加：

```json
{
  "id": "qwen3.8-flash-mac-egress",
  "label": "Qwen Flash — Mac direct egress",
  "planner": "api",
  "model": "openai-chat:qwen3.8-flash",
  "key_file": "/home/zwy/.config/embodied-harness/qwen-api.key",
  "base_url": "http://127.0.0.1:18091/compatible-mode/v1",
  "reasoning_effort": "none"
}
```

这是本机回环 HTTP，再经 SSH 加密通道到 Mac，最终 HTTPS 到阿里云；不是在局域网明文暴露 API。密钥仍由既有配置读取，relay 不内置密钥。原三个模型条目与默认选择均保留。

如工作台需要重启才能加载模型列表，先确认 LIBERO 无活动任务，保存当前配置，再只重启该工作台服务；不复位环境、不调用动作、不操作真机或 UniVTAC。

## 3. 验证与完成条件

先检查新旧模型声明及非目标文件哈希；短请求与历史多图请求经现有 SDK 成功，保持输入 token 和参数一致。检查较长空闲间隔后新连接、客户端取消、隧道中断的失败可见性和退出清理；断线不静默降级、不自动开始任务。使用单一 Qwen 请求流验证，此草稿不承诺并发吞吐。

记录每次的出口、首个增量、完整耗时、输入/缓存/输出 token，保留失败。确认 Mac 出口仍比远程直连稳定后才用于下一批获批任务；短测收益不当作长期服务保证或任务成功率收益。

新增网络脚本、配置差异及小型验证摘要在验证后提交/推送并更新 PR；凭据、请求正文和图片不提交。修改前核对本地/远程独立修改，按文件保留原内容与恢复副本。
