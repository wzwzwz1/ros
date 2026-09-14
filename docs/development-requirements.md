# 开发要求与执行约定

版本：1.0，2026-09-14。本文的数值是首版工程验收目标，除明确标注的历史实测外，均不是已测性能。

## 1. 范围与部署位置

| 位置 | 必需职责 | 首版不承担 |
|---|---|---|
| Wheeltec | ROS Humble、驱动、定位/Nav2、Robot Gateway、独立运动监督、音频采集/播放 | LLM、大型 VLM、数据库主副本 |
| Mac M4 / 16 GB | Agent 编排、SQLite、目标检测、RGB-D 后处理、语音、调试界面 | Linux ROS 运行环境的替代 |
| DeepSeek API | P4 起的文本任务规划与工具选择 | 连续速度控制、最终停车或成功裁决 |
| 64 GB RAM 服务器 | 可选数据备份、回放评测；确认 GPU 后再选推理服务 | P0～P5 必需依赖 |

首版只承诺平坦单层、已建图、实验人员在场的室内场地。椅子“附近”是几何可达停车区域；“椅子前面”、无地图探索、任意物体识别、多人跟随、楼梯、全双工语音属于后续扩展。

## 2. 工程布局（P0 起实现）

```text
ros/
├── README.md / AGENTS.md / docs/
├── pyproject.toml / uv.lock
├── src/spatial_agent/
│   ├── api/             # Mac HTTP / 事件 / 最小调试页
│   ├── gateway_client/  # mock、replay、hardware 适配
│   ├── memory/
│   ├── perception/
│   ├── tasks/           # P3 固定状态机
│   ├── planner/         # P4 DeepSeek adapter
│   └── voice/           # P5
├── ros2_ws/src/
│   ├── robot_skills/
│   ├── robot_gateway/
│   └── robot_safety/    # 独立于 Gateway 进程
├── configs/             # 可提交示例；local/ 为私有配置
├── deploy/              # 项目专用 service 和打包清单
├── scripts/project
├── tests/{unit,integration,acceptance}/
├── datasets/            # 本地数据，默认忽略，仅提交 manifest
└── artifacts/           # 日志、录包、报告，默认忽略
```

避免过早建立多个独立数据库、消息中间件或微服务。Mac 可用一个应用进程加按需模型工作进程；车端安全监督必须独立于 Web/模型调用。

## 3. 环境与依赖

- Mac：优先 Python 3.11、uv 独立环境；P0 实测依赖轮子与 macOS/ARM64 兼容并锁定。不修改系统 Python。
- 车端：ROS Humble 自带 Python 3.10；使用系统 ROS 环境与独立 overlay。需要 pip 依赖时用兼容的 `--system-site-packages` venv，禁止全局升级 rclpy/NumPy 破坏厂商包。
- 首版纯 Python 共用协议代码兼容 Python 3.10；Mac 的 MLX 等可选依赖单独分组。不要向车端同步 Mac venv、二进制或 wheel。
- 使用 Pydantic 验证所有外部输入，SQLite 保存任务与记忆；测试用 pytest，风格/静态检查选用 ruff 等轻量工具。
- 车端用 colcon 构建项目包，保存 apt 包版本、ROS 包来源、pip 锁文件和构建日志。编译/版本异常应固定单个依赖，不直接升级 OS/ROS。
- 模型采用显式 model_id、revision、来源 URL、SHA-256、精度、运行时、许可记录。下载缓存不进 Git，默认不远程执行模型仓库任意代码。
- 版本记录参考 [模型锁模板](templates/models-lock.example.json)。含空值或 example_only 的模板不是已下载、已验证模型清单。
- 依赖和模型版本在首次实际安装时解析并锁定；不得把文档日期当作实际验证过的版本号。

## 4. 配置要求

用 `configs/local/runtime.json`（不提交）覆盖可提交的默认配置；模板见 [运行配置](templates/runtime.example.json)。

- 启动时严格校验。缺少 map_id、frame、标定、运动会话或模型文件时，只降级相关能力；不得以假值补齐。
- 明确区分 mock / replay / hardware，禁止运行时悄悄回退到 mock。回放不能向硬件发送目标。
- `DEEPSEEK_API_KEY` 只存在 Mac 环境；SSH 凭据沿用用户已有设置。不要把原连接说明中的密码复制到新配置。
- API 模型名称可配置。P4 首次部署从官方可用列表验证模型与工具能力后锁定，禁止静默切换模型。
- 模型推理、RPC、导航和完整任务分别有超时；网络重试不会重复执行运动。超时计时使用 monotonic clock。
- 所有距离 m、角度 rad、时间戳明确时钟域；UTC 用于日志，ROS stamp 用于 TF，monotonic 用于本机超时。

## 5. 首版资源目标

这些是**验收预算**，不是预估占用或硬件性能承诺。超过预算须说明、优化或调整运行方式，再重新验收。

| 指标 | 默认目标 | 测法 |
|---|---|---|
| Mac 项目进程树峰值 RSS 总和 | ≤ 8 GiB | 1 秒采样；同时另报系统 memory pressure、Metal/MLX 分配，避免把共享内存重复相加当物理总量 |
| Mac 系统 swap 增量 | 30 分钟验收内 ≤ 512 MiB，memory pressure 不持续进入红色 | 用同一工具记录基线/峰值；记录其他运行应用 |
| 车端 MemAvailable | 全链路运行时 ≥ 512 MiB | `/proc/meminfo` 1 秒采样 |
| 车端存储剩余 | ≥ 5 GiB | 部署前后及录包期间检查 |
| 车端 CPU | 60 秒平均 ≤ 总算力 80%，无持续传感器掉频 | 按 CPU 核数归一化，附 odom/scan 统计 |
| 任务事件到 Mac 页面 | p95 ≤ 1 秒 | 本机时间记录接收与呈现 |
| 大模型调用 | 单任务最多 8 次、总工具调用最多 20 次 | 本地计数器强制执行；人工追问新 turn 延续同任务预算 |
| API token | 单任务累计输入 ≤ 40,000、输出 ≤ 4,000 | 发送前预估、返回后 usage 计数；超过预算停止新增调用 |

API 费用按实际返回 token 和当时价格写报告；预算可由用户配置，默认不增加购买或自动充值。可用缓存/摘要减少输入，但不丢弃失败状态与关键几何依据。

首版不同时常驻多个 LLM/VLM。默认使用本地轻量语音与检测，LLM 用 API；可选 Qwen3.5-4B 量化作为单独实验 profile，不能影响主验收。

## 6. 开发、测试与交付要求

每个功能依次做：契约 → 最小实现 → 失败路径 → 离线测试 → 部署演练 → 对应硬件验收。

- 日志为 JSONL，包含 trace_id、task_id、operation_id、组件、事件、错误码、版本和配置哈希；网络凭据、完整 Authorization header 不进入日志。
- 状态与记忆写入使用事务；重复请求无重复副作用；断电重启后保留记录，但旧运动任务禁止自动继续。
- mock 验证状态机、错误和调用边界；replay 验证真实传感器数据的感知结果；hardware 验证实车性能。三者互不替代。
- 改变行为要覆盖正常、超时、取消、重复请求和依赖失效中的相关路径；不为文档或简单值搬运添加无意义单测。
- 部署前生成文件清单、目标路径、配置差异、重启服务和回滚目标；只修改项目拥有的资源。
- 各阶段必须提供一个可重复的验收入口，产出 [报告模板](templates/acceptance-report.example.json) 对应格式及可读总结。
- 必需用例、样本数和阈值在执行前锁定。不能在看完结果后删失败样本、减样本数或降低阈值。
- 冻结输入参考 [suite 模板](templates/suite-manifest.example.json)。模板只演示单个 case；执行器必须根据阶段规范补齐所有必需 case 和真实 trial，不能把空 trials 判成通过。
- 阈值确需改变时，写决策记录说明场地/物理约束和影响，保留旧结果；新版本另起全套验收，未重新通过前仍不算 PASS。

## 7. 完成定义

一个阶段完成必须同时满足：

1. 本阶段所有要求已实现，接口与 CLI 文档同步。
2. 代码版本、部署版本、配置、模型和地图能复现。
3. 必需离线测试通过。
4. 必需硬件/API/声学用例按指定模式完成；缺失记 BLOCKED/NOT_RUN。
5. 所有可靠性与停车类用例通过，统计类指标达到门槛。
6. 报告附原始证据、失败样本、计算方法与回滚记录。
7. 进度文件指向本次验收报告，明确下一阶段入口。
