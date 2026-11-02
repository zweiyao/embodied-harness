# UniVTAC 任务0工具开发与冻结验证

用户于2026-11-02授权：开发仅任务0，Astra探索感知模态的有效使用方式，最多优化五次，
之后冻结并在同一测试任务上验证。正在运行；本文件不预报实验结论。

## 事前确定的条件

- 模型：实验、制作、评议都使用远程 Codex SDK 的 gpt-6-astra high。
- 原生基线：observe、read_image、read_depth、tactile_stats、move_eef、finish。
- 原始控制器、动作后图像、官方任务指令和判分均保持原样。
- 预算：每轮60次模型响应、10000 token配置、单请求300秒、整轮3600秒。
  Maker/评议分别最多一次SDK调用/优化，300秒、10000输出token软上限并事后核查。
- 开发基线：insert_hole seed 0、1、2 各一次。
- 每次优化只生成/修改一个 sensor_modal_evidence，在相同三个开发seed各验证一次。
  最多3+5×3=18轮开发仿真，不把同seed解释成相同物理状态。
- 候选只有被实际调用且正常返回才参与保留；按官方成功数优先，同成功数时平均输入+输出token更少优先。
- 提前停止要求：3/3开发成功、总token下降至少20%，Astra根据采用与结果认为可靠性和token都有收益。
  否则做到第五次。Astra主观评价本身不构成增益证据。
- 冻结开发集上最好的版本；若所有工具都无采用或无改善，则冻结原生基线并保留负结果。
- 正式测试：insert_tube、pull_out_key 各seed 0–4一次，共10轮。开始测试后不再改工具/说明/阈值。
  与已完成原始深度基线比较；Astra基线为插管4/5、拔钥匙2/5。

## 工具制作与隔离

代码在 examples/univtac/develop_tools.py，复用原有Library、publish、Sandbox、
白名单传感导出和Codex SDK。生成代码只在无网络/无GPU的Docker沙箱中执行。
模型只看到开发任务的传感、实际动作和调用反馈；任务编号还会与实际存档配置交叉检查。
不会读取或提供测试任务的历史观测来制作工具。判分器和隐藏物体状态不属于工具输入。

每个开发运行确定性抽取三个时刻给maker，保留原始RGB像素，深度提供标明采样位置的数值摘要。
工具执行时拿到完整原始数组，最多四个最近记录帧；它不会获得maker采样之外的隐藏字段。
每版先做参数检查及各开发运行初始/末段的Docker回放，再在真实仿真中验证采用和结果。
无离线策略请求替代仿真；制作和评议是明确单独计费的程序生成请求。

图库只显示同名最新版本，实验目录和快照保留每版源码、输入、输出、回放与使用记录。
系统提示词不注入特定任务经验。新工具说明仅描述程序如何使用、测量含义与局限。

## 运行与留档

远程根目录：/home/zwy/work/embodied_harness/experiments/univtac-tool-development-20261102。
网页沿用 http://127.0.0.1:18093/console 和 /tools。

baseline-only阶段先运行三轮；完成后，托管的续接服务检查初始基线完整再进入五轮优化。
同一个脚本的resume-baseline只允许续接完整初始基线，不会重跑已完成开发轮或中途重复优化。
模型、预算、运行源码和Docker镜像与初始协议不符时停止。

记录包括protocol.json、status.json、各组results/score、每次maker和assessment的SDK事件/usage、
candidate.json、replay.json、history.json、best.json、freeze.json、final.json，以及
research.md/research_log.md/autoresearch-results.tsv/progress.png。
网络/基础设施失败和生成程序失败分别保留；未经执行的候选不记为0/3任务能力。
token中缓存属于输入、推理属于输出，均不重复加算；制作成本与使用成本分开汇总。
没有账单不换算美元，不以这批小样本宣称普遍泛化或统计显著性。

## 验证与当前状态

- 定向UniVTAC+SDK：288 passed；最后的调用有效性/选择修订定向5 passed。
- 全仓：1828 passed、12 skipped、2项已存在失败（旧腕部定位门槛、旧pilot maker/freeze检查）。
- pre-commit全仓通过。远程独立的SDK timeout实现保留，仅补充reasoning_effort可选参数；旧调用默认low不变。
- 首轮开发基线：fa19bfdfb6ebfb2c2895，任务0/seed0，真实仿真已进入模型调用。
- 尚未生成或发布本批候选，未得到本批工具增益结论。

- 工具调用错误单独计数，不算有效采用；发布时保存上一版本差异与实际来源实验。


## 第一版制作记录

开发基线已3/3成功，平均403.17秒、输入加输出906258 token。
第一版sensor_modal_evidence由Astra high生成，源码336行，制作240.48秒，
输入235525、输出7074 token（其中推理1552，已包含在输出中）。
版本95fa278251b44a64017d4e8134d5886babe80fb61d23b34b152a10a7ad5eeef2。
六个开发窗口回放执行通过，已发布到原工具库，正在任务0三轮真实仿真验证。
功能包括空间匹配/去重marker后的时序变化、双指证据、实测手部运动和深度摘要；
尚未证明成功率或token增益，也未验证maker声称的排列不变性等所有性质。
源码与小型制作摘要在validation/univtac-tool-development-20261102/iteration-1。
