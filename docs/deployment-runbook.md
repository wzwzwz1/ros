# 部署、运行与回滚手册

本文是开发时必须实现并最终实际验证的操作契约。**当前只有文档，`./scripts/project` 及下列项目服务尚不存在。** P0 负责实现基础命令；后续阶段扩展子命令。未实现命令应清楚报错，不用空脚本返回 0。

## 1. CLI 契约

所有命令均在项目根目录执行，支持 `--help`。会访问网络/硬件的命令必须明确目标，不靠自动发现选中任意机器人。

| 命令 | 作用/要求 | 最迟实现 |
|---|---|---|
| `./scripts/project bootstrap --target mac` | 创建环境、安装锁定依赖、检查平台；重复执行幂等 | P0 |
| `./scripts/project doctor --target mac` | 只读检查硬件/内存/磁盘/依赖 | P0 |
| `./scripts/project doctor --target robot --read-only` | SSH 只读收集身份、包、设备、topic、TF 与控制链 | P0 |
| `./scripts/project config validate --file configs/local/runtime.json` | 配置验证；不能开启运动 | P0 |
| `./scripts/project test --level unit` | 无硬件、无外部推理 API | P0 |
| `./scripts/project test --level integration --profile mock` | 契约、模拟 Gateway、状态机及故障注入 | P0 |
| `./scripts/project models fetch --group perception` | 按模型清单下载、校验 hash/许可、检查磁盘 | P2 |
| `./scripts/project models fetch --group voice` | 同上；不下载未选择的大模型 | P5 |
| `./scripts/project deploy --target robot --release <id> --dry-run` | 输出计划、文件清单与服务变化，不写车端 | P1 |
| `./scripts/project deploy --target robot --release <id>` | 仅部署本项目；服务默认 disarmed | P1 |
| `./scripts/project tunnel up` | SSH 转发，确认主机身份；不能自动忽略 host key 变化 | P1 |
| `./scripts/project up --profile mock` | Mac + 模拟 Gateway，禁止硬件网络 | P0 |
| `./scripts/project up --profile robot-readonly` | Gateway 与状态查看，可定位/采集；不能导航 | P1 |
| `./scripts/project up --profile robot-live` | 具备导航链，但仍 disarmed，需有效现场会话 | P1 |
| `./scripts/project status` | 列出目标、profile、版本、依赖、armed/stop 状态 | P0 |
| `./scripts/project session open --file configs/local/session.json` | 校验真实现场会话记录，生成短期会话，不默认 arm | P1 |
| `./scripts/project robot arm --session <id>` | 所有前置通过后开启运动许可；不自行移动 | P1 |
| `./scripts/project robot stop --reason <text>` | 优先车端停车，终止租约，等待/报告确认 | P1 |
| `./scripts/project accept --phase P1 --mode hardware --session <id>` | 执行冻结的阶段用例，产出报告；省略 session 不允许运动 | 对应阶段 |
| `./scripts/project accept --phase P2 --mode replay` | 真实录包离线验收，与 hardware 标签分开 | P2 |
| `./scripts/project down` | 先停车/撤销租约，再关本项目进程；不清理他人节点 | P0/P1 |
| `./scripts/project rollback --target robot --release <id>` | 停车后恢复已知项目版本，默认 disarmed | P1 |

统一退出码：0=所请求操作通过，1=已执行但失败，2=参数/配置错误，3=缺少前置条件，4=尚未实现。进度命令的正常响应不代表阶段验收通过。`accept --mode` 的退出码对应本次请求模式的必需用例；该范围有 BLOCKED/NOT_RUN 时不得返回 0。报告必须同时提供 `run_status` 和汇总所有模式的 `phase_gate_status`，本次 mock 返回 0 不等于整个阶段通过。

## 2. P0：建立本地可复现环境

1. 检查目录是否已有 Git 仓库和修改。实际实施时可初始化当前根目录；保留原三份文档。分支默认 `codex/` 前缀。
2. 增加 `.gitignore`，忽略 `.env*`（保留无密钥 example）、`configs/local/`、模型、录音、地图图像、artifacts 和 venv。私有原连接文档是否公开由用户决定，不发布本仓库。
3. 实现 bootstrap、doctor、mock、配置校验和报告框架。使用 [配置模板](templates/runtime.example.json) 创建本地配置，未知字段保持 null。
4. 锁定兼容依赖，运行 unit/integration；进程以 mock 启动，检查没有真实机器人网络连接。
5. 将 stdout/stderr、环境版本、配置哈希存入 `artifacts/acceptance/<run_id>/`，不打印密钥。

## 3. 机器人盘点（只读）

连接信息来自用户确认的目标与已有 SSH 配置。历史地址为 `wheeltec@192.168.0.100`；地址可变，必须核对 robot_id/设备身份。

doctor 应执行或等价采集：

- OS/kernel/architecture、`free`、磁盘、CPU、系统时间与 Mac 时间差。
- `~/wheeltec_ros2` 的 source、install、Nav2 插件、当前 launch/参数/URDF 和脚本内容。
- 显式加载 `/opt/ros/humble/setup.bash` 及厂商 install；非交互 SSH 不假定 `.bashrc` 会自动 source。
- topic/service/action/type/QoS、publisher、TF、传感器设备的实际路径。
- microphone 是否提供普通 PCM/ALSA 音频；存在唤醒节点不能证明能采集自由语音。
- `~/scripts/` 各脚本会启动/停止哪些进程。不得直接调用宽泛 cleanup/switch 脚本。
- Mac 到车端连接、Mac 到 DeepSeek 域名 HTTPS 连接分别验证；不用 API key 也能验证 DNS/TLS，推理能力另测。

若车未在线，记录 BLOCKED，完成 mock 和其他本地任务。不得扫描无关网段寻找设备。

## 4. 车端发布布局

```text
~/spatial_agent/
├── releases/<release_id>/   # 本项目源码、lock、构建产物
├── current -> releases/<release_id>
├── shared/{configs,maps,logs,state}/
└── previous-release.json
```

- release_id 使用提交 hash 加构建标识；有未提交代码时记录完整 diff/hash，不能伪称干净 commit。
- 在车端 ARM64 环境构建 overlay，依次 source 系统 ROS、厂商 install、项目 install。
- 默认不修改厂商文件；必要的 launch/参数拷贝到项目配置中，由项目启动器显式使用。
- 服务建议 `spatial-safety.service`、`spatial-gateway.service`、`spatial-navigation.service`，名称和所有权固定。用户服务/系统服务选型在 P1 根据设备权限验证；需要管理员写入时先生成完整 unit 和变更计划。
- 自动重启只恢复只读/disarmed 服务，不恢复运动租约或旧任务。
- 发布时先确保已停稳、撤销 arm，再原子切换 current；不能在车运动时热换控制组件。
- 应用与 SQLite schema 迁移都备份。回滚有不兼容数据库变更时恢复对应备份，并保留新记录副本。

## 5. 启动与实车会话

顺序如下；启动器根据已存在进程与所有权去重：

1. 检查电量/供电、磁盘、时钟与传感器状态。
2. 启动独立运动监督，保持输出禁止运动。
3. 启动底盘、雷达、TF/里程计；P2 起启动 RGB-D。
4. 选择建图或定位模式。任务模式加载已冻结地图、Nav2，建立唯一 map→odom 链。
5. 在已知起点设置经过测量的初始位姿与合理协方差，验证定位；不能用全零 covariance 假装精准。
6. 启动 Gateway，建立 SSH 隧道与 Mac 应用，检查版本和 capabilities。
7. 如开展运动，读取已存在的现场会话确认并校验，不对已经确认的同一批测试重复提问。
8. arm 前检查限定区域、当前配置哈希、地图、停车方式、关键 sensor/TF、只有受控速度发布者和有效 lease。
9. 执行指定 suite，记录每个 trial；结束无论成功失败均停车、disarm、停止续约并保存报告。

现场会话至少包含：operator、确认来源及时间、到期时间（默认 30 分钟）、robot_id、map_id、场地多边形、最大速度、允许用例、物理停车方式、现场已清场事实。可用用户本会话真实确认生成记录，不需要再次重复确认；Agent 不能自行虚构 operator_present。

模板文件中的 `example_only=true`、空身份、过期时间或未确认现场均不能用于真实 arm。配置 `motion.enabled` 仅决定是否加载 live 运动能力；已有执行授权和有效现场会话后可启用，启动服务仍默认 disarmed。长 suite 可在同一确认范围内分批执行；超过已确认在场时段需取得新的真实在场信息，不可自动延长会话。

更换场地/地图、无人继续在场、超出速度/用例范围、会话过期或异常运动后，会话失效。mock 的 operator/session 仅在 mock 可用。

## 6. 常规部署验证

部署前计划必须列出：目标主机与身份、release、文件清单、影响服务、磁盘估算、config diff、回滚 release、需要重新验收的 case。

部署后依次检查：health → capabilities → status → pose/TF → 传感器 → 无运动 fault suite → 有效会话下的运动 suite。P4/P5 再增加 API/音频能力。

每阶段至少从新建进程启动一次；P1 须跨两次机器人重启验证。不能只验证开发终端里长期运行的残留环境。

## 7. 故障与回滚

| 现象 | 立即动作 | 后续 |
|---|---|---|
| Mac/SSH 断开 | 车端租约超时禁止运动 | 恢复通信，只读核对；旧目标不自动恢复 |
| Gateway 卡死/退出 | 独立监督撤销运动 | 保存 supervisor 和底盘证据；检查依赖，不重启即继续 |
| supervisor 退出 | 已验证的下游命令超时/等效机制停车 | 此链路未验证则禁止运动验收 |
| TF/定位/scan 无效 | 禁止新目标，停止当前运动 | 在静止状态排查，不猜测位姿 |
| 深度无效 | 拒绝定位/导航到物体 | 允许固定状态机选择已验收观察点再看，受任务预算限制 |
| API 429/5xx/超时 | 有界重试，期间不给新运动目标 | 失败则 MODEL_UNAVAILABLE，保留当前任务状态 |
| 部署后健康检查失败 | 保持 disarmed | 回滚 current/config/schema；重跑健康检查和受影响 suite |
| 音频或磁盘缓冲过载 | 停止新增采集/新任务，保留控制通道 | 清理由本项目明确标记且不属验收证据的临时文件 |

不得为排错关闭安全监督、取消输入验证或调大超时到无限。清理/归档按 manifest 精确选择文件。

## 8. 服务器与完全本地扩展

服务器不是首版必需部署目标。启用前先确认操作系统、CPU、GPU 型号/显存、磁盘和可达性。仅有 64 GB RAM 时先用于离线处理与备份，不写死 CUDA/vLLM 部署命令。

更换模型后，保持 Task/Tool 接口，重新跑 P4 契约与场景 suite；模型 API 和自部署服务均不能绕过本地执行器。
