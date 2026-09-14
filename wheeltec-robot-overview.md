# Wheeltec ROS 小车整体情况（2026-09-11 实测）

> 供后续开发参考。所有信息均为 SSH 登录实测所得。

## 1. 连接方式

| 项目 | 值 |
|------|-----|
| 热点 | `WHEELTEC_CAT2`（密码 `dongguan`） |
| 小车 IP | `192.168.0.100` |
| SSH | `ssh wheeltec@192.168.0.100`，密码 `dongguan` |
| 免密登录 | 已配置 `~/.ssh/id_ed25519` 公钥（2026-09-11），直接 ssh 即可 |
| VNC | 小车上跑着 x11vnc（systemd 服务 `x11vnc.service`），可用 VNC 客户端连 `192.168.0.100` 看桌面 |
| FTP | vsftpd 在运行 |
| 上网 | 见 `wheeltec-ssh-connect.md`：停热点服务后 `nmcli` 连手机热点；用完记得恢复热点 |

注意：小车没有 RTC 电池/校时，联网前系统时间会停留在旧时间（实测显示 2022 年），跑 ROS2 DDS 和 TLS 时可能出问题，联网后建议 `sudo ntpdate` 或 `timedatectl` 校时。

## 2. 计算平台

| 项目 | 值 |
|------|-----|
| 主板 | EmbedFire 野火 LubanCat1（RK3566/RK3588s 系列，板名 `EmbedFire LubanCat1 HDMI`） |
| 架构 | aarch64（ARM64），4 核 |
| 内存 | 4 GB（3.8 GiB 可用）+ 4 GB swap |
| 磁盘 | 56 GB，已用 35 GB（剩 19 GB） |
| 系统 | Ubuntu 22.04.2，内核 4.19.232（厂商定制） |
| ROS | **ROS 2 Humble**（`/opt/ros/humble`），只有 ROS 2，没有 ROS 1 |

算力定位：只有 CPU、无独立 NPU/GPU 推理环境记录（RK3566 自带 0.8TOPS NPU 但未见配置）。跑大模型/视觉模型需靠外部电脑，小车只做传感器+底盘节点。

## 3. 硬件清单（实测可用）

| 硬件 | 型号/证据 | 接口/设备节点 | 状态 |
|------|-----------|---------------|------|
| 2D 激光雷达 | 镭神 LS N10_P（驱动自识别 `Lidar is N10_P`） | `/dev/wheeltec_lidar` → CH343 串口 460800 | ✅ 实测 `ros2 launch turn_on_wheeltec_robot wheeltec_lidar.launch.py` 可出 `/scan` |
| 深度相机 | Orbbec Astra Pro Plus（USB ID `2bc5:0614`，launch 为 `astra_pro_plus.launch.py`），RGB 为独立 UVC 相机（`2bc5:0511`，`/dev/video9,10`） | USB | ✅ 驱动包 `ros2_astra_camera` 已装 |
| 底盘控制器（STM32） | Wheeltec 主板，串口 115200 | `/dev/wheeltec_controller` → CH343 串口 | ✅ 走 `turn_on_wheeltec_robot` 包 |
| IMU | 板载（`wheeltec_imu` 包 + EKF） | 串口/I2C | ✅ 配置文件 `config/imu.yaml` |
| 麦克风阵列 + 语音 | `wheeltec_mic` 包，含 `call_recognition`（唤醒）、`command_recognition`（离线命令词识别）、TTS（`tts_make_ros2`） | USB | ✅ 驱动已装 |
| 人体骨架识别 | `wheeltec_bodyreader`（Orbbec body tracking） | USB | ✅ 驱动已装 |
| 板载摄像头接口 | rkisp CSI 摄像头管线（`/dev/video0-8`），未确认是否插了 CSI 摄像头 | MIPI | ❓ |
| 音频输入输出 | rk809 codec（可录音/放音，配合 mic 和 TTS） | I2S | ✅ |
| GPIO/I2C | `/dev/gpiochip0-5`、`/dev/i2c-0,1,6`（可外接传感器） | — | 可扩展 |
| 显示器接口 | 有 lightdm 桌面 + HDMI | — | — |

车型：目录中含大量 URDF（mini_mec / mini_akm / senior / flagship 等全系），本机具体车型未在配置中明确标出（`base_serial.launch.py` 中 `akmcar` 默认 true，疑似阿克曼或差速型号），**首次开底盘前先用 `wheeltec_robot_keyboard` 低速验证运动方向**。

## 4. 软件环境（`~/wheeltec_ros2`，已编译 install）

主要功能包（全部为 ROS 2 Humble）：

- **bringup**：`turn_on_wheeltec_robot`（底盘串口 + EKF + IMU + TF），入口 `ros2 launch turn_on_wheeltec_robot turn_on_wheeltec_robot.launch.py`
- **导航栈**：`navigation2-humble`（Nav2）、`wheeltec_robot_nav2`、`nav2_waypoint_cycle`
- **SLAM**：`wheeltec_robot_slam`（cartographer 等）
- **相机**：`ros2_astra_camera`、`usb_cam-ros2`
- **语音**：`wheeltec_mic`（唤醒+命令词）、`tts_make_ros2`
- **感知/跟随**：`simple_follower_ros2`（目标跟随）、`wheeltec_robot_kcf`（KCF 视觉跟踪）、`aruco_ros`（二维码定位）、`wheeltec_bodyreader`（人体骨架）
- **遥控**：`wheeltec_robot_keyboard`、`wheeltec_joy`（手柄）
- **其他**：`wheeltec_multi`（多机）、`wheeltec_gps`、`wheeltec_path_follow`、`wheeltec_robot_rrt2`、`web_video_server-ros2`（浏览器看相机画面）、`qt_ros_test`
- 用户自己的工作区：`~/ros2_ws`（diy_msg、diy_turn_on_wheeltec_robot）

启动方式：`~/.bashrc` 已 source `/opt/ros/humble` 和 `~/wheeltec_ros2/install/setup.bash`，ssh 登录即可用 ros2 命令。当前小车开机不会自动启动 ROS 节点（topic list 为空）。

## 5. 遥控→建图→导航 操作手册（2026-09-11 实测验证）

全部命令来自车上自带手册 `~/wheeltec_ros2/src/ROS2-V3.5(humble)常用指令.txt`，底盘启动已实测（串口正常、`/odom` 20Hz）。每个 SSH 终端都要先确认环境（`.bashrc` 已自动 source，无需手动）。

### 第 0 步：可视化（Mac 上看 rviz）

跨机器看 TF 要求两台机器时钟一致，而小车无 RTC 电池、每次断电后时间回到 2022。两种办法：

- **简单**：在 Mac 上用 VNC 客户端连 `192.168.0.100`（车上有 x11vnc），直接在小车桌面开 rviz2；
- 或者修小车时间：`sudo date -s "2026-09-11 20:00:00"`（重启后失效，需重设），然后 Mac 装 ROS 2（如 RoboStack）跑 rviz2，或用 Foxglove Studio。

### 第 1 步：启动底盘 + 传感器

```bash
# 终端1：底盘 + EKF + IMU（实测 OK）
ros2 launch turn_on_wheeltec_robot turn_on_wheeltec_robot.launch.py

# 终端2：雷达（实测 OK，出 /scan）
ros2 launch turn_on_wheeltec_robot wheeltec_lidar.launch.py

# 或者一条带起底盘+雷达+相机：
# ros2 launch turn_on_wheeltec_robot wheeltec_sensors.launch.py
```

验证：`ros2 topic hz /odom`（~20Hz）、`ros2 topic hz /scan`（~10Hz）。

### 第 2 步：键盘遥控（不是实体遥控器）

```bash
# 终端3：键盘控制，按键 i 前进 / , 后退 / j l 转向 / k 停止，速度分档
ros2 run wheeltec_robot_keyboard wheeltec_keyboard
```

注意：首次遥控先低速、留好空间。终端要能接收按键（直接 ssh 交互终端即可）。带 USB 手柄的话用 `ros2 launch wheeltec_joy wheeltec_joy.launch.py`。

### 第 3 步：建图

```bash
# 终端4：三选一，推荐 slam_toolbox 或 cartographer
ros2 launch wheeltec_slam_toolbox online_async_launch.py
# ros2 launch wheeltec_cartographer cartographer.launch.py
# ros2 launch slam_gmapping slam_gmapping.launch.py
```

然后用键盘遥控车慢慢扫完场地，rviz2 里能看到地图逐渐长出来。满意后保存：

```bash
ros2 launch wheeltec_nav2 save_map.launch.py
# 地图存到 ~/wheeltec_ros2/src/wheeltec_robot_nav2/map/
```

### 第 4 步：Nav2 导航

```bash
# 终端5：加载刚才的地图启动导航
ros2 launch wheeltec_nav2 wheeltec_nav2.launch.py
```

rviz2 里用 **2D Pose Estimate** 给初始位姿，再点 **Nav2 Goal** 下目标点，车自动规划路径过去。参数文件默认 `param_mini_akm.yaml`（阿克曼车型），如果运动学不符换对应车型参数。

### 遥控方式补充（2026-09-11 实测）

- **蓝牙手柄：不可行**。小车没有蓝牙射频（rfkill 只有 WLAN，无 hci 设备；内核虽加载了蓝牙协议栈但无适配器）。想用蓝牙手柄需自购 USB 蓝牙适配器插车上并 `bluetoothctl` 配对。
- **厂家 PS2 无线手柄：可行**（如果装箱有）。它是 2.4G USB 接收器方案：接收器插小车 USB 口，出现 `/dev/input/js0` 后 `ros2 launch wheeltec_joy wheeltec_joy.launch.py`（该 launch 同时会拉起底盘）。普通 USB 有线手柄同理可用。
- 手柄/键盘控制车走的是**车本地**的 `/joy → /cmd_vel` 链路，与 Mac 是否在线无关。

### 建图时 Mac 需要保持连接吗？

**不需要**。雷达驱动、SLAM（slam_toolbox/cartographer）、底盘、EKF 全部跑在车本机，通过本机 DDS 通信，地图也建在车上。Mac 的作用只有两件事：SSH 发命令、rviz 看图。

- 用手柄遥控时：SSH 里用 `tmux` 启动各节点（防断线杀进程），之后 Mac 可以完全离开，建图照常进行，回来再连上看图/存图。
- 用键盘遥控时：Mac 必须保持连接（终端就是遥控器），建图过程建议保持 VNC/rviz 观察地图是否扫完整。
- Mac 中途断开再重连，车上节点不受影响，DDS 会自动重新发现。

### 想绕过 rviz 手动点 goal？用 simple commander（Agent 接入点）

```python
from nav2_simple_commander.robot_navigator import BasicNavigator  # Python API 下发导航目标
```

这就是后续 LLM Agent 调度的入口。

### 2026-09-11 实跑记录（重要经验）

- **车型确认**：进程加载的是 `mini_akm_robot.urdf`，这是台**迷你阿克曼车**，Nav2 用 `param_mini_akm.yaml` 正确。
- **slam_toolbox 与本车雷达不兼容**：slam_toolbox 要求每帧扫描点数固定，而 N10_P 每帧点数会浮动（528/529/530），扫描被全部丢弃，/map 永远出不来。**建图用 cartographer**（厂家配置已调好，实测 /map 2Hz 正常）。
- **rviz2 在车上跑不起来**：GL/Qt 驱动缺陷（软件渲染也段错误）。替代方案：**浏览器看图** —— 车上有个 map→PNG 快照服务，Mac 打开 `http://192.168.0.100:8000` 每 2 秒自动刷新看到实时地图（端口 8000，python http.server）。
- 小车系统时间已校准（无 RTC，重启后需重校，脚本会提示）。
- 辅助脚本已固化在车上 `~/scripts/`（/tmp 重启会丢）：
  - `~/scripts/start_mapping.sh {bringup|lidar|slam|rviz|stop}` 单独起各模块
  - `~/scripts/switch_carto.sh` 一键清场并启动 cartographer 建图（推荐入口）
  - `~/scripts/start_viewer.sh` 启动地图快照+网页服务
  - `~/scripts/cleanup_car.sh` 清理所有 ROS 进程
- 实测建图会话的标准启动顺序：`switch_carto.sh` → `start_viewer.sh` → Mac 浏览器开 8000 端口 → Mac 终端 ssh 上去跑 `ros2 run wheeltec_robot_keyboard wheeltec_keyboard` 开车。
- 存图：`ros2 launch wheeltec_nav2 save_map.launch.py`，地图落在 `~/wheeltec_ros2/src/wheeltec_robot_nav2/map/`。

## 6. 适合做什么（针对 AI/Agent 方向练手）

你有算法/软件背景，这台车的合理分工是：**小车上跑传感器驱动 + 底盘控制（ROS 2），AI 推理放你的 Mac 或云端**，两边用 Wi-Fi + DDS/ROS 2 或简单 HTTP/WebSocket 连接。

建议路线（由浅入深）：

1. **跑通基础**：键盘遥控 → cartographer 建图 → Nav2 点名导航（rviz 在 Mac 上跑，`ROS_DOMAIN_ID` 相同即可直接订阅小车话题）。
2. **语音 + LLM Agent**：用现成的 `wheeltec_mic` 唤醒/命令词节点做前端，把识别文本发给 Mac/云上的 LLM（function calling），LLM 输出映射为 `cmd_vel` 或 Nav2 goal —— 一个最小的"对话式机器人 Agent"。
3. **VLM 视觉 Agent**：Astra RGB 图像流 → Mac 上的视觉模型（目标检测/VLM 描述）→ 输出控制指令，配合 `simple_follower_ros2` 改造成"自然语言指定目标的人/物跟随"。
4. **自主任务 Agent**：Nav2 waypoint + LLM 做任务规划（"去厨房看看有人吗"→ 调度导航 → 到点拍照 → VLM 判断 → 语音 TTS 汇报）。这台车传感器（激光雷达+深度相机+IMU+麦克风阵列+TTS）正好凑齐了这个闭环。
5. **进阶**：ROS 2 Humble 自带 ros2_control/action/server 概念是机器人 Agent 工具调用（tool use）的天然载体，可以把每个 ROS 服务/动作封装成 LLM 的 tool。

注意事项：

- 4 GB 内存 + ARM CPU，不要在小车上跑推理（除很小的模型/RKNN NPU 需另行折腾）。
- 内核 4.19 较老，编译新版驱动/依赖时注意兼容。
- `ROS_MASTER_URI`/`ROS_HOSTNAME` 在 `.bashrc` 里有 ROS 1 残留配置（`192.168.151.128`），ROS 2 下无影响但建议清理；多机通信统一设 `ROS_DOMAIN_ID`（被注释掉了）。
- 磁盘剩 19 GB，装东西前留意。
