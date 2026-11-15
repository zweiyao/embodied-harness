# holmes_RUA

[English](README.md) · [简体中文](README.zh-CN.md)

`holmes_RUA` 是基于 [RPent](https://github.com/RLinf/RPent) 的具身智能体研究项目。研究目标是从多模态交互中的反复失败中提炼可复用经验，将重复的感知处理与判断流程封装为工具，并验证它们对任务成功率、执行时间和 token 消耗的影响。

仓库以 RPent 上游 `ef70215` 的整理快照为起点，包含仿真与 Flexiv 接入、研究工作台及实验分析记录。可执行工具或单轮成功本身不代表方法有效；改进需通过明确条件下的对照实验验证。

## 真机：holmes_RUA 与 RPent

每个任务、每种方法各 5 次。`holmes_RUA` 对应同一任务内进行三轮工具优化；“初始仿真模态”沿用原表的方法名称。Token 和耗时均为**每次实验的平均值**。

| 任务 | 方法 | 成功 / 次数 | 成功率 | 平均 Token | 平均耗时（秒） |
| --- | --- | --- | --- | --- | --- |
| 插 U 盘 | 初始仿真模态 | 0/5 | 0% | 3,273,821 | 1,200.00 |
| 插 U 盘 | RPent | 0/5 | 0% | 1,893,213 | 943.80 |
| 插 U 盘 | holmes_RUA | 4/5 | 80% | 2,638,278 | 493.50 |
| 夹柠檬放抽屉 | 初始仿真模态 | 4/5 | 80% | 2,031,283 | 1,507.30 |
| 夹柠檬放抽屉 | RPent | 5/5 | 100% | 1,872,327 | 1,406.20 |
| 夹柠檬放抽屉 | holmes_RUA | 5/5 | 100% | 1,444,817 | 1,246.80 |
| 做早餐 | 初始仿真模态 | 2/5 | 40% | 1,892,430 | 1,872.80 |
| 做早餐 | RPent | 3/5 | 60% | 1,723,034 | 1,649.20 |
| 做早餐 | holmes_RUA | 5/5 | 100% | 1,263,439 | 1,137.30 |

来源：[维护者提供的真机汇总](validation/holmes-rua-robot-results-20261113/real-robot.json)。本次文档更新按所提供表格录入，未重新核查逐轮真机日志。

## UniVTAC：冻结工具对照

模型为 `gpt-6-astra`，推理强度 high。插管与拔钥匙各跑 seed 0–4；每条件共 10 次，最多 60 次模型响应、10000 输出 token 配置、单请求 300 秒、整轮 3600 秒。`holmes_RUA` 使用开发后冻结的几何感知工具 `d6c13e92`，测试期间不再调整工具；这组条件与真机的“三轮优化”分开记录。

| 任务 | 方法 | 成功 / 次数 | 成功率 | 平均 Token | 平均耗时（秒） |
| --- | --- | --- | --- | --- | --- |
| 插管（任务 1） | RPent（首次基线） | 4/5 | 80% | 617,724.4 | 285.50 |
| 插管（任务 1） | RPent（原生复测） | 3/5 | 60% | 838,255.4 | 337.58 |
| 插管（任务 1） | holmes_RUA（冻结工具） | 4/5 | 80% | 672,493.8 | 362.32 |
| 拔钥匙（任务 2） | RPent（首次基线） | 2/5 | 40% | 1,226,303.2 | 427.44 |
| 拔钥匙（任务 2） | RPent（原生复测） | 5/5 | 100% | 961,619.2 | 306.16 |
| 拔钥匙（任务 2） | holmes_RUA（冻结工具） | 4/5 | 80% | 679,407.4 | 258.10 |
| **总体** | RPent（首次基线） | 6/10 | 60% | 922,013.8 | 356.47 |
| **总体** | RPent（原生复测） | 8/10 | 80% | 899,937.3 | 321.87 |
| **总体** | holmes_RUA（冻结工具） | 8/10 | 80% | 675,950.6 | 310.21 |

这批记录中，相比最近一次 RPent 原生复测，冻结工具版成功率同为 **80%**，平均 Token 减少 **24.89%**、平均耗时减少 **3.62%**。每条件仅 10 次，不能据此确认稳定的成功率或因果收益；首次原生基线一并保留，便于比较批次波动。

Token 为输入加输出，缓存输入不重复计入；平均值包含有效失败，工具制作成本不在表中。这里是 Astra 的小样本冻结工具测试，不包含 Qwen 迁移结果。详见[原始对照说明](validation/univtac-authored-geometry-test-20261103/README.md)和[逐次统计快照](validation/holmes-rua-robot-results-20261113/univtac.json)。

## LIBERO：RPent 实测结果

**本节为本项目使用 RPent harness 测得的结果，不是 RPent 论文成绩，也不是 holmes_RUA 优化后的提升结果。** 原始结果按环境官方成功信号统计，模型口头宣告完成不计作成功。不同任务集、预算和网络条件的批次分别列出，不能直接用它们推断某项优化的因果收益。

### GPT / Astra：LIBERO-Pro `libero_10_task`

模型 `gpt-6-astra`，Codex planner，`reasoning_effort=low`；任务 0–9 各 5 次，共 50 次。每次最多 30 次已完成模型响应、600 秒；使用 RPent 原生 17 个工具及冻结经验 `language-c592f23a3a324c08`。基础设施意外保留归档并排除，补跑对应任务；超时与预算耗尽计失败。

| 任务 | 成功 / 有效次数 | 成功率 | 平均交互次数 | 平均用时（秒） | 平均 token | 总 token |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 5/5 | 100.0% | 14.0 | 163.4 | 565,809 | 2,829,046 |
| 1 | 5/5 | 100.0% | 17.4 | 207.8 | 808,469 | 4,042,344 |
| 2 | 4/5 | 80.0% | 22.2 | 216.5 | 1,296,358 | 6,481,792 |
| 3 | 2/5 | 40.0% | 23.8 | 334.8 | 1,386,704 | 6,933,519 |
| 4 | 1/5 | 20.0% | 29.4 | 274.9 | 1,841,347 | 9,206,737 |
| 5 | 5/5 | 100.0% | 11.4 | 107.1 | 418,977 | 2,094,886 |
| 6 | 4/5 | 80.0% | 22.4 | 217.8 | 1,158,476 | 5,792,379 |
| 7 | 5/5 | 100.0% | 17.2 | 154.2 | 766,096 | 3,830,481 |
| 8 | 4/5 | 80.0% | 17.6 | 181.4 | 817,257 | 4,086,287 |
| 9 | 0/5 | 0.0% | 30.0 | 282.3 | 2,060,328 | 10,301,639 |
| **合计** | 35/50 | 70.0% | 20.5 | 214.0 | 1,111,982 | 55,599,110 |

### Qwen Flash：LIBERO-Pro `libero_10_task`

模型 `qwen3.8-flash`，API planner，关闭思考；任务 0–9 各 5 次，共 50 次，最多 30 次模型请求，原生工具及冻结经验与上述批次相同。**本批是混合时间预算：3000 秒组 2/8 成功，1500 秒组 1/42 成功。** 早期 600 秒尝试不混入。这里的合计仅作历史描述，不是统一预算基准。

| 任务 | 成功 / 有效次数 | 成功率 | 平均交互次数 | 平均用时（秒） | 平均 token | 总 token |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 2/5 | 40.0% | 27.6 | 2333.1 | 833,850 | 4,169,248 |
| 1 | 0/5 | 0.0% | 27.8 | 2180.5 | 1,051,854 | 5,259,268 |
| 2 | 0/5 | 0.0% | 30.0 | 282.8 | 1,357,440 | 6,787,199 |
| 3 | 0/5 | 0.0% | 30.0 | 235.7 | 1,228,947 | 6,144,737 |
| 4 | 0/5 | 0.0% | 30.0 | 194.7 | 1,113,165 | 5,565,823 |
| 5 | 1/5 | 20.0% | 28.2 | 199.7 | 1,049,023 | 5,245,115 |
| 6 | 0/5 | 0.0% | 27.2 | 480.3 | 1,035,975 | 5,179,877 |
| 7 | 0/5 | 0.0% | 24.4 | 466.9 | 803,826 | 4,019,129 |
| 8 | 0/5 | 0.0% | 30.0 | 167.2 | 924,672 | 4,623,361 |
| 9 | 0/5 | 0.0% | 30.0 | 168.2 | 1,026,412 | 5,132,061 |
| **合计** | 3/50 | 6.0% | 28.5 | 670.9 | 1,042,516 | 52,125,818 |

### Qwen Flash：Object-T 阶段结果

LIBERO-Pro `libero_object_task`，模型 `qwen3.8-flash`，关闭思考，RPent 原版提示词、冻结经验及 17 个原生工具。每次最多 **50 次模型请求，无任务总时限**，模型 HTTP 与环境 / VLA / SAM3 RPC 无超时限制；原生仿真动作预算保留。网络为远程 IPv4 直连。

截至 **2026-11-13 13:32（北京时间）的数据核查**，仅计已结算的 **44/50** 个唯一任务 / seed，39 次成功。5 个切换前样本已排除，其中 4 个已用 IPv4 复测替换。任务 1、8、9 尚未齐全，待完成项不计为失败；**88.6% 是已完成样本的阶段成功率，不是完整 50 次成绩。**

| 任务 | 成功 / 有效次数 | 成功率 | 平均交互次数 | 平均用时（秒） | 平均 token | 总 token |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 5/5 | 100.0% | 18.2 | 603.9 | 452,810 | 2,264,051 |
| 1 | 4/4 | 100.0% | 20.0 | 1107.7 | 550,527 | 2,202,109 |
| 2 | 5/5 | 100.0% | 12.6 | 80.7 | 297,266 | 1,486,328 |
| 3 | 5/5 | 100.0% | 15.4 | 97.1 | 404,372 | 2,021,861 |
| 4 | 3/5 | 60.0% | 39.4 | 371.7 | 1,557,204 | 7,786,020 |
| 5 | 5/5 | 100.0% | 25.8 | 196.7 | 830,491 | 4,152,455 |
| 6 | 2/5 | 40.0% | 43.8 | 433.7 | 1,840,018 | 9,200,092 |
| 7 | 5/5 | 100.0% | 19.0 | 141.6 | 584,392 | 2,921,961 |
| 8 | 3/3 | 100.0% | 14.0 | 82.8 | 314,116 | 942,347 |
| 9 | 2/2 | 100.0% | 27.5 | 212.6 | 917,606 | 1,835,211 |
| **合计** | 39/44 | 88.6% | 23.8 | 334.8 | 791,192 | 34,812,435 |

交互次数按各适配器归档口径统计：Codex/Astra 为已完成模型响应数，Qwen API planner 为模型请求数，均包含有效失败。两者计数定义不同，也不等于物理动作数。平均用时包含成功与有效失败；token 为 API 返回的输入加输出，缓存输入已包含在输入中，不重复相加。完整条件、逐次小型结果及原始文件摘要见 [结果快照](validation/holmes-rua-homepage-20261113/results.json)。统计快照时间以该文件的 `checked_at` 为准。

## RoboDojo：RPent 单轮测试（53 个有效任务，1 个初始化异常）

**有效结果为 4/53（7.55%），不是完整 54 个有效样本的成绩。** `imitate_sorting_sequence` 因原生 `CollectEnv` 缺少演示臂轨迹加载所需的 `eval_seed` 而未进入模型执行，单列为初始化异常。49 个有效失败中，3 个为超时、46 个为其他未通过环境判分的结束。逐一核对 53 份主实验 SDK 日志，未见额度或模型连接错误。独立复盘另完成 21 轮、2 轮因额度失败、30 轮未处理；复盘错误不改变主实验判分。

本项目使用 RPent 当前开发配置，已尝试官方清单的 54 个任务，均为 layout 0，其中 53 个进入有效测试。前 9 个结果为串行；暂停后保留有效结果，剩余任务以两个独立环境并行，Pi/SAM3 共享服务串行处理请求；手动中断的尝试排除。执行拓扑不同，耗时不能视为统一负载下的性能。模型为 `gpt-6-astra`（Codex，reasoning low），使用 12 个原生工具和冻结只读经验库 `language-c592f23a3a324c08`；每任务最多 120 次模型响应、16384 输出 Token 设置、600 秒规划预算。规划预算包含工具执行，表中耗时另含环境启动与清理。Pi0.5 使用 RoboDojo 双 ARX-X5 权重。原生动作次数不限，属于 **dev 诊断配置，不是官方评测，也不是 RPent 论文成绩**。

成功只认环境官方判分，超时算失败；基础设施异常单列并排除成功率分母。每任务仅一次，不能用该表证明稳定成功率、经验迁移效果或优化收益。交互为 Codex 报告的模型响应数，不等于工具调用或机器人动作；Token 为输入加输出，缓存不重复相加。表中指标仅计主实验，独立复盘 agent 的用量另记。

| 任务 | 成功 / 有效次数 | 成功率 | 平均交互 | 平均耗时（秒） | 平均 Token | 结算 |
| --- | --- | --- | --- | --- | --- | --- |
| `align_blocks` | 0/1 | 0% | 30 | 422.2 | 857,732 | 失败 (finish: stuck) |
| `arrange_largest_number` | 0/1 | 0% | 59 | 632.9 | 2,299,349 | 失败 (finish: stuck) |
| `arrange_largest_number_random` | 0/1 | 0% | 53 | 669.3 | 2,088,873 | 失败 (finish: stuck) |
| `build_tower` | 0/1 | 0% | 18 | 235.1 | 454,094 | 失败 (finish: success) |
| `classify_objects` | 0/1 | 0% | 41 | 450.1 | 1,552,169 | 失败 (finish: stuck) |
| `classify_objects_by_language` | 0/1 | 0% | 43 | 560.2 | 1,648,843 | 失败 (finish: stuck) |
| `cover_blocks` | 0/1 | 0% | 27 | 332.2 | 873,840 | 失败 (finish: stuck) |
| `deposit_coin` | 0/1 | 0% | 23 | 256.2 | 616,672 | 失败 (finish: stuck) |
| `fasten_screws` | 0/1 | 0% | 28 | 347.0 | 765,075 | 失败 (finish: stuck) |
| `fill_egg_holder` | 0/1 | 0% | 33 | 408.9 | 1,182,051 | 失败 (finish: stuck) |
| `fill_pen_holder` | 0/1 | 0% | 57 | 647.6 | 2,222,205 | timeout |
| `fold_clothes` | 1/1 | 100% | 29 | 352.0 | 930,369 | 成功 |
| `fold_clothes_random` | 0/1 | 0% | 44 | 686.3 | 1,511,519 | 失败 (finish: stuck) |
| `general_pickup` | 1/1 | 100% | 37 | 389.2 | 1,211,170 | 成功 |
| `hang_mugs` | 0/1 | 0% | 40 | 564.3 | 1,565,256 | 失败 (finish: stuck) |
| `hang_mugs_random` | 0/1 | 0% | 30 | 410.3 | 888,631 | 失败 (finish: stuck) |
| `imitate_sorting_sequence` | — | — | — | — | — | 异常（排除） |
| `insert_key` | 0/1 | 0% | 22 | 287.2 | 680,947 | 失败 (finish: stuck) |
| `insert_tubes` | 1/1 | 100% | 19 | 172.2 | 476,749 | 成功 |
| `make_kong` | 0/1 | 0% | 26 | 318.1 | 836,334 | 失败 (finish: stuck) |
| `make_toast` | 0/1 | 0% | 51 | 637.3 | 1,803,068 | 失败 (finish: stuck) |
| `make_toast_random` | 0/1 | 0% | 46 | 565.3 | 1,674,933 | 失败 (finish: stuck) |
| `match_and_pick_from_conveyor` | 0/1 | 0% | 24 | 593.1 | 1,198,794 | 失败 (finish: stuck) |
| `organize_table` | 0/1 | 0% | 28 | 373.4 | 969,985 | 失败 (finish: stuck) |
| `pack_objects_into_box` | 0/1 | 0% | 38 | 462.1 | 1,249,672 | 失败 (finish: completed_unverified) |
| `pack_objects_into_box_random` | 0/1 | 0% | 38 | 530.2 | 1,075,155 | 失败 (finish: stuck) |
| `pick_from_conveyor_by_image` | 0/1 | 0% | 16 | 190.2 | 400,618 | 失败 (finish: stuck) |
| `play_Xylophone` | 0/1 | 0% | 26 | 304.0 | 858,568 | 失败 (finish: stuck) |
| `play_stacking_toy` | 0/1 | 0% | 30 | 302.1 | 899,609 | 失败 (finish: stuck) |
| `play_tic_tac_toe` | 0/1 | 0% | 41 | 471.1 | 1,393,427 | 失败 (finish: stuck) |
| `plug_in_charger` | 0/1 | 0% | 22 | 273.1 | 673,020 | 失败 (finish: stuck) |
| `pour_balls_into_vase` | 0/1 | 0% | 14 | 237.4 | 358,368 | 失败 (finish: failure) |
| `pour_by_language` | 0/1 | 0% | 44 | 676.4 | 1,430,186 | timeout |
| `pour_liquid_into_cup` | 0/1 | 0% | 26 | 335.3 | 764,041 | 失败 (finish: failure) |
| `pour_liquid_into_cup_random` | 0/1 | 0% | 27 | 422.4 | 774,634 | 失败 (finish: unverified) |
| `press_by_number` | 0/1 | 0% | 21 | 317.2 | 522,915 | 失败 (finish: unverified) |
| `push_T` | 0/1 | 0% | 44 | 532.3 | 1,803,652 | 失败 (finish: stuck) |
| `push_T_random` | 0/1 | 0% | 40 | 498.3 | 1,331,066 | 失败 (finish: stuck) |
| `put_bottles_into_dustbin` | 0/1 | 0% | 44 | 467.3 | 1,832,154 | 失败 (finish: success) |
| `solve_equation` | 0/1 | 0% | 42 | 395.3 | 1,565,192 | 失败 (finish: stuck) |
| `sort_nesting_dolls_by_size` | 0/1 | 0% | 37 | 355.3 | 1,428,817 | 失败 (finish: stuck) |
| `sort_nesting_dolls_by_size_random` | 0/1 | 0% | 25 | 347.4 | 842,681 | 失败 (finish: stuck) |
| `stack_blocks` | 0/1 | 0% | 66 | 646.1 | 3,569,675 | timeout |
| `stack_blocks_by_language` | 0/1 | 0% | 43 | 406.2 | 1,495,506 | 失败 (finish: stuck) |
| `stack_blocks_random` | 0/1 | 0% | 27 | 329.5 | 736,678 | 失败 (finish: stuck) |
| `stack_bowls` | 1/1 | 100% | 18 | 180.3 | 426,217 | 成功 |
| `stack_bowls_random` | 0/1 | 0% | 15 | 225.5 | 380,106 | 失败 (finish: success) |
| `store_laptop_and_headphones` | 0/1 | 0% | 45 | 501.4 | 1,830,554 | 失败 (finish: stuck) |
| `store_laptop_and_headphones_random` | 0/1 | 0% | 31 | 379.6 | 1,124,614 | 失败 (finish: stuck) |
| `store_tools_in_toolbox` | 0/1 | 0% | 39 | 499.3 | 1,326,800 | 失败 (finish: stuck) |
| `swap_T` | 0/1 | 0% | 36 | 512.2 | 1,342,675 | 失败 (finish: stuck) |
| `swap_blocks` | 0/1 | 0% | 30 | 347.3 | 965,089 | 失败 (finish: stuck) |
| `sweep_blocks` | 0/1 | 0% | 39 | 569.2 | 1,393,208 | 失败 (finish: stuck) |
| `sweep_blocks_random` | 0/1 | 0% | 31 | 403.5 | 868,818 | 失败 (finish: stuck) |
| **合计** | 4/53 | 7.55% | 34.0 | 423.2 | 1,188,158 | 已尝试 54/54 |

[完整条件、任务指令与逐次结果](validation/robodojo-alltasks-20261114/results.json).

## 使用与开发

| 入口 | 内容 |
| --- | --- |
| [快速开始](docs/source-zh/rst_source/get_started/quickstart.rst) | 环境安装、资产、权重与首次任务 |
| [研究工作台](docs/manual-workbench/README.md) | 模型配置、工具选择、实验记录与回放 |
| [LIBERO 指南](docs/source-zh/rst_source/simulators/libero.rst) | 安装、仿真资产、任务与评测 |
| [UniVTAC](robots/univtac/README.md) / [Flexiv](robots/flexiv/README.md) | 各环境部署要求与限制 |
| [RoboDojo](docs/source-zh/rst_source/simulators/robodojo.rst) / [RoboCasa](docs/source-zh/rst_source/simulators/robocasa.rst) / [RoboTwin](docs/source-zh/rst_source/simulators/robotwin.rst) | 仿真接入说明；支持状态以各指南为准 |
| [开发说明](CONTRIBUTING_zh.md) / [测试](tests/README.md) | 贡献约定、接口与验证方法 |

项目展示名称为 `holmes_RUA`。Python 包、CLI 命令及配置兼容名称仍为 `rpent`；GitHub 仓库地址仍为 `zweiyao/embodied-harness`。外部硬件采集器、凭据、录像、原始观测、标定数据与模型权重不随源码发布。

## 上游与许可

本项目基于 [RLinf/RPent](https://github.com/RLinf/RPent)，遵循 [Apache-2.0 许可证](LICENSE)，保留上游署名。RPent 及其 Harness VLA 工作的引用如下：

```bibtex
@article{zhang2026harnessvla,
  title={Harness VLA: Steering Frozen VLAs into Reliable Manipulation Primitives via Memory-Guided Agents},
  author={Zhang, Yixian and Zhang, Huanming and Gao, Feng and Li, Xiao and Liu, Zhihao and Zhu, Chunyang and Qiu, Jiaxing and Yan, Yuchen and Liu, Jiyuan and Tang, Wenhao and Fang, Zhengru and Nie, Yi and Wei, Changxu and Wang, Yu and Ding, Wenbo and Yu, Chao},
  journal={arXiv preprint arXiv:2607.08448},
  year={2026},
  url={https://arxiv.org/abs/2607.08448}
}
```
