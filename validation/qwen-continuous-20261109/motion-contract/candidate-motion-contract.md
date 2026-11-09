# 只读草案：将纯搬运与夹爪指令分离

状态：未实施、未部署、未接入当前 C/E/T。先等本轮轨迹结束和图像审计，再决定是否值得实现其中一个方案。当前父代理观察到 C task 4 已抬杯后，在搬运调用中显式给出 `gripper=-1`；本文没有独立判定此前抓持是否稳固。E 已出现 `move_eef(..., gripper=+1)`，可能无需新增工具即可避免该错误。

2026-11-09 后续独立审计补充了两个直接接口错误，方案 B 的依据因此增强，但仍未实施：

- C task 4：已抓住并抬起物体，随后搬运调用显式 `gripper=-1`，物体掉落。
- E task 0：抓取、短提和搬运本来有效；req18 的 `robot0_eef_quat` 正确采用 xyzw，req19 在纯下降意图下把四个元素整个倒序传入 `move_eef`。错误目标要求约 2.8943 rad 旋转，实际转约 0.7165 rad（41.05°）；返回的 2.1804 rad 是**距错误目标的剩余误差**，不是实际转角。后续 `move_to` 保持的是已经改变的姿态。原接口与 SciPy 均为 xyzw，错误发生在模型重填参数。C task 0 使用 18 请求、约 281 秒成功，不能将此单例视为方案 B 效益证据。

两类错误都能由纯平移工具不接收 gripper/quaternion 来避免，但前提是模型实际调用该工具。E task 4 的未抓住即搬运是另一个根因，B 不解决它。

当前方案 B 的**精确四文件差异**见同目录 `candidate-translate-to.patch`，对应只读基线 hash 见 `candidate-translate-to-base-hashes.json`；这些是审批文件，尚未应用。它不触碰 `robots/libero/tools.py`、core planner 或 controller 参数。下面 B 的草稿以该 patch 为准。

## 判断与适用条件

这里的可证伪假设是：将手臂目标和夹爪开闭写在同一个动作调用里，使模型在连续搬运时重复填写一个本应保持的控制量，可能引入与位置目标无关的松爪错误。给纯平移一个不接收 `gripper` 的显式工具，可消除**该工具调用内部**误填 `-1` 的途径，但不能保证模型选它、不能证明物体抓牢，也不能防止模型在错误位置显式调用 `release`。

远程只读核实的 `robosuite/models/grippers/panda_gripper.py` 与 `robotiq_85_gripper.py` 均通过 `current_action + ... * sign(action)` 更新夹爪目标，因此 `0` 保留当前目标。它不冻结实测指间距离：接触、重力、滑移和原先未完成的闭合仍可能改变 qpos。适用范围限定于当前支持这种零输入语义的 LIBERO 夹爪与现有控制模式；未来不同夹爪需重新验证。

两种方案都保留原 `move_to`、`move_eef`、`set_gripper` 和 `release` 的接口与实现；不新增闭合判定或自动释放；不写任务坐标/固定轨迹经验；不修改控制增益、步长、总预算或原始默认选择。

## 方案 A：translate_eef，短步目标

新增工具只接受 `xyz, steps=5`。从调用时实测四元数固定本段姿态，用 `gripper=0` 调用现有 `move_eef`。沿用原来的每次 1–10 控制步及全部边界检查。

候选新增到 `robots/libero/eef_control.py` 的 `EefControl` 类；原 `move_eef` 不变：

```python
    @tool
    def translate_eef(
        self,
        xyz: Annotated[list[float], Field(min_length=3, max_length=3)],
        steps: Annotated[int, Field(ge=1, le=10, strict=True)] = 5,
    ) -> ToolResult:
        """Translate toward world XYZ metres, retaining measured orientation and gripper target.

        Execute 1..10 control steps (default 5), then inspect images and pose
        errors. Change fingers with set_gripper or release. Retained gripper
        target does not establish holding, arrival or collision clearance.
        """
        raw = self.primitives.env.raw_obs()
        result = self.move_eef(
            xyz,
            np.asarray(raw["robot0_eef_quat"]).tolist(),
            0.0,
            steps=steps,
        )
        result.data["name"] = "translate_eef"
        if not result.is_error:
            result.data["gripper_command"] = 0.0
        return result
```

优点：每段提供图像及实测误差，沿用已验证的控制器实时缩放，模型不再重复构造纯平移的四元数和夹爪参数。代价：短步可能要求更多模型往返；在 30 请求预算中，长距离搬运可能比现有 `move_to` 更难完成。不得把工具输出误差下降当作放置成功。

## 方案 B：translate_to，复用原 move_to 的闭环

优先考虑此方案作为 C task 4 那种错误的最小独立候选。工具仅接收 `xyz`，委托原 `move_to(xyz, gripper=0)`；`max_steps`、`step_clip`、`tol`、`action_scale` 和姿态控制全部使用原默认。它不增加每次动作步数，也不增加自动目标或路径规划。放置前仍由模型选择目标，放置后的开爪仍显式调用现有 `release`。

候选新增到同一 `EefControl` 类；仅复用类的工具注册，不依赖新增 controller RPC：

```python
    @tool
    def translate_to(
        self,
        xyz: Annotated[list[float], Field(min_length=3, max_length=3)],
    ) -> ToolResult:
        """Move toward world XYZ metres, preserving orientation and the gripper target.

        Uses unchanged move_to servo defaults. Split XY travel over 0.30 m into
        intermediate targets. Change fingers with set_gripper or release.
        Inspect returned images; preserved gripper target does not prove holding.
        """
        target = np.asarray(xyz, dtype=float)
        if target.shape != (3,) or not np.isfinite(target).all():
            raise ValueError("Supply three finite world XYZ coordinates")
        if self.primitives.env.terminated or self.primitives.env.truncated:
            return ToolResult(data={"error": "Environment episode ended"})
        result = self.primitives.move_to(target.tolist(), gripper=0.0)
        result.data["name"] = "translate_to"
        if not result.is_error:
            result.data["gripper_command"] = 0.0
        return result
```

优点：一步模型请求可完成原 `move_to` 的内部伺服，减少 30 请求预算下的往返；直接封住搬运时重填夹爪参数的错误，改动更少。代价：继承原 `move_to` 的路径限制、长距离/姿态风险与返回反馈粒度；不是新增避障器。`move_to` 当前文档要求较长平移拆分路径，该约束仍生效，包装不能绕开。下一版若该工具可单独选择而不暴露原 `move_to`，其说明必须完整保留该现有约束，而不能只引用另一个不可见工具。

精确 patch 已将原 0.30 m 分段约束保留在新工具说明中；这是原工具的现有控制接口限制，不是从某条任务轨迹提取的经验。新包装只增加自身输入的有限数/形状检查和已结束环境检查。`steps_used` 继续沿用原 `move_to` 的到位检查迭代数，可能比实际动作步数多一次；不顺手修原统计，审计时以实际执行/录像帧另核。

## 必要的注册与默认选择改动

只实施 A 或 B 中一个，不同时引入。以方案 B 为例，`robots/libero/research/manual.py` 当前只为 `move_eef` 注册绑定工具，应改为：

```diff
-        if any(t["name"] == "move_eef" for t in selected):
+        optional_moves = {t["name"] for t in selected} & {"move_eef", "translate_to"}
+        if optional_moves:
             from robots.libero.eef_control import EefControl
-            controller = self.primitives.env.get_eef_controller_state()
-            if "error" in controller:
-                raise ValueError(controller["error"])
-            definition = EefControl(self.primitives).move_eef
-            self.add_tool(
-                definition.with_handler(
-                    partial(self._execute_primitive, "move_eef", definition)
+            if "move_eef" in optional_moves:
+                controller = self.primitives.env.get_eef_controller_state()
+                if "error" in controller:
+                    raise ValueError(controller["error"])
+            control = EefControl(self.primitives)
+            for name in sorted(optional_moves):
+                definition = getattr(control, name)
+                self.add_tool(
+                    definition.with_handler(
+                        partial(self._execute_primitive, name, definition)
+                    )
                 )
-            )
```

方案 A 将这里的 `translate_to` 替换为 `translate_eef`，而 controller 检查仍对整个非空 `optional_moves` 执行；`robots/libero/robot_spec.py` 的 `_spawn_env_server` 还需将 `t["name"] == "move_eef"` 改为 `t["name"] in {"move_eef", "translate_eef"}`，使显式选 A 的独立环境启用既有反馈包装。方案 B 不改该启动门控，单独选择 B 不需要 EEF controller 包装。

`rpent/dashboard/workbench.py` 的 `native_catalog` 已遍历 `EefControl` 并按 owner 分类为 control，无需改动。**必须**在 `Workbench.selection(ids=None)` 中同时排除新增工具，避免自动改变原默认工具集。方案 B 为：

```diff
-                and not (self.robot == "libero" and t["name"] == "move_eef")
+                and not (
+                    self.robot == "libero"
+                    and t["name"] in {"move_eef", "translate_to"}
+                )
```

方案 A 将新增名字换成 `translate_eef`。

当前 `availability_prompt` 在选入 `move_eef` 后直接指示模型选择下一段 `move_eef`，可能削弱新工具使用。若要做“动作契约”独立候选，在新工具选中时将这一段替换为以下两句，旧条件与旧文本完全保留：

```text
Use translate_to for position-only moves while retaining the gripper target. Inspect returned images and pose; use an enabled gripper tool when the fingers must change.
```

方案 A 仅替换工具名。该两句属于候选的显式行为变化，需纳入冻结差异；不能同时扩写经验或加入额外抓取策略。也可首轮不改该段、只添加工具，但必须记录是否因旧提示而根本未调用新工具；不能把未调用下的成功率归因为新契约。

除上述源码外，扩充 `tests/unit_tests/robots/libero/test_eef_control.py`，并在 `docs/manual-workbench/libero-eef-control.md` 记录显式选择和边界。原 `robots/libero/tools.py` 不改。如实施，先在独立 checkout 验证，再以新冻结工作区用于下一条件；当前 C/E/T 的 live 源码不变。

## 可证伪检查

1. 行为契约：不同已有夹爪 target 下，候选工具每个控制步的 grip 输入均为 0，活动夹爪模型的内部 target 保持；原 `move_to(...,-1)`、`move_eef(...,-1)` 和 `release` 的原行为仍可独立使用。不能用恒定 qpos stub 代替目标保持测试。
2. 原动作预算：B 委托 `move_to` 后沿用其默认控制上限及步长，无隐藏第二次动作；A 恰好遵循原 1–10 控制步和取消/终止行为。使用同一起始状态和同一目标，对照原方法显式 `gripper=0` 的轨迹及反馈。只包装不应改变位置路径。
3. 注册：默认工具列表逐项不变；显式新工具能经 `ManualToolkit` 记录图像/反馈；未选择不能调用。B 单独选择不启动 controller 扩展，A 单独选择才启用。工具 schema 无 `gripper` 参数。
4. 用远程当前实际夹爪类做无物体的有限诊断，核对 command target 保持及 qpos反馈；这只证明指令隔离。此项若需要新仿真必须在当前 C/E/T 结束后、单独记录，不能冒充任务有效性。
5. 任务机制：冻结其他配置，对相同 task/seed 检查新工具实际调用率、搬运中的显式开爪事件、物体在图像中是否继续随 EEF 移动、错误释放位置、模型请求数与最终官方成功。若仍因误认抓住、几何目标错误、显式 release 或请求预算失败，则本候选没有解决这些根因；不要再把所有失败解释成夹爪参数问题。

建议：等本轮审计。若 E/T 已自然维持闭爪且失败转移至几何/抓取，暂不实施这个候选；若搬运时的开爪误参仍反复出现，先选 B，对现有长程伺服增加一个薄而明确的纯搬运接口，A 留作需要密集视觉反馈时的独立候选。

## B 的实施准备（等根代理明确 READY）

1. 先复核 patch 四个文件的基线 hash 与当前独立修改，逐块应用候选，绝不覆盖当前 C/E/T live source。只选 B，不同时加入 workflow W1 或新经验。
2. 在 `tests/unit_tests/robots/libero/test_eef_control.py` 扩充：不同初始姿态下，新包装与原 `move_to(..., gripper=0)` 的逐步动作、终态和预算一致；动作旋转分量为零且夹爪分量为零；xyz 非有限/长度错时零动作；原显式开爪动作不受影响；新 schema 仅含 xyz；新工具默认不选；仅选 B 不需 controller RPC/启动标志。保留原 steps_used 含检查迭代的断言，不把它改成动作计数。
3. 在 `tests/unit_tests/robots/libero/research/test_manual.py` 增加显式 B 注册和动作后图像/状态记录检查，验证无 controller RPC 的旧原语环境也可使用；同时选 B 与 move_eef 时，move_eef 原校验仍生效。只选原工具时 prompt 文本和行为保持。
4. 远程隔离 checkout 跑相应定向、完整 unit suite 和 scoped pre-commit。通过后，另做不调用模型的有限 controller 诊断，核实实际活动夹爪在输入 0 时 command target 保持；不得把实测 qpos 不完全恒定判成指令改变。是否进行新仿真由根代理按当前实验空闲与已获授权范围安排。
5. 新条件只增加 B 和上述选中时两句动作引导，记录 B 实际采用、手动开爪/四元数重排错误是否消失、仍存抓持/几何问题、总请求与官方成功。冻结并保留原 30/600，不能把动作预算增加当作工具收益。
