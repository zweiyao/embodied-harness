# B 的有限真实仿真接口检查

根代理在 iteration-02 cleanup 和全部保护检查通过后，明确授权此诊断。
它不调用模型，不消费 iteration-03 的正式条件，不估计任务成功率。

运行源码使用本轮隔离 checkout。Python 启动前设置独立
`LIBERO_CONFIG_PATH`、`LIBERO_TYPE=pro` 和无代理环境；独立配置从 iteration-02
已修正私有 BDDL/原 init 的配置复制，`benchmark_root` 必须精确等于安装路径。
配置设为只读；共享配置、BDDL 和 runtime 源码先后 hash 核验。

使用一个仅本进程拥有的 LIBERO 环境，通过既有 facade/client 调用。
在 probe 进程内增加一个只读环境包装属性，返回机器人夹爪类和
`current_action`；不读取物体真值，不改变控制行为或 live 源文件。

固定 task 0 / seed 0 仅提供接口诊断起点。open、closed、partially-closing
三组各自从同一 reset/init 开始，分别运行原 `move_to(...,gripper=0)` 和 B。
每次只作一个高于原到位容差的短向上目标；参数留在诊断脚本/记录中，
不写入经验。每段沿用原最多 80 步，另有有限夹爪 warmup；全程 watchdog 300 秒。
比较真实逐步 7D 动作、EEF 位姿、夹爪 target、实际 qpos、帧数与终态。
姿态允许原伺服固有漂移，要求 B 与原路径一致，不把漂移强行定义成零。
另检查已到位调用实际零动作且保留原 steps_used=1 的检查迭代行为。

图像、视频和逐步 trace 仅保留远程独立诊断目录；本地只保存小型摘要。
finally 关闭自身 facade/环境，记录所有本 probe 子进程 PID/start-time，
退出后再核实这些进程已退出；不得停止共享工作台/VLA/相机服务。

通过条件：同起点轨迹一致、纯平移 grip/rotation 输入为零、夹爪控制 target 保持、
原步数语义保持、无模型请求、保护 hash 不变、owned 环境清理通过。
实际 qpos 仍可能继续变化，不能以它恒定作为要求，也不能以 target 保持认定抓住物体。
