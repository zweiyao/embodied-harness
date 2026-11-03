# Flexiv 双视角定位

2026-10-31，移除 `localize_target` 在 provisional 控制会话中按相机名称拒绝腕部查询的逻辑。该工具仍是只读测量，不执行运动；图像帧号、标定对应、实测深度、像素范围及深度不连续检查保留。

## 原因与修改

实际使用的 RDK 系统提示词原本没有“腕部只能观察”要求。拒绝来自 `robots/flexiv/toolkit.py`：motion_enabled、calibration_provisional 为真且腕部未获得绑定文件的现场确认时，工具直接报错。旧 native 提示词有相同限制，观测还返回 control_camera=side；工具说明却允许选择 wrist 或 side。第二轮 USB 的两次腕部查询因此失败。

现在 RDK、EEF 及 native 模式的感知说明统一为：两个视角都可定位，选择特征可见更清楚、深度有效的视角；两视角不一致时交叉检查。标定检查描述不确定性，不是相机选择限制；图像清楚本身不代表三维精度。观测 control_camera=null，不再指定一个必用相机。

board-03 的 wrist_passed=false、side_passed=true 及其哈希保持原样，没有伪造现场确认或测量精度。已有 operator-confirmed 参数继续保存确认来源，不再作为腕部只读查询的前置条件。原有标定加载条件、动作授权、工作区、速度、故障处理与控制器未变；本轮未改经验库或启动新实验。

## 验证与部署

独立远程目录 `reviews/flexiv-dual-view-20261031`：真机模块 255 passed/1 skipped，全仓 1957 passed/14 skipped，pre-commit 通过。回归覆盖未现场确认/已确认、side/wrist 两视角均返回测量，以及失败标定标志保持、motion_authorized=false。

核对运行源码与修改前基线一致后，备份并同步五个 Python 文件；仅重启 Flexiv env 和 dashboard。RDK 与相机服务未重启。实读运行观测得到 control_camera=null、原始标定哈希不变、双相机与左指图像齐全，配置与重启前逐项一致。硬件 IDLE、armed=false、无故障。本轮未实测新接口能否提高抓取或插入成功率。

证据及原文件备份：`/home/zwy/work/embodied_harness/validation/flexiv-dual-view-20261031/`。
