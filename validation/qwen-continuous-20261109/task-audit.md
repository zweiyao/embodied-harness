# LIBERO-PRO libero_10_task 定义与初态只读审计

2026-11-09。范围：当前远程安装包的全部十个任务定义、任务 8 全部 50 个 pruned_init 初态、归档相机标定/单个 world-map 点及 loader 源码。没有启动环境/渲染器、模型或实验；没有修改 runtime、benchmark 或其配置。只在本地 debug 目录保存审计脚本、摘要与本报告。

这是实施前的只读审计快照。其后用户已批准独立修正版，实际实施与配对实验见 [research.md](research.md) 和 [iteration-01/change-plan.md](iteration-01/change-plan.md)；下文“尚未实施”描述审计当时状态。

**2026-11-10 解释更正：** 下文左右投影结论针对标定图。后续记录证实策略图与标定图水平镜像，标定图右边对应策略图左边；因此此前直接断言官方语言/评分存在内在错误的表述过强。保留下文原始审计及数值，最新解释见 [视角更正说明](visual-coordinate-audit/task8-viewpoint-clarification.md)。原作者预期视角未确认，用户批准的私有 right 语言、goal、初态及历史结果均不改变。

## 结论

任务 8 的语言/评分对象冲突已由初态数组和加载顺序证实：文字要求 left moka pot，goal 指向 moka_pot_1，但该对象在 50/50 个保存初态中处于 right 区域。第 0 个初态通过当轮标定投影后，moka_pot_1 中心位于画面列 851.78，moka_pot_2 中心位于列 617.56。故不是仅凭区域名称提出的猜测。

这是离线源码顺序＋实际保存数组解码，未新建模拟器查询 live joint-name/position 表。后续启动获准实验时，应增加只读 named-body/初态校验以确认实际创建模型的对应关系；不把对象真值提供给执行模型或经验库。

## 十任务概览

`benchmark/__init__.py:219` 的 `_make_benchmark` 对 `libero_10_task` 使用列表原顺序，不套用只针对 standard suites 的 permutation。文件名沿用原版任务，不能用文件名替代当前 BDDL language。

| ID | 当前语言含义 | 静态 language/goal 核对 |
| --- | --- | --- |
| 0 | cream cheese 与 tomato sauce 入篮 | 一致 |
| 1 | alphabet soup 与 butter 入篮 | 一致 |
| 2 | 开炉并把 pan 放上去 | 一致 |
| 3 | bottle 入底层抽屉并关上 | 一致 |
| 4 | 黄白杯放左盘、白杯放右盘 | 一致 |
| 5 | cup 放 caddy 后格 | 一致 |
| 6 | 红杯上盘、pudding 放盘右侧 | 一致 |
| 7 | ketchup 与 cream cheese 入篮 | 一致 |
| 8 | 文字左壶、goal 指向右侧对象 | 冲突 |
| 9 | 白杯入微波炉并关门 | 一致 |

其余九项的“一致”是对象名称与目标关系静态核对，未证明所有初态可达或物理判据完全正确。所有十个 BDDL 的绝对路径、SHA256、language、parsed goal 与对象清单均在 [task-audit.json](task-audit.json)。

## 任务 8 可复核证据

基路径 `SITE=/home/zwy/work/harnessvla/.venv/lib/python3.11/site-packages`；下列路径均相对 SITE。

- `liberopro/liberopro/bddl_files/libero_10_task/KITCHEN_SCENE8_put_both_moka_pots_on_the_stove.bddl`：language 为 `put the left moka pot on the stove`；goal 为 `On moka_pot_1 flat_stove_1_cook_region` 和 `Turnon flat_stove_1`。init 把 pot1 放入 right region、pot2 放入 left region。SHA256 `8193749b068293ae3f118f5cf2711c30b42c28657eae15de8a3d21f2293a6caa`。
- 对应 `init_files/libero_10_task/…pruned_init`：SHA256 `a3972734eb5c9b0bbcf7664c1d141a74b921a179d46867b60ba9348d5de890f2`，NumPy shape `(50,47)`。
- `envs/bddl_utils.py:134–143` 按声明顺序解析对象；`envs/problems/libero_kitchen_tabletop_manipulation.py:55` 按该顺序插入 objects_dict。
- `envs/bddl_base_domain.py:383–390` 使用 `list(objects_dict.values())`，模型按 `objects + fixtures` 顺序合并；`robosuite/models/tasks/task.py:105–119` 顺序 append 对象 body。
- Panda XML `robosuite/models/assets/robots/panda/robot.xml` 含 7 个关节；`robosuite/models/assets/grippers/panda_gripper.xml` 含 2 个 slide 指关节。
- `envs/objects/turbosquid_objects.py:164` 的 MokaPot 各含一个 free joint（7 qpos / 6 qvel）；`envs/problems/libero_kitchen_tabletop_manipulation.py:44` 加载 fixture 时传 joints=None；`liberopro/liberopro/assets/articulated_objects/flat_stove.xml` 只有 button hinge。
- 所以 nq=7+2+7+7+1=24，nv=7+2+6+6+1=22；`robosuite/utils/binding_utils.py:230` 定义 flattened 为 `[time,qpos,qvel]`，长度 47 完全吻合。
- `envs/env_wrapper.py:154–163` 的 `set_init_state` 直接设置该状态、forward、更新观测，不重新按对象名排列 qpos。

初态数组索引（Python 从零开始、右端不含）：time `[0:1]`；机器人 `[1:10]`；pot1 free qpos `[10:17]`；pot2 `[17:24]`；炉按钮 `[24:25]`；qvel `[25:47]`。

第 0 个状态：pot1 XYZ `[-0.0488368868,0.2618840102,0.97]`；pot2 `[0.0558150146,0.0744069182,0.97]`。对实际 BDDL 区间做逐行比较，pot1 在 right region 50/50、pot2 在 left region 50/50，不依赖单个轨迹。

当轮归档 `agentview_metadata_high.json/00.json` 的 K/T 投影：pot1 `(row=581.70,col=851.78)`；pot2 `(681.49,617.56)`。投影使用标定相机的正 Z 约定；用 `agentview_world_high.npz/00.npz` 的 `(630,840)` 像素点回投影得到 `(629.9725,840.0441)`，证明约定与记录一致。物体中心投影不是物体完整轮廓，也不代表抓取点。

## 最小隔离修正版路径：LIBERO_CONFIG_PATH 可用，但有一项关键条件

已读实际 loader，尚未实施覆盖：

1. `liberopro/liberopro/__init__.py:7` 在 import 时读取 `LIBERO_CONFIG_PATH`；`:41` 的 `get_libero_path` 从该目录 `config.yaml` 读取路径。
2. 当前 `rlinf/envs/sim/libero/libero_env.py:277` 从 `get_libero_path("bddl_files")` 得到 bddl_root，`:314` 拼接 suite folder/filename，`:441` 将 final_path 作为显式 `bddl_file_name` 交给 worker，`:247` 以该参数创建 WorkerEnv。
3. 同文件 `:450–452` 也从 final_path 提取实际提供给模型的语言；`envs/env_wrapper.py:59–67` 用同一传入文件获取 language 并创建任务。故改私有 BDDL 的 language 会同时影响环境任务语言与 planner 的描述来源。
4. `:622–627` 单独从 config 的 `init_states` 读取初态，根据所选 BDDL 父目录名定位 init 子目录。因此私有根下面应继续叫 `libero_10_task`，不要把内层 suite folder 改为 corrected 名称；修正版 cohort 名放外层目录和报告字段。
5. **关键保护**：`libero_env.py:43–57` 的 `_repoint_libero_config` 比较 `benchmark_root` 与实际安装模块的 `os.path.dirname(os.path.abspath(__file__))`。若不完全相同，会调用 `set_libero_default_path` 重写整份 config，丢掉自定义 bddl_files。必须保持 benchmark_root 为实际安装包绝对路径，只改 bddl_files。
6. 不要把 `LIBERO_BDDL_PATH` 当成覆盖入口：worker 的 `:232–234` 会设回安装包；本链路真正的任务文件来自上述显式 final_path。

拟审核方案 A（独立修正版 cohort）：每个隔离 lane 设私有 LIBERO_CONFIG_PATH；复制十任务 BDDL 到一个只读候选 bddl 根，仅把 task8 的 language `left` 改为 `right`，保持 init、goal、对象、文件名不变。保持 benchmark_root/assets/init_states 为已验证原路径。原安装包与主工作台不变。候选与对照均必须用同一修正任务文本/goal，否则不能把该差异算作工具收益。此方案没有声称在未修正原版的全部十任务上取得成绩。

拟审核方案 B：保持原版全部文件，隔离 task8 的语言/官方成功解释，先在其余九项优化。不能通过把特定右侧坐标写入经验来提高 task8 的官方分数。

以上两方案尚未实施。获准后最低验证：启动脚本在 Python import 前设置私有配置；核对实际日志 final BDDL 路径/语言、goal 与 init hash、原安装文件 hash；确认私有 config 没被 repoint 覆盖；读取初态 named-body 映射并保存独立审计，不暴露给目标模型；将修正版成绩单列。

## 复核命令

精简可执行读取脚本：[audit_task_definitions.py](audit_task_definitions.py)。脚本只用 runpy 加载 parser/map 文件、torch.load 现有 init 数组、NumPy 回投影与源码读取，不导入/构建 LIBERO 环境。

```sh
ssh -o ConnectTimeout=8 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 zwy@10.162.250.228 \
  'cd /home/zwy/work/harnessvla && .venv/bin/python -' \
  < validation/qwen-continuous-20261109/audit_task_definitions.py \
  > /tmp/qwen-task-audit.json
```

执行结果：exit 0，10 个任务，两个区域检查均 50/50；无环境/模型执行。初次脚本尝试用了未加 table 前缀的 region key，触发 KeyError；改为从 parser 返回的完整名称按唯一 suffix 选择后重跑通过。该脚本错误没有更改运行状态或实验结果。
