# P1：基础导航、Robot Skills 与停车

## 目标和前置条件

实现“加载地图、获取位姿、规划到点、执行、取消和停止”，在真实小车上形成可重复的受控导航能力。

硬件验收前 P0 已通过；需要平坦限定场地、已确认现场会话、独立物理停车方式、实际 footprint/轴距/转弯半径及可用地图。先完成所有无需运动的工作，再请求仍缺少的现场事实。

## 按顺序执行

1. **P1.1 实测运动学和控制链**：检查实际 URDF、底盘模式、速度单位/转向转换、发布者和 watchdog。用有标记场地/人工测量验证尺寸与转弯半径；不能由参数文件名称推出物理值正确。
2. **P1.2 建立受控输出路径**：实现 `robot_safety` 独立进程、lease、stop 锁存、超时和必要输入新鲜度检查。导航输出先通过该层，列出全部可控制底盘的其他入口并避免绕过。
3. **P1.3 停车链分级验证**：先 mock 故障注入，再无地面移动的台架验证 Gateway/supervisor 退出后行为；最后在低速测试区测物理制动。未证明下游超时停车则硬件关卡不通过。
4. **P1.4 地图与定位**：已有地图先校验；没有地图则在有效现场会话中按厂商 Cartographer 流程遥控采集。保存到项目 shared/maps 和 Mac manifest，冻结 hash。任务运行选择 AMCL 或已实测的等效定位方案，保证 TF 唯一权威。
5. **P1.5 阿克曼 Nav2 配置**：优先验证现有插件组合。若不能产生可执行曲率路径，评估 Humble Smac Hybrid/Lattice 与阿克曼兼容控制器；关闭依赖原地旋转的恢复，不默认启用倒车。使用真实 footprint、膨胀范围和最小转弯半径。
6. **P1.6 Robot Skills**：实现 `get_pose`、`plan`、`navigate_to_pose`、`cancel_navigation`、`get_navigation_status`、`stop_robot`。异步动作不阻塞 HTTP、lease 或 stop。区分 action 的取消确认与物理停稳。
7. **P1.7 Gateway 与 Mac 客户端**：实现接口契约中 P1 endpoints、幂等请求、事件序列与重连。Mac 最小页面显示地图/轨迹/位姿/状态/错误和停车按钮，不依赖车载 RViz。
8. **P1.8 发布**：实现 release、服务启动顺序、dry-run、只读默认、故障回滚和两次重启复现。
9. **P1.9 验收**：先离线、再静止硬件、最后在会话范围内完成导航与 fault suite，保存视频/测量及全部失败 trial。

## 必须交付

- 三个车端包 `robot_skills`、`robot_gateway`、`robot_safety`，有独立职责与构建入口。
- `nav2`/安全/TF 配置和 `hardware-baseline.json`，包含实测值与测量方法。
- frozen map manifest、允许区域、≥3 个验收目标、初始位姿设置方法。
- Mac 客户端、只读状态页和停车入口；没有完备地图交互也应能从 suite manifest 执行目标。
- 独立停车链证据、服务部署/回滚清单与报告。

## 部署与验收

先实现并执行离线测试，再完成明确的部署计划：

```bash
./scripts/project test --level unit
./scripts/project test --level integration --profile mock
./scripts/project deploy --target robot --release <release_id> --dry-run
./scripts/project deploy --target robot --release <release_id>
./scripts/project tunnel up
./scripts/project up --profile robot-readonly
./scripts/project status
```

确认定位、控制链与真实现场会话后，才进行：

```bash
./scripts/project up --profile robot-live
./scripts/project session open --file configs/local/session.json
./scripts/project robot arm --session <session_id>
./scripts/project accept --phase P1 --mode hardware --session <session_id>
./scripts/project robot stop --reason acceptance_finished
./scripts/project down
```

`<...>` 必须来自实际已生成的 release/session，不能复制占位符运行。`accept` 在开始/结束每批故障测试时管理 disarm/重新检查，故障后的重新 arm 必须仍在有效现场范围内。

全部 P1-STREAM～P1-ROLLBACK 用例见 [验收规范](../acceptance.md)。历史 `/odom` 20 Hz、`/scan` 10 Hz 只能用作排查参照。

## 失败处理与退出条件

运动学/制动验证失败：停止地面实验，独立修复参数或控制链。定位异常：静止状态核对时钟/TF/地图，不能不断发目标尝试“跑好”。不满足转弯空间：返回不可达，不缩小 footprint 伪造路径。

P1 PASS 后向 P2 提供：有效 map_id、位姿/TF API、可控启动与停止、经验证的导航/故障行为、明确版本和静止采集位置。
