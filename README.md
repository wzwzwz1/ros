# Wheeltec Spatial Agent

基于 Wheeltec Mini AKM 的室内空间理解与导航 Agent。目标是通过物体感知、空间记忆、主动观察和导航完成任务，并逐步加入中文语音与自定义唤醒词。

## 当前状态

- 2026-09-14：完成开发与验收规范设计；本目录目前是文档仓库，**尚未实现本文描述的程序、CLI 或部署脚本**。
- 主机：Apple M4，16 GB 统一内存；服务器：64 GB RAM，CPU/GPU/显存待确认。
- 机器人：ROS 2 Humble / Ubuntu 22.04 / ARM64 / 4 GB RAM，Mini AKM 阿克曼底盘。
- 历史交接记录已验证底盘、雷达、Cartographer 建图；这些记录不等同于本项目阶段验收。
- 本轮任务仅编写文档，没有连接机器人、安装模型、调用付费推理、部署服务或让小车运动。

## 已确定的产品范围

首个闭环：**在已建图、平坦、受控的室内场地，找到一把椅子，停在附近可达位置，并重新观察确认。**

开发顺序：

| 阶段 | 结果 | 执行文档 |
|---|---|---|
| P0 准备 | 建立工程、采集环境证据、明确连接与运行配置 | [P0](docs/phases/P0-foundation.md) |
| P1 基础导航 | 加载地图、定位、到点、取消、停车、断网处置 | [P1](docs/phases/P1-navigation.md) |
| P2 物体定位 | RGB-D 检测、地图坐标、轻量物体记忆 | [P2](docs/phases/P2-perception.md) |
| P3 最小任务闭环 | 固定流程完成“找椅子并停在附近” | [P3](docs/phases/P3-task-loop.md) |
| P4 空间 Agent | DeepSeek 规划、记忆查询、选择观察点、有限恢复 | [P4](docs/phases/P4-agent.md) |
| P5 语音 | 自定义唤醒、中文指令、播报、统一任务入口 | [P5](docs/phases/P5-voice.md) |

阶段的硬件验收按 P0 → P1 → P2 → P3 → P4 → P5 执行。前阶段硬件暂不可用时，可以继续独立的离线开发，但不能宣布后续实车阶段通过。

## 给执行 Agent 的入口

依次读取：

1. [AGENTS.md](AGENTS.md)：如何执行、如何报告状态。
2. [开发要求](docs/development-requirements.md)：工程、资源、配置、测试与完成定义。
3. [架构与选型](docs/architecture.md)：车端、Mac、API 和服务器分工。
4. [接口与数据契约](docs/interface-contracts.md)：实现之间必须保持一致的约定。
5. [当前进度](docs/progress.md) 和 [机器可读状态](docs/phase-status.json)。
6. 当前阶段文档，以及共用的 [部署手册](docs/deployment-runbook.md)、[验收规范](docs/acceptance.md)。

后续可向 Agent 下达：

> 按本仓库 AGENTS.md 和阶段文档，从第一个未完成阶段开始开发、部署和验收。先读取实际进度和已有证据；自动完成已授权、条件具备的工作。缺少实车或现场条件时完成可独立进行的离线工作，明确列出剩余条件，不能把模拟结果标成实车通过。

## 运行方式

规范要求 P0 实现统一入口 `./scripts/project`。现阶段该文件不存在；文档中的这一类命令是**待实现的命令契约**，不能声称已经运行成功。实现后，入口必须提供 `--help`、清晰错误和结构化报告。

默认开发模式为 `mock`，不会连接真实机器人。硬件访问和实车运动使用独立运行配置；详见部署手册。

## 资料与规范的关系

以下三份文件保留为历史背景，不作为自动执行脚本：

- [原交接文档](wheeltec_spatial_agent_handoff.md)
- [小车实测概况](wheeltec-robot-overview.md)
- [原连接说明](wheeltec-ssh-connect.md)

当前开发以本套阶段规范和用户后续明确要求为准。旧文档中的“直接输出 cmd_vel”“车载 RViz”“第一版停在椅子前面”等表述已不属于当前开发方案。硬件结论有冲突时重新采集证据，不能只凭文档覆盖实测。

外部技术依据与核对方式见 [参考资料](docs/references.md)。
