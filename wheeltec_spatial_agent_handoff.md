# Wheeltec Spatial Agent 项目交接文档

## 0. 项目目标

基于现有 Wheeltec ROS 2 小车，构建一个以**空间理解、任务规划、导航执行和语音交互**为核心的具身 Agent 系统。

目标不是让 LLM 直接输出电机控制，而是采用分层架构：

```text
语音 / 文本任务
    ↓
ASR
    ↓
LLM / Agent Planner
    ↓
Spatial Memory / World Model
    ↓
Robot Skills / ROS2 Tools
    ├─ navigate_to()
    ├─ get_pose()
    ├─ observe_scene()
    ├─ find_object()
    ├─ follow_person()
    ├─ stop_robot()
    └─ speak()
    ↓
Nav2 / Cartographer / 感知节点
    ↓
底盘 / 传感器
```

核心研究问题应放在：

```text
Perception
→ Spatial Representation
→ Reasoning
→ Action
→ Re-observation
→ Memory Update
```

而不是单纯“LLM 控制 ROS 小车”。

---

# 1. 机器人硬件与系统信息

## 1.1 基本信息

- 厂商：Wheeltec
- 车型：**Mini AKM**
- 底盘：**阿克曼转向底盘**
- ROS：**ROS 2 Humble**
- OS：Ubuntu 22.04.2
- 架构：aarch64 / ARM64
- 主板：EmbedFire 野火 LubanCat1 HDMI
- SoC：RK35xx 系列
- CPU：4 核
- 内存：4 GB + 4 GB swap
- 磁盘：约 56 GB，总剩余约 19 GB
- 内核：4.19.232（厂商定制）

注意：

- 该车不是麦克纳姆底盘。
- `N10_P` 是激光雷达型号，不是小车型号。
- 车载算力较弱，不建议在车上跑大模型或重型视觉模型。
- 推荐车端承担实时 ROS、SLAM、导航、传感器采集，AI 推理放 Mac / GPU 工作站。

---

# 2. 网络与远程连接

## 2.1 默认热点

```text
SSID: WHEELTEC_CAT2
Password: dongguan
Robot IP: 192.168.0.100
```

SSH：

```bash
ssh wheeltec@192.168.0.100
```

密码：

```text
dongguan
```

当前已经配置 SSH 公钥免密登录。

## 2.2 VNC

车上有：

```text
x11vnc.service
```

可连接：

```text
192.168.0.100
```

但当前车载 `rviz2` 因 GL/Qt 驱动问题会崩溃，因此 VNC 主要用于普通桌面排查，不建议依赖车载 RViz。

## 2.3 时间问题

小车没有 RTC 电池。

断电重启后，系统时间可能回到旧年份（曾实测 2022）。

这会影响：

- ROS 2 DDS
- 跨机器 TF
- TLS
- 某些网络服务

联网后应校时，例如：

```bash
sudo ntpdate pool.ntp.org
```

或手动：

```bash
sudo date -s "2026-09-14 10:00:00"
```

后续建议增加自动校时脚本。

---

# 3. 传感器与底盘

## 3.1 2D 激光雷达

型号：

```text
镭神 LS N10_P
```

设备：

```text
/dev/wheeltec_lidar
```

串口：

```text
CH343
460800 baud
```

启动：

```bash
ros2 launch turn_on_wheeltec_robot wheeltec_lidar.launch.py
```

输出：

```text
/scan
```

实测约 10 Hz。

重要已知问题：

- N10_P 每帧 scan 点数会轻微浮动，如 528 / 529 / 530。
- `slam_toolbox` 会因为要求固定扫描点数而丢弃扫描。
- 因此当前推荐 **Cartographer** 建图。

---

## 3.2 深度相机

型号：

```text
Orbbec Astra Pro Plus
```

主要驱动：

```text
ros2_astra_camera
```

RGB 独立 UVC：

```text
USB ID 2bc5:0511
/dev/video9
/dev/video10
```

深度设备：

```text
USB ID 2bc5:0614
```

可用于：

- RGB 视觉
- Depth
- 目标定位
- 人体骨架
- 视觉语义理解
- 语义地图
- ObjectNav

---

## 3.3 底盘控制器

Wheeltec STM32 控制板：

```text
/dev/wheeltec_controller
115200 baud
```

主要包：

```text
turn_on_wheeltec_robot
```

启动：

```bash
ros2 launch turn_on_wheeltec_robot turn_on_wheeltec_robot.launch.py
```

已实测：

```text
/odom ≈ 20 Hz
```

---

## 3.4 IMU

已有：

```text
wheeltec_imu
EKF
config/imu.yaml
```

用于：

```text
Encoder + IMU → EKF → odom
```

---

## 3.5 麦克风与语音

已有：

```text
wheeltec_mic
call_recognition
command_recognition
tts_make_ros2
```

能力：

- 唤醒
- 离线命令词识别
- TTS
- 音频输入输出

适合构建：

```text
Wake Word
→ ASR
→ Agent
→ ROS Tool
→ TTS
```

---

## 3.6 人体识别

已有：

```text
wheeltec_bodyreader
```

基于 Orbbec 人体骨架追踪。

另有：

```text
simple_follower_ros2
wheeltec_robot_kcf
aruco_ros
```

可以快速做：

- 人体跟随
- KCF 视觉跟踪
- ArUco 定位/跟随

---

# 4. ROS 2 软件环境

工作区：

```bash
~/wheeltec_ros2
```

已编译：

```text
install/
```

`.bashrc` 已自动 source：

```bash
/opt/ros/humble/setup.bash
~/wheeltec_ros2/install/setup.bash
```

因此 SSH 登录后可直接使用：

```bash
ros2 ...
```

用户自有工作区：

```bash
~/ros2_ws
```

已有：

```text
diy_msg
diy_turn_on_wheeltec_robot
```

建议后续 Agent 项目优先放到新的独立 workspace 或 Git 仓库中，避免直接修改厂家 workspace。

---

# 5. 厂家已有功能包

## Bringup

```text
turn_on_wheeltec_robot
```

负责：

- 底盘串口
- IMU
- EKF
- TF
- 基础状态

---

## 导航

```text
navigation2-humble
wheeltec_robot_nav2
nav2_waypoint_cycle
```

---

## SLAM

```text
wheeltec_robot_slam
wheeltec_cartographer
wheeltec_slam_toolbox
slam_gmapping
```

实际推荐：

```text
Cartographer
```

---

## 相机

```text
ros2_astra_camera
usb_cam-ros2
```

---

## 感知

```text
simple_follower_ros2
wheeltec_robot_kcf
aruco_ros
wheeltec_bodyreader
```

---

## 遥控

```text
wheeltec_robot_keyboard
wheeltec_joy
```

---

## 其他

```text
wheeltec_multi
wheeltec_gps
wheeltec_path_follow
wheeltec_robot_rrt2
web_video_server-ros2
qt_ros_test
```

---

# 6. 已验证基础流程

## 6.1 启动底盘

```bash
ros2 launch turn_on_wheeltec_robot turn_on_wheeltec_robot.launch.py
```

验证：

```bash
ros2 topic hz /odom
```

---

## 6.2 启动雷达

```bash
ros2 launch turn_on_wheeltec_robot wheeltec_lidar.launch.py
```

验证：

```bash
ros2 topic hz /scan
```

---

## 6.3 键盘遥控

```bash
ros2 run wheeltec_robot_keyboard wheeltec_keyboard
```

常用按键：

```text
i 前进
, 后退
j/l 转向
k 停止
```

首次运动必须低速验证。

---

# 7. 建图

## 7.1 当前推荐 Cartographer

不要优先使用 `slam_toolbox`。

原因：

```text
N10_P 每帧点数浮动
→ slam_toolbox 丢帧
→ /map 无输出
```

推荐：

```bash
ros2 launch wheeltec_cartographer cartographer.launch.py
```

或使用已有脚本：

```bash
~/scripts/switch_carto.sh
```

---

## 7.2 当前推荐标准流程

```bash
~/scripts/switch_carto.sh
~/scripts/start_viewer.sh
```

Mac 浏览器：

```text
http://192.168.0.100:8000
```

然后 SSH 中：

```bash
ros2 run wheeltec_robot_keyboard wheeltec_keyboard
```

慢速遥控建图。

---

## 7.3 保存地图

```bash
ros2 launch wheeltec_nav2 save_map.launch.py
```

地图目录：

```bash
~/wheeltec_ros2/src/wheeltec_robot_nav2/map/
```

---

# 8. Nav2

导航：

```bash
ros2 launch wheeltec_nav2 wheeltec_nav2.launch.py
```

当前车型对应：

```text
mini_akm_robot.urdf
param_mini_akm.yaml
```

该参数目前是正确选择。

重要：

这是阿克曼车，因此：

- 无法原地旋转
- 无法横移
- 存在最小转弯半径

Agent 和局部规划器必须考虑非完整约束。

---

# 9. 辅助脚本

固定目录：

```bash
~/scripts/
```

已有：

```text
start_mapping.sh
switch_carto.sh
start_viewer.sh
cleanup_car.sh
```

用途：

```text
start_mapping.sh {bringup|lidar|slam|rviz|stop}
switch_carto.sh
    清理旧进程 + 启动 Cartographer

start_viewer.sh
    地图 PNG 快照 + HTTP 服务

cleanup_car.sh
    清理 ROS 相关进程
```

---

# 10. 已知系统限制

## 10.1 本地算力

车载：

```text
ARM 4 核
4 GB RAM
```

不建议运行：

- 大型 VLM
- 7B+ LLM
- SAM
- VGGT
- 重型 YOLO
- 大型视觉编码器

推荐：

```text
车端：
ROS2
传感器
Cartographer
Nav2
实时控制

外部 Mac / GPU：
LLM
VLM
YOLO
SAM
Spatial Memory
Agent Planner
```

---

## 10.2 RViz

车载 `rviz2`：

```text
GL / Qt 崩溃
```

当前不要依赖。

替代：

- Mac ROS2 + RViz
- Foxglove
- Web Viewer
- 自定义 Web UI

---

## 10.3 地图性质

N10_P 是 2D LiDAR，因此地图是二维激光扫描平面。

适合：

- 实验室
- 办公室
- 教室
- 普通走廊

不擅长：

- 大面积玻璃
- 镜面
- 高重复货架
- 大型空旷大厅
- 多楼层 3D
- 楼梯/悬崖检测

深度相机可以弥补一部分 2D LiDAR 的高度信息缺失。

---

# 11. 空间 Agent 推荐架构

建议分成 4 层。

## Layer 1：Robot Skill Layer

最优先实现。

建议 ROS2 tool：

```python
get_robot_pose()
navigate_to_pose(x, y, yaw)
navigate_to(name)
cancel_navigation()
stop_robot()

capture_rgb()
capture_depth()

speak(text)

get_laser_summary()
get_navigation_status()
```

所有 tool 必须具备：

- timeout
- error
- status
- cancel
- safety check

LLM 不直接控制 `/cmd_vel`。

---

## Layer 2：Perception Layer

输入：

```text
RGB
Depth
LiDAR
Robot Pose
TF
```

输出 object observation：

```json
{
  "label": "chair",
  "confidence": 0.91,
  "camera_xyz": [0.2, 0.0, 2.3],
  "map_xy": [4.3, 2.8],
  "timestamp": 123456
}
```

推荐流程：

```text
RGB
→ Detector / VLM
→ Depth
→ camera XYZ
→ TF
→ map XYZ
```

---

# 12. Spatial Memory

这是整个项目最值得重点做的模块。

第一版不要一开始做复杂 3D Scene Graph。

先做 object-centric memory：

```json
{
  "objects": {
    "chair_001": {
      "label": "chair",
      "position": [4.3, 2.8],
      "confidence": 0.91,
      "last_seen": 12345
    },
    "door_001": {
      "label": "door",
      "position": [2.1, 5.2]
    }
  }
}
```

以后再扩展：

```text
Building
└─ Floor
   └─ Room
      ├─ Object
      ├─ Region
      └─ Relation
```

支持关系：

```text
left_of
right_of
near
inside
in_front_of
behind
connected_to
visible_from
reachable_from
```

最终目标：

```text
Metric Map
+
Semantic Memory
+
Topological Graph
```

---

# 13. Agent Layer

Agent 应负责：

- 任务分解
- Tool selection
- 空间查询
- 信息不足判断
- 主动观察
- 重规划
- 失败恢复

例如：

用户：

```text
去找一把椅子，并停在它前面。
```

Agent：

```text
1. query_memory("chair")
2. 如果已有可靠位置：
      navigate_to(chair)
3. 否则：
      select_next_viewpoint()
      navigate_to(viewpoint)
      observe_scene()
      update_memory()
4. 找到 chair
5. estimate_safe_goal(chair)
6. navigate_to_pose(goal)
7. verify_target()
8. speak("已经找到椅子")
```

这比：

```text
LLM → /cmd_vel
```

合理得多。

---

# 14. 语音架构

已有 Wheeltec 麦克风阵列和 TTS。

建议：

```text
Wake Word
↓
Audio
↓
ASR
↓
Agent
↓
ROS2 Tool
↓
执行
↓
TTS
```

第一版可以先用：

```text
厂商 wake word
+
外部 ASR / LLM
+
车载 TTS
```

以后再替换为更强 ASR。

---

# 15. 推荐外部计算架构

```text
                 Wi-Fi
┌───────────────┐     ┌────────────────────┐
│ Wheeltec      │     │ Mac / GPU Server   │
│               │     │                    │
│ LiDAR         │     │ LLM                │
│ Astra RGB-D   │────→│ VLM / Detector     │
│ IMU/Odom      │     │ Spatial Memory     │
│ Cartographer  │←────│ Agent Planner      │
│ Nav2          │     │                    │
│ STM32         │     │                    │
└───────────────┘     └────────────────────┘
```

连接方式可以选择：

### ROS2 DDS

优点：

- ROS 原生
- Topic/Service/Action 完整

问题：

- Wi-Fi multicast
- DDS discovery
- 时间同步

### HTTP / WebSocket

适合 Agent tool API。

推荐长期设计：

```text
ROS2 local skills
↓
Robot Gateway
↓
HTTP/WebSocket
↓
Agent Server
```

这样 Agent 与 ROS 解耦更清晰。

---

# 16. 第一阶段 MVP

不要一开始做完整智能机器人。

第一阶段只做：

> **“找到实验室中的椅子，并导航到椅子附近。”**

需要：

```text
Cartographer
Nav2
RGB-D
Object Detector / VLM
Spatial Memory
Agent Tools
```

MVP 验收：

1. 启动机器人
2. 加载已有地图
3. 获取机器人 map pose
4. 采集 RGB-D
5. 检测 chair
6. 估计 chair 在 map 坐标系下的位置
7. 写入 Spatial Memory
8. 生成 chair 附近可达 goal
9. Nav2 导航
10. 到达后重新观察
11. 判断任务成功

---

# 17. 第二阶段

加入多物体语义地图：

```text
chair
desk
door
person
trash_bin
extinguisher
```

支持：

```text
“最近的椅子在哪里？”
“门附近有什么？”
“带我去桌子旁边。”
```

---

# 18. 第三阶段

做主动探索 / ObjectNav：

用户：

```text
去找一个垃圾桶。
```

机器人：

```text
Memory 无结果
↓
选择 waypoint
↓
导航
↓
观察
↓
更新 memory
↓
重新规划
```

核心研究点：

- Next Best View
- Active Exploration
- Semantic Exploration
- Spatial Uncertainty

---

# 19. 第四阶段

语音 Agent：

```text
“去门口看看有没有人。”
```

执行：

```text
ASR
↓
Agent
↓
navigate_to("door")
↓
observe_scene()
↓
person detector / VLM
↓
TTS 回答
```

---

# 20. 第五阶段：Research 方向

如果后续要做成更偏论文的系统，建议重点研究：

## Spatial Memory

- Object-centric memory
- Scene Graph
- Topological map
- Metric-semantic fusion
- Long-term memory update

## Grounding

语言：

```text
“靠门的椅子”
```

如何映射到真实世界对象。

## Active Perception

Agent 判断：

```text
当前视角不足
→ 主动移动
→ 获取新视角
```

## Geometry Verification

VLM：

```text
“椅子在左边”
```

使用：

```text
Depth / LiDAR / TF
```

验证几何关系，减少幻觉。

## Spatial Reasoning

包括：

- distance
- direction
- containment
- visibility
- reachability
- relative position

## Failure Recovery

例如：

```text
目标不存在
Nav2 失败
路径被堵
对象已移动
定位失败
```

Agent 如何检测和恢复。

---

# 21. 推荐仓库结构

```text
wheeltec-spatial-agent/
├── AGENTS.md
├── README.md
├── docs/
│   ├── hardware.md
│   ├── ros_interfaces.md
│   ├── architecture.md
│   └── experiments.md
│
├── ros2_ws/
│   └── src/
│       ├── robot_skills/
│       ├── perception_bridge/
│       ├── spatial_memory_bridge/
│       └── robot_gateway/
│
├── agent/
│   ├── planner/
│   ├── tools/
│   ├── memory/
│   └── prompts/
│
├── perception/
│   ├── detector/
│   ├── rgbd_localization/
│   └── semantic_mapping/
│
├── voice/
│   ├── asr/
│   └── tts/
│
├── configs/
├── scripts/
└── tests/
```

---

# 22. Codex 接手后的第一批任务

建议 Codex 按顺序完成，不要跳级。

## Task 1：项目初始化

创建：

```text
wheeltec-spatial-agent
```

加入：

```text
README.md
AGENTS.md
docs/
```

---

## Task 2：Robot Skill Layer

实现 ROS2 Python 包：

```text
robot_skills
```

API：

```python
get_pose()
navigate_to_pose()
cancel_navigation()
stop_robot()
get_nav_status()
```

底层：

```text
nav2_simple_commander
```

禁止 LLM 直接控制连续 `/cmd_vel`。

---

## Task 3：Robot Gateway

实现一个简单 HTTP API：

```text
GET  /pose
POST /navigate
POST /stop
GET  /status
```

将 ROS2 与 Agent 解耦。

推荐 Python：

```text
FastAPI
```

ROS2 节点与 Web API 可以先放同一进程，也可以后续拆分。

---

## Task 4：Spatial Memory v0

先用：

```text
SQLite / JSON
```

记录：

```text
object_id
label
x
y
z
confidence
timestamp
source
```

提供：

```python
add_observation()
query_objects()
find_nearest()
update_object()
```

---

## Task 5：RGB-D Object Grounding

实现：

```text
2D Detection
+
Depth
+
TF
→ map-frame object position
```

暂时不追求 Scene Graph。

---

## Task 6：第一个 Agent

Tool：

```text
get_pose
navigate
observe
find_object
stop
speak
```

任务：

```text
find a chair and navigate near it
```

---

# 23. 安全约束

Agent 必须满足：

- 不允许 LLM 直接连续发布高速 `/cmd_vel`
- 所有导航必须经过 Nav2
- `stop_robot()` 永远可立即调用
- 设置最大速度
- 设置最小安全距离
- 任务 timeout
- 导航失败时停止
- 感知失败时不盲目运动
- 不允许自动上下楼梯
- 深度相机后续最好增加 cliff / drop detection

---

# 24. 当前最重要的设计原则

## 原则 1

LLM：

```text
负责“做什么”
```

Nav2：

```text
负责“怎么走”
```

STM32：

```text
负责“怎么驱动轮子”
```

不要混层。

## 原则 2

空间智能不要只依赖 VLM。

推荐：

```text
VLM / Detector
+
Depth
+
LiDAR
+
TF
+
Metric Map
```

做 cross-check。

## 原则 3

第一版优先可靠性，不追求复杂模型。

先跑通：

```text
object → map coordinate → Nav2
```

再做 Agent reasoning。

## 原则 4

机器人是“主动传感器”。

Agent 应该允许：

```text
不知道
→ 移动
→ 再看
→ 更新认知
```

这是该项目相比普通视觉问答最值得做的地方。

---

# 25. 当前一句话项目定义

> **基于 ROS 2、RGB-D、2D LiDAR 和多模态大模型的真实室内空间理解与自主导航 Agent。**

重点不是语音控制本身，而是：

> **让 Agent 建立、查询和更新真实空间记忆，并通过主动移动获取信息、完成任务。**

---

# 26. 推荐首个演示

Demo：

```text
用户：
“去找一把椅子，然后停在它前面。”

机器人：
1. 查询 Spatial Memory
2. 如果未知则开始探索
3. RGB-D 发现 chair
4. 转成 map 坐标
5. 计算安全目标位置
6. Nav2 导航
7. 到达后重新观察
8. TTS：
   “我已经找到椅子。”
```

这是整个项目最合适的第一个完整闭环。
