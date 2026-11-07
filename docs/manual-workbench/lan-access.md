# RPent 局域网访问

远程入口仅允许 TCP 来源地址 `10.162.217.98`（操作员当前 Mac）。不读取
`X-Forwarded-For` 等 HTTP 头作为放行依据，不提供通用代理或任意目标转发。

| 工作台 | 直接访问地址 |
| --- | --- |
| LIBERO | http://10.162.250.228:8092/ |
| UniVTAC | http://10.162.250.228:8093/ |
| Flexiv 真机 | http://10.162.250.228:8083/ |

原工作台继续监听远程回环地址，入口仅转发这三个网页端口，支持原有流式响应、
图像及长连接。无需重启工作台，不改变实验、工具或机器人控制。底层控制服务
保持原监听方式，未加入对外入口。

将 `deploy/rpent-lan-access.service` 安装到远程用户的
`~/.config/systemd/user/`，执行 `systemctl --user daemon-reload` 和
`systemctl --user enable --now rpent-lan-access.service`。关闭入口使用
`systemctl --user disable --now rpent-lan-access.service`，不影响原工作台。
用户服务需要登录会话或启用 linger 才能持续运行。此次部署已启用 linger，
退出 SSH 后入口仍运行；已配置自启动，未通过实际重启主机验证。

这是来源 IP 限制，不是设备身份认证，也不加密 HTTP。Mac 地址变化后会拒绝
访问；应核实新的地址并经用户确认更新 `--allow`，不能自动放宽到整个网段。
若旧地址被其他设备分配，该设备也会符合 IP 条件；长期固定使用宜在网络侧
保留地址，或另行配置带认证的加密访问。远程地址变化需相应更新 `--bind`。
其他既有服务的监听范围不由这个入口管理。
