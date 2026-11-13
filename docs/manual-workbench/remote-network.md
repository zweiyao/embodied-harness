# 远程实验网络选择

在远程 Linux 主机上选择网络，再启动实验或 API 探针。实验脚本只继承环境；Mac 网络保持原样。`source` 会同时更新当前 shell 和用户 systemd manager，已运行进程的环境保持原样。重启工作台前须确认无运行任务，并保存其配置；切换网络不会恢复暂停的批处理。

## 安装 IPv4 直连入口

远程需要已安装 `/usr/bin/verge-mihomo`，并支持用户 systemd 服务。从本仓库根目录安装独立配置和服务：

```bash
install -Dm644 deploy/rpent-ipv4-direct.yaml ~/.config/rpent/network/ipv4-direct.yaml
install -Dm644 deploy/rpent-ipv4-direct.service ~/.config/systemd/user/rpent-ipv4-direct.service
install -d ~/.local/share/rpent/ipv4-direct
/usr/bin/verge-mihomo -t -d ~/.local/share/rpent/ipv4-direct -f ~/.config/rpent/network/ipv4-direct.yaml
systemctl --user daemon-reload
systemctl --user enable rpent-ipv4-direct.service
source deploy/remote-network.sh direct-ipv4
```

该模式启动 `rpent-ipv4-direct.service`，将 HTTP(S) 代理环境指向远程 `127.0.0.1:47040`。入口通过 DIRECT 出站连接目标服务，固定 IPv4，不连接外部代理节点；TUN 关闭，不修改系统路由或全机 IPv6 设置。域名按系统 DNS 解析，IPv6 字面地址请求被拒绝。HTTPS 使用 CONNECT 隧道，不解密图片或 API 请求；请求地址、模型、JSON 和 harness 配置保持原样。使用代理环境变量的客户端会继承该入口，本地 `localhost`、`127.0.0.1` 和 `::1` 仍绕过入口。

启用服务只保证入口随用户 manager 启动；重启主机后，启动实验前仍须显式运行网络选择命令。已运行的工作台不会因上述命令自动接入 IPv4 入口，须在空闲时重启，并核对新进程的环境和实际外联地址。

## 查看与切换

```bash
source deploy/remote-network.sh status
systemctl --user status rpent-ipv4-direct.service
ss -ltnp 'sport = :47040'
```

`status` 仅显示代理变量名，不输出凭据；实际 IPv4 外联应通过新进程请求期间的 `ss -tniap` 核对。已有实验的 HTTP 阶段记录保持原样。

恢复普通直连，交由系统和客户端选择地址：

```bash
source deploy/remote-network.sh direct
```

普通直连模式不会关闭回环转发服务。确认所有依赖该入口的进程已结束或切换后，可以停止或禁用服务：

```bash
systemctl --user disable --now rpent-ipv4-direct.service
```

需要外部代理的模型使用原有模式，先确认相应入口可用，再选择，例如远程原代理：

```bash
source deploy/remote-network.sh proxy http://127.0.0.1:7900
```

网络选择命令不启动这个外部代理，也不重启工作台。各模式供后续新进程继承，勿在实验或探测代码中再次覆盖代理或地址策略。
