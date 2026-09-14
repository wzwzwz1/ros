# P0：工程与环境准备

## 目标和前置条件

建立可复现工程、mock 开发环境和真实设备清单，为 P1 提供可靠输入。需要项目目录读写权限；机器人离线时仍可完成本地部分。

输入：[开发要求](../development-requirements.md)、[架构](../architecture.md)、[部署手册](../deployment-runbook.md)、历史实测文档。不要把硬件规格的历史记录标为本轮实测。

## 按顺序执行

1. **P0.1 盘点与建库**：检查当前代码/Git/用户修改，建立开发要求中的布局、忽略规则和版本标识。保留原文档。`src`、tests 和命令实现按需要建立，不制造空包假装功能完成。
2. **P0.2 本地环境**：实测 M4/macOS/Python，选定 Python 3.11 环境，锁定 FastAPI/Pydantic/httpx/pytest 等基础依赖。模型依赖分 perception/voice/optional-vlm，基础安装不下载所有模型。
3. **P0.3 命令入口**：实现 bootstrap、doctor、config validate、test、up(mock)、status、down、accept/report。未来命令未实现返回退出码 4，并列出所属阶段。
4. **P0.4 协议与模拟器**：实现 v1 类型和 error envelope；mock gateway 可模拟导航反馈、超时、断流、拒绝和取消。所有返回注明 source=mock，并在连接层禁止 mock profile 连接真实目标。
5. **P0.5 只读机器人盘点**：按部署手册采集设备、ROS 包、实际参数、控制路径、TF、时间和网络；记录 topic 的类型与 QoS，不只记名称。只读命令失败也保存结果。
6. **P0.6 关键未知项**：列出轴距/车宽/footprint、最小转弯半径、停车机制、可用地图、Nav2 当前插件、RGB-D 标定/对齐、麦克风原始PCM入口。注明谁/哪阶段测量，未确认值保持 null。
7. **P0.7 地图/现场资料格式**：实现 map manifest、session 文件和 suite manifest 的验证器；格式可验证，但实际地图与现场确认由后续真实数据填写。
8. **P0.8 报告**：实现报告完整性检查，覆盖缺证据不能PASS。用两次独立启动验证幂等，更新进度。

## 必须交付

- 可运行 mock 工程、依赖锁、`.gitignore`、CLI help。
- 脱敏的 `artifacts/inventory/<run_id>/`，包含 Mac/robot 环境与未知项。
- 项目配置验证器与示例；`models.lock.json` 的结构（未下载模型不得写假的 SHA）。
- 文档生成器/验收报告生成器的最小实现，以及对应行为测试。
- 第一份 P0 报告；用户没有给服务器 GPU 不阻塞本阶段。

## 部署与验收

实现命令后执行：

```bash
./scripts/project bootstrap --target mac
./scripts/project doctor --target mac
./scripts/project doctor --target robot --read-only
./scripts/project config validate --file configs/local/runtime.json
./scripts/project test --level unit
./scripts/project test --level integration --profile mock
./scripts/project up --profile mock
./scripts/project accept --phase P0 --mode mock
./scripts/project down
```

只读盘点是单独证据，不能被 `accept --mode mock` 生成。P0 的 `run_status` 可显示 mock 通过；`phase_gate_status` 必须引用 P0-ENV 的 hardware 只读证据后才能 PASS。详细用例 P0-ENV～P0-REPORT 见 [验收规范](../acceptance.md)。

## 失败处理与下一阶段

- 无机器人：P0 本地可完成；P0-ENV=BLOCKED，继续做 P1 mock 的独立实现。
- 无 API 凭据：不阻塞 P0～P3；P4 api-live 暂不可执行。
- 发现实际车型/传感器与文档不一致：保留证据，修正配置与受影响计划。
- P0 不开展地面运动、不改系统网络、不部署 Nav2 新控制配置。

进入 P1 的必要输入：可复现工程、真实机器人身份/软件清单、网络链路、当前控制链和关键未知项列表。
