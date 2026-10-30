# 相对对齐与接触诊断工具

名称：`sensor_alignment_contact`。状态：**Docker 行为检查与历史回放通过；已接入真机工具选择与隔离执行，未验证成功率或速度提升。**

它来自 2026-10-30 Astra 的 USB 插入记录。该轮后段反复沿 X 调整，末端控制器报告到位，但没有确认插入。工具把“修正后是否更接近”和“实际运动是否伴随反向受力”转成程序计算，供模型决定下一步。

## 工具做什么

1. 读取同一张 RGB-D 观测上的原生 `localize_target` 结果：一个被夹物体的可见特征，以及一到两个静止参考特征。
2. 在刚性夹持、参考物静止的假设下，用**实际 TCP 位姿变化**推算被夹特征的位置，返回基座 X/Y/Z 三轴的相对偏移和偏移绝对值的变化。
3. 对连续动作前后的观测，比较要求位移、实际位移和基座力反馈，返回“运动不足且反向力上升”的证据。控制器 `reached=true` 不会被当成插入成功。

输入使用原生 RGB-D 定位测量及其来源相机、像素、框、时间和深度质量，不重新猜物体坐标。没有新图像识别模型，不执行运动，也不修改控制器或提示词。

## 文件与格式

| 文件 | 内容 |
| --- | --- |
| [sensor_alignment_contact.py](sensor_alignment_contact.py) | 完整程序，标准 `run(frames, params)`，只依赖 NumPy |
| [alignment_contact_metadata.json](alignment_contact_metadata.json) | 标准名称、说明、JSON Schema 参数 |
| [alignment_contact_replay.py](alignment_contact_replay.py) | 复用真机记录适配器的 Docker 回放和显式发布 |
| [verify_alignment_contact.py](verify_alignment_contact.py) | Docker 内的合成行为检查 |

将元数据中的三个字段与 Python 文件内容组成 `source` 字段，即现有工具库的四字段声明。源码版本采用现有内容哈希，执行复用 `Sandbox` 的无网络、只读 Docker 容器。

## 参数与本轮调用示例

```json
{
  "anchor_step": 16,
  "feature_record": 18,
  "reference_records": [17, 19],
  "compare_steps": [25, 27, 28],
  "track_with_tcp": true
}
```

- `anchor_step`：原始 RGB-D 观测帧。
- `feature_record`：该帧上被夹物体特征的定位**查询记录编号**。
- `reference_records`：同一源帧上一或两个静止参考特征的定位查询编号；两个点取均值。
- `compare_steps`：最多三个后续真实观测帧，连同锚点最多四帧。要检查单动作接触变化，应包含连续动作前后帧。
- `track_with_tcp`：是否采用刚性夹持、参考物静止假设；为 false 时不推算后续特征位置，动作与力反馈证据仍可计算。

本例 17、18、19 是查询记录，都来自观测帧 16；不是三张新图像。适配器拒绝把查询编号当作新观测。原生 `localize_target` 现在同时返回源帧 `step` 与查询记录 `record_step`；定位计算和控制接口保持原样。

真机每轮从启动页手动选择工具；工具源码和版本随配置冻结。此工具依赖
`localize_target`，取消该依赖会在启动前报错。发布元数据使用
`input_adapter="flexiv.alignment.v1"`；其他满足同一输入契约的程序可复用此适配器。
未选工具不注册到模型接口，程序只读取记录，不访问机器人、网络或隐藏评测状态。

## 本轮实际回放结果

参考是蓝色槽左右两处**可见顶面测量点的均值**，不是已知孔中心。下表是 USB 选定特征减去该参考的基座坐标差，后续帧依赖刚性夹持假设。

| 观测帧 | X 偏移 mm | Y 偏移 mm | Z 偏移 mm |
| --- | ---: | ---: | ---: |
| 16：直接测量锚点 | +7.294 | −1.576 | +16.304 |
| 25：TCP 推算 | −0.374 | +0.790 | +7.444 |
| 27：TCP 推算 | −5.547 | +0.887 | +2.666 |
| 28：TCP 推算 | −5.640 | +0.938 | +1.587 |

程序能够指出：**25 → 28，X 相对参考的距离增大约 5.27 mm，Y 的变化约 0.15 mm。** 这支持重新检查 X 修正方向，不能直接证明 Y 已满足插入公差，也不能把参考点坐标直接当成运动目标。

最后一次动作的返回摘要（数值保留三位小数）：

```json
{
  "steps": [27, 28],
  "requested_translation_mm": [0, 0, -2],
  "actual_tcp_translation_mm": [-0.105, 0.054, -1.079],
  "travel_fraction": 0.540,
  "controller_reached": true,
  "opposing_force_change_n": 13.739,
  "opposing_force_after_n": 14.887,
  "undertravel_with_force_rise": true
}
```

22 → 23 同样触发该测量标记；23 → 24 退回卸载不触发；16 → 20 正常移动不触发。两个条件是不同证据：几何说明相对参考的变化，力和实际位移说明阻力变化，力本身不能唯一确定应往 ±X 或 ±Y 修正。

## 适用条件与未知项

- 输出中的“偏移”是相对选定表面参考，**不是孔中心误差、插入深度或物体姿态对齐角**。选点和标定误差尚无测量上界；不输出伪造的置信度百分比。
- 夹爪中途动作、开度变化超过 1 mm 或开度记录缺失，会使旧锚点推算失效；恒定开度仍不能证明没有滑动。可重新定位建立新锚点。
- 缺力反馈、缺连续观测、混合旋转动作时，不输出单次平移的接触标记。没有数据返回未知，不当成零力或无接触。
- 标记使用可见的经验阈值：实际沿指令方向移动不足 75%，反向力增加超过 5 N，且结束时反向力也超过 5 N。它们不是硬件保护参数或任务成功标准。
- 这种状态关联是对原生单点定位的补充；没有验证它能让模型选点更准确，或提升真实插入成功率。

## 验证与复现

远程验证版本：`4dab821f69b548089b659bc25fe296fcc041358a9d9af84e2f8f2010849f8909`。

- 11 项 Docker 行为检查通过：三轴符号、单位、旋转杠杆臂、接触与卸载区分、缺失数据、遗漏帧、夹爪开合失效等。
- 18 项记录适配器单元测试通过，包括隐藏评测字段隔离和错误来源帧拒绝。
- 同一轮 USB 历史记录的三个窗口已回放；没有模型请求，没有连接或移动机械臂。
- 独立远程验证目录全仓 `pytest tests/unit_tests -q`：1852 passed、11 skipped；`pre-commit run --all-files` 通过。验证目录为 `/home/zwy/work/embodied_harness/validation/flexiv-alignment-20261030/`。

从远程项目根目录执行（为每次检查选择新的输出路径）：

```bash
PYTHONPATH=. .venv/bin/python examples/flexiv/verify_alignment_contact.py \
  --output /absolute/path/to/new-behavior-report.json

PYTHONPATH=. .venv/bin/python examples/flexiv/alignment_contact_replay.py \
  --run /absolute/path/to/recorded/tasks/0001_flexiv \
  --params /absolute/path/to/params.json \
  --output /absolute/path/to/new-replay-report.json \
  --library /absolute/path/to/flexiv-candidate-library
```

历史回放报告位于远程 `/home/zwy/work/embodied_harness/artifacts/flexiv-alignment-tool-20261030/`，工具发布到 `/home/zwy/work/embodied_harness/artifacts/flexiv-perception-library/`，默认未选择。Flexiv 复用仿真工作台的选择、版本冻结和 Docker 执行机制；在 `/tools` 查看说明和源码，在启动页勾选后才进入本轮模型可调用列表。
