# P3：固定流程的最小任务闭环

## 目标和前置条件

不依赖 LLM，完成“观察椅子 → 生成附近可达停车位 → 导航 → 重新观察确认”。P1/P2 硬件门槛已通过；使用冻结地图和受控场地。

这一步构建后续 Agent 复用的确定性执行器和成功判据。椅子可在起始视野内，或从明确指定的已验收观察点看到；不要求自主探索。

## 按顺序执行

1. **P3.1 固定任务状态机**：实现 ACCEPTED/OBSERVING/PLANNING/NAVIGATING/VERIFYING/终态；task_id 贯穿导航、图像、memory 与事件。
2. **P3.2 目标选择**：优先用户明确指定的 object_id；“一把椅子”可按可达路径代价确定性排序。没有可靠观测时 capture；无候选则 TARGET_NOT_FOUND。
3. **P3.3 Goal sampler**：根据物体范围、footprint、相机视野与局部 costmap 生成候选；验证净空、阿克曼曲率/朝向和可达路径。可配置采样密度，但不会缩小真实 footprint。
4. **P3.4 执行前再查**：map/calibration/候选年龄/关键数据仍有效；不存在有效目标时 NO_SAFE_GOAL。动作通过 P1 API，下发之后只跟踪相同 operation。
5. **P3.5 终点核验**：Nav2 成功后确认静止，采集 arrival 时间之后的新 bundle，检查对象关联与末端距离。无法确认时最多 2 次静止复拍；P3 不新增复杂移动恢复。
6. **P3.6 失败与取消**：导航失败、目标缺失、校验失败、取消和超时各有明确终态；迟到回调不能把取消变成功，任何失败不留下继续运动的任务。
7. **P3.7 任务持久化与事件**：重启显示中断任务而非恢复运动；页面可看轨迹、目标、当前步骤、最终证据和停车入口。
8. **P3.8 验收**：生成冻结 trial manifest，覆盖至少3个起点和3个椅子位置组合，完成 10 次端到端和错误成功判定测试。

## 必须交付

- 固定执行器、goal sampler、verifier、Task API 和可读失败原因。
- 纯几何/状态机测试与真实闭环报告，候选拒绝原因可追溯。
- 成功结果包含到达位姿、arrival observation_id、目标关联依据和末端距离；失败结果保存同样可用的证据。
- 本阶段完全禁用 LLM API 也能完成验收，作为后续模型实验基线。

## 部署与验收

```bash
./scripts/project test --level unit
./scripts/project test --level integration --profile mock
./scripts/project accept --phase P3 --mode replay
./scripts/project up --profile robot-live
./scripts/project accept --phase P3 --mode hardware --session <session_id>
```

先按部署手册完成当前版本发布、已存在有效会话和 arm 检查。P3-GOAL～P3-RESTART 的样本与门槛见 [验收规范](../acceptance.md)。

首版默认 task timeout=300秒、navigation timeout=180秒、静止复拍≤2次。到达距离为 footprint 到物体外缘0.6～1.0m；不能用机器人中心到物体点的距离代替。

## 失败处理与退出条件

找不到附近可达停车位即失败；Nav2 成功但目标移走即校验失败；观察到不同椅子不得偷换任务目标。出现这些结果应改进几何/记忆/状态机，不让后续 LLM 用一句话掩盖。

P3 PASS 后提供：可供 Agent 调用的复合导航/核验工具，完整状态机与无需模型的对照基线。
