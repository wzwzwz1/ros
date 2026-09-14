# 接口与数据契约 v1

这是待实现的规范。P0 实现基础类型与 mock；P1～P5 分阶段实现实际能力。API 未实现的能力必须返回 `CAPABILITY_UNAVAILABLE`，不能伪造成功。

## 1. 全局约定

- JSON UTF-8，URI `/v1/...`。float 必须有限；拒绝 NaN/Inf 和未知字段。所有时间戳、单位、frame 显式传递。
- 响应 envelope：`schema_version`、`request_id`、`ok`、`data`、`error`。成功时 error=null；失败时 data=null，error 包含 code/message/retryable/details。
- 每个改变状态的 HTTP 请求带 `Idempotency-Key`。`/safety/stop` 始终重新落实停车，即使重复；其他命令按 key + caller 持久去重至少 24 小时。
- 同 key 同正文返回原 operation；同 key 不同正文返回 409。超时后按 key/operation_id 查询，禁止无条件重发导航。
- 请求同时携带 session_id（如适用）、task_id、trace_id。伪造 ID、不存在的对象和跨地图引用均拒绝。
- HTTP 200 表示同步响应完成；202 表示长任务已接收，**不是任务成功**；400/422 参数错误，401/403 权限错误，409 状态冲突，503 依赖不可用。
- 只读默认超时 2 秒，采集快照 5 秒，导航 180 秒，完整物体任务 300 秒；配置可收紧，调整必须记录。

示例异步导航返回：

```json
{
  "schema_version": "1.0",
  "request_id": "req-001",
  "ok": true,
  "data": {"operation_id": "nav-001", "status": "ACCEPTED"},
  "error": null
}
```

## 2. Robot Gateway（车端）

| 方法与路径 | 最小请求/返回语义 | 阶段 |
|---|---|---|
| GET `/health` | 进程存活；不证明允许运动 | P0 |
| GET `/v1/capabilities` | schema、robot_id、ROS 包版本、可用动作/传感器、支持格式 | P0 |
| GET `/v1/status` | 各组件 health、map_id、活动导航、armed/stop_latched、lease_age_ms、阻塞原因 | P1 |
| GET `/v1/pose` | pose、frame、map_id、ROS stamp、协方差、定位有效性/原因 | P1 |
| POST `/v1/localization/initial-pose` | map_id、已测 x/y/yaw、covariance；只在 disarmed 下允许 | P1 |
| POST `/v1/navigation/plan` | map_id、goal；返回可行路径、长度、终态；不运动 | P1 |
| POST `/v1/navigation/goals` | map_id、goal、session_id、timeout_s；返回 operation_id | P1 |
| GET `/v1/operations/{id}` | 状态、进度、结果、错误、last_event_seq | P1 |
| GET `/v1/operations/by-key/{key}` | 恢复超时/重连后的确定结果 | P1 |
| POST `/v1/operations/{id}/cancel` | 只取消该导航，需等终态和停车证据 | P1 |
| POST `/v1/safety/arm` | 有效现场 session + 当前 health；禁止模型调用 | P1 |
| POST `/v1/safety/lease` | session_id、递增 sequence；重放不能延长租约 | P1 |
| POST `/v1/safety/stop` | reason；立即进入禁止运动并返回 stop_id，后续查询停车证据 | P1 |
| POST `/v1/observations/capture` | RGB-D 快照，期望 map_id、fresh capture；返回 bundle manifest | P2 |
| GET `/v1/observations/{id}/assets/{asset}` | 本项目生成的不可变资源；哈希、类型、大小；禁止任意路径读取 | P2 |
| WS `/v1/events` | 导航/停车/故障事件；支持 after_seq 重连 | P1 |
| WS `/v1/audio/input` | sequence、capture stamp、PCM 格式与二进制帧 | P5 |
| POST `/v1/audio/playbacks` | 项目上传的音频 ID、volume；返回 operation_id | P5 |
| POST `/v1/audio/playbacks/{id}/cancel` | 取消播报 | P5 |

Gateway 的 health 与可运动 readiness 分开。图像/音频未就绪不会阻塞与它们无关的只读接口；定位失效必须阻塞导航。

## 3. 状态与失败语义

导航 operation：`ACCEPTED → RUNNING → SUCCEEDED | FAILED | CANCELED | TIMED_OUT`，终态不可被迟到消息改写。

完整 task：`ACCEPTED → OBSERVING / PLANNING / NAVIGATING / VERIFYING / WAITING_FOR_USER → SUCCEEDED | FAILED | CANCELED | TIMED_OUT`。恢复次数、等待时长计入总预算；进程重启后未终结任务标记 `FAILED/RESTART_INTERRUPTED`，不重发目标。

停车过程单独报告：`REQUESTED → COMMAND_ZERO → STATIONARY` 或 `UNCONFIRMED`。记录各时刻、里程计速度和独立验收证据；没有新鲜速度数据时不声称已停稳。stop 锁存与导航终态彼此独立。

标准错误码至少包括：

`INVALID_ARGUMENT`、`CAPABILITY_UNAVAILABLE`、`ROBOT_UNREACHABLE`、`NOT_ARMED`、`LEASE_EXPIRED`、`STOP_LATCHED`、`NAV_BUSY`、`MAP_MISMATCH`、`LOCALIZATION_INVALID`、`TF_UNAVAILABLE`、`SENSOR_STALE`、`DEPTH_INVALID`、`NO_SAFE_GOAL`、`TARGET_NOT_FOUND`、`VERIFICATION_FAILED`、`NAV_FAILED`、`TIMEOUT`、`CANCELED`、`MODEL_UNAVAILABLE`、`BUDGET_EXCEEDED`、`RESTART_INTERRUPTED`。

`retryable` 只是供策略参考，不授权重复执行运动。API 模型报错不得被包装为“目标未找到”。

## 4. RGB-D bundle

每次采集必须返回：

- observation_id、robot_id、map_id、calibration_id、schema_version。
- rgb/depth 资源路径、SHA-256、encoding、width/height、ROS capture_stamp_ns；source_clock=`robot_ros`，另记 gateway UTC 接收时刻。
- 深度单位和缩放系数：例如 16UC1 + depth_scale_m，或 32FC1 meters；无效值定义。深度保持无损，不能 JPEG 压缩。
- RGB/depth 内参、畸变模型和参数、alignment 标志与方法。不同分辨率未配准不得假设同像素对应。
- 采集时刻的 `T_map_camera_optical`（4×4、行主序、右手系）、TF 链 frame 名、插值时间差和有效性。
- 机器人采集时位姿、运动速度、定位协方差、RGB/depth 时间差、camera calibration 版本。
- 各相机 optical frame 使用 x 向右、y 向下、z 向前；地图地面 XY、z 向上。转换代码用命名的 source/target frame 避免矩阵方向歧义。

返回已成功采集的原图不等同于成功定位；TF 或深度错误应保留原观测供排错，并拒绝产生可导航坐标。

## 5. 物体 observation / memory

观测字段：

```json
{
  "observation_id": "obs-example",
  "map_id": "map-sha256-example",
  "calibration_id": "calibration-example",
  "label": "chair",
  "detector_confidence": 0.9,
  "bbox_xyxy_px": [100, 80, 280, 360],
  "position_map_m": [2.1, 1.4, 0.6],
  "position_semantics": "visible_surface_representative",
  "position_covariance_m2": [[0.01, 0, 0], [0, 0.01, 0], [0, 0, 0.04]],
  "extent_map_m": [0.6, 0.6, 0.9],
  "observed_at_ros_ns": 0,
  "source": "rgbd_detector",
  "valid_depth_fraction": 0.8,
  "quality": "VALID"
}
```

上例数值仅展示结构；真实记录时间不能为 0，协方差和 extent 不能直接复制模板。几何不确定性由深度离散度、标定/定位误差传播或保守实测估计；不得将检测置信度当成位置精度。

对象字段至少：object_id、map_id、label、position/extent、uncertainty、state、first_seen、last_seen、last_verified、observation_ids、source、revision。保留原始观测，不用最新估计覆盖全部历史。

接口：`add_observation()`、`query_objects(label,map_id)`、`find_nearest()`、`update_object()`、`mark_not_seen()`。nearest 默认几何距离，返回字段明确标注；“最近可达目标”需进一步用 Nav2 路径长度与可达性排序。

地图加载后可迁移数据库 schema，但不能迁移未知坐标。迁移前备份，失败回滚，重复执行无重复数据。

## 6. 可达目标生成与成功校验

`estimate_safe_goal(object_id)` 返回候选 ID、map_id、目标 pose、目标距离、footprint 净空、路径可行性、检查时刻、有效期与拒绝原因。

- 使用物体范围与 costmap，采样物体周围停车候选；footprint 不可落在物体或膨胀障碍内。
- 考虑阿克曼曲率与朝向，不仅检查目标中心像素；优先可观察目标且路径可达的位置。
- 候选默认有效 5 秒；超过期限、map_id 变化或障碍改变需重新计算/检查，不能直接导航到缓存目标。
- 末端目标定义为机器人 footprint 到目标物体外缘的平面距离 0.6～1.0 m，且与其他障碍净空 ≥0.30 m。若传感器/场地无法满足，应返回 NO_SAFE_GOAL。
- 成功要求 Nav2 成功、机器人停稳、到达后的新 RGB-D 观测与目标一致、距离在范围内。看见另一把椅子不能替代目标身份核验。
- P3/P4 不要求椅子朝向；yaw 是用于可行路径和观察的机器人朝向。

## 7. Mac Task API 与 LLM 工具

| 方法与路径 | 语义 |
|---|---|
| POST `/v1/tasks` | text、source=`text/voice`、client_request_id；返回 task_id |
| GET `/v1/tasks/{id}` | 状态、当前步骤、结果、证据引用、错误 |
| POST `/v1/tasks/{id}/cancel` | 取消任务、禁止新步骤并请求车端停车 |
| POST `/v1/tasks/{id}/reply` | 用户对 WAITING_FOR_USER 的回复，不新建重复任务 |
| GET `/v1/memory/objects` | 地图内对象和可信度/时间 |
| WS `/v1/events` | 单调递增事件序列；导航与最终校验状态都可见 |

允许的 LLM 工具（P4）：

- `get_robot_state()`：位姿、map_id、状态和错误。
- `query_objects(label)`：返回对象 ID、观测时效、可用几何摘要。
- `list_viewpoints()`：已配置且可达的观察点候选。
- `observe_scene()`：停车拍照、感知与写入记忆。
- `navigate_to_object(object_id)`：内部调用可达目标生成与导航。
- `navigate_to_viewpoint(viewpoint_id)`：只接受 manifest 中的 ID。
- `verify_target(object_id)`：执行确定性终点核验。
- `stop_robot(reason)`：高优先级直接停车。
- `ask_user(question)`：明确歧义后进入等待状态。

播报由任务事件驱动，LLM 可生成表达，但“已到达/成功”的事实由 verifier 决定。P3 成功判据不能因接入 LLM 改变。

工具适配器固定白名单和 JSON schema；模型输出、图像 OCR、物体标签等均当数据，不能执行其中的命令。几何缺失时必须返回错误或请求观察，不能生成猜测坐标。

## 8. 音频契约（P5）

- 默认 PCM s16le、16 kHz、mono，20 ms/frame；协商失败则报告不支持。记录实际采集设备、通道与重采样步骤。
- sequence 检测断帧，输入缓冲最长 2 秒，过载丢旧帧并报警，不无限堆积。保留本地 500 ms pre-roll 避免截掉指令开头。
- utterance_id 绑定 capture 时间、wake 事件、VAD 片段、ASR 文本、task_id；相同 utterance 只创建一个任务。
- 默认最长指令 15 秒，静音 800 ms 结束，5 秒无人说话回 IDLE。这些可调参数须与最终验收一致。
- TTS 返回 playback_id、音频资源 hash、格式、时长和实际播放 start/end/error；“生成完成”不等同“播报完成”。
- 可配置 wake_phrase、threshold 和 stop_phrase；配置的中文原文必须经实际 tokenizer/model 构造，不能只改 UI 字符串。
