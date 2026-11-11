# B：可选纯平移接口

已按根代理审查后的 READY 实施 `translate_to(xyz)`，并完成远程隔离验证。
尚未部署到 live runtime，未选入模型实验。随后经根代理确认 iteration-02 cleanup
通过，在独立诊断目录完成有限真实仿真接口检查。

## 改动

新工具只接受三个有限的世界坐标数，内部调用原
`move_to(xyz, gripper=0)`，沿用原姿态保持方式和全部伺服默认。
模型不再为这类纯平移重新输入夹爪参数或四元数。原工具继续存在，
其接口、实现、控制参数和步数上限均未改变；模型仍可能选择原工具。

工作台默认不选新工具。显式选择时增加两句纯平移引导；未选中时，
原默认工具集合和旧提示保持一致。单选 B 不需要 EEF controller RPC；
同时选择 `move_eef` 时，它的原 controller 检查仍生效。

`gripper=0` 保留控制目标，不冻结实测指间距离，不证明抓牢，也不自动避障。
原 `move_to` 的长距离分段约束仍保留在新说明中。
原 `steps_used` 包括到位检查迭代，可能比实际动作步数多一次；本轮保留该统计，
未修改原 primitive。实际动作数需按环境执行/记录帧另核。

本轮未实施 W1 工作流、API hook、新经验或多 agent 架构；
`robots/libero/tools.py` 与 core planner 均未修改。
审批依据和应用前基线保存在本目录的 decision、patch 和 hash 文件中。

## 来源与机制

本轮根代理与审计代理提供的轨迹证据解释了候选动机，不构成 B 的有效性结果：

- iteration-01 C task 4：已抓住并抬起物体，搬运时显式传入 `gripper=-1` 后掉物。
- iteration-01 E task 0：抓取、短提及搬运原本有效；req19 将 req18 正确返回的
  xyzw 四元数整个倒序用于原本仅需平移的动作。错误目标要求约 2.8943 rad
  旋转，实际旋转约 0.7165 rad（41.05°）；2.1804 rad 是剩余目标误差。
  后续原 `move_to` 保持的是已改变的姿态。C task 0 使用 18 请求、约 281 秒成功，
  这一历史单例也不是 B 的效果证明。
- iteration-02 E+T task 0：第一次 Pi0 的启发式 success 为 true，但图像中奶酪仍在桌上。
  req5 声称做短横移验证 holding，却显式开爪，使该验证失去判别力；
  不能把它描述为放掉了已成功抓取的物体。第二次 Pi0 后才出现实际抓起。
- iteration-02 E+T task 4：第一杯闭爪搬运并释放到左盘；第二杯 Pi0 后图像显示 holding，
  req20/24 的提升或下降却显式给出 `-1`，物体落在左盘旁。
  该轨迹四次 patch 调用均未用 `alignment_pair`。此次 pi0 success=false 源于
  下降启发式未满足，不能据此判定没抓住。

这些错误共同指向：纯平移不需要模型重复决定开闭或重排姿态。
B 能排除其自身接口内的这两类误参，但不能判断选点身份、建立抓持，
或阻止模型在错误时机调用原工具/显式 release。
iteration-01 E task 4 的空抓搬运是另一个问题，B 没有解决它。

## 验证

验证目录：
`/home/zwy/work/embodied_harness/validation/qwen-continuous-20261109/motion-contract-test-checkout`。
使用既有远程 Python 3.11 环境；未覆盖全部 CI Python 矩阵。

| 检查 | 结果 |
| --- | --- |
| 定向 EEF、ManualToolkit、Workbench | 48 passed，0.76 秒 |
| 隔离 checkout 全量 unit suite | 2056 passed / 15 skipped，73.42 秒 |
| B 六文件 scoped pre-commit | 通过；只修复本轮新增测试写法和格式 |
| 无仿真验证脚本 scoped pre-commit/直接 Ruff | 通过 |
| 相同起点与原 `move_to(..., 0)` 逐步动作对照 | 相同，含非平凡初始姿态和已到位情况 |
| 停滞预算、非法输入、取消、终止 | 通过；保留原预算和原到位计数 |
| 默认工具及三种旧提示快照 | 与改动前 checkout 完全一致 |
| B 单独注册/动作后图像记录/旧 EEF 校验 | 通过 |
| 已安装 PandaGripper、Robotiq85Gripper 的 `format_action(0)` | 三组目标保持；`-1` 对照改变目标 |
| Live、旧/新工具库、01/02 固定配置保护 | 33 项 hash 保持 |
| 独立真实仿真 old/B 三种夹爪目标对照 | 6 段通过，每段 3 个真实平移控制步 |
| 已到位调用 | 实际 0 步，保留原 steps_used=1 |
| 真实仿真清理 | 自有环境关闭；无残留进程，无强制清理 |

夹爪检查直接调用已安装类的格式化方法，未加载 XML、创建环境或 reset；
它验证的是 command target 数学语义，未验证真实接触中的指间距或抓持。
只读检查当前 server/RLinf 的 step 转发未见夹爪零值重编码；
真实仿真随后在独立只读 config 下执行，实际模块来自候选源码，
`RPENT_REPO_ROOT`/`PYTHONPATH` 双隔离，所有代理变量为空。
实际 PandaGripper 的 open、closed-target、partial-target 三组中，B 与原方法的
逐步动作、EEF 位姿和 qpos 在 1e-7 数值容差内一致，夹爪 target 保持。
每组姿态漂移约 0.003536 rad，B 与原方法完全相同；没有把原伺服漂移宣称为零。
这包含 18 个显式平移步和 32 个夹爪 warmup 步，环境 reset 内部等待步另计。
图像、视频及逐步 trace 仅在远程 `motion-contract/sim-probe-20261109/` 保留，
本地只有 `sim-probe-summary.json`、`sim-probe-cleanup.json` 和复现脚本。
共享配置、BDDL、运行源码前后 hash 保持，诊断不计入任务成功率。

全仓 pre-commit 未重跑；此前无关存量问题保留。
原始 live 独立修改未覆盖。没有模型请求或正式评测格启动。
具体 hash、源码声明和范围见 `validation.json`、`translate-to-declaration.json`
及 `offline-contract-check.json`。
完整源码差异与当前 Qwen 路径的隔离依据见 `source-differences.md`；
并非整个验证工作树在字节上只差 M。

后续 iteration-03 已确定使用 C 作为背景，条件记作 C+M（M 即本轮开发代号 B），
与此前 C 的相同 task 4/0、seed 0 对照，不叠加 E 或 T。正式启动仍由根代理确认。
继续冻结 30 请求/600 秒，并分别记录 M 是否被调用、
误参是否减少、其他失败根因以及官方任务成功。当前检查不能证明成功率或时间/token 收益。
