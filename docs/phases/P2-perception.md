# P2：RGB-D 物体定位与空间记忆

## 目标和前置条件

用真实 RGB-D 图像检测椅子，得到有不确定性、可追溯的 map-frame 几何观测，并保存成可查询记忆。

硬件验收以前置 P1 通过为准。需要相机实际输出、可靠 TF、标定及测量场地；默认停车观察。可先使用有真实来源的录包做离线开发，不能把图片样例当成本车标定证据。

## 按顺序执行

1. **P2.1 相机盘点**：确认 RGB/Depth/CameraInfo 的 topic、frame、encoding、尺寸、单位、FPS/QoS。检查 UVC 与深度是否同一时间域、是否提供对齐结果。
2. **P2.2 标定与同步**：验证内参/畸变、RGB-depth 外参、相机到 base 的外参；固定安装位置并给 calibration_id。缺标定时先提供采集工具、标定板要求和执行步骤，让现场人员完成实物准备后采集。
3. **P2.3 Bundle API**：实现采集时 TF、时间差、新鲜度、静止条件和资源哈希；深度无损，RGB 可 JPEG。采样默认按需 640×480 或相机实际支持配置，不能只改尺寸却不更新内参。
4. **P2.4 检测**：Mac 下载锁定 YOLO11n；用验收集外样本调整分辨率、置信度和 NMS。模型支持的 class list 由模型读取并暴露，不手写不存在的类。
5. **P2.5 几何定位**：在检测区域选择一致的有效深度簇，剔除零值、远背景和离群点；不能无条件取 bbox 中心像素。使用内参反投影及 capture TF 得到地图坐标；明显多峰/低有效率时拒绝或标 tentative。
6. **P2.6 不确定性与范围**：记录测量离散度、定位/标定贡献、有效深度比例与可见物体范围。先采用保守表面代表点，另附定义，不宣称输出物体朝向。
7. **P2.7 SQLite memory**：实现 observation/object 两层、去重、关联门槛、版本、时间、map_id 隔离和重启恢复。首次有效观测可 tentative，多次一致观测后 confirmed；相邻同类物体不强行合并。
8. **P2.8 可视化与数据集**：最小页面显示 RGB 检测框、深度取样、地图投影、ID/置信度/时间和错误。采集调参集与独立验收集，保存标签与真值测法。
9. **P2.9 验收**：30 组几何测量与 100 张检测验收图片，运行 invalid-data suite 和延迟/资源采样。

## 必须交付

- capture bundle API、Mac Detector/Grounding/Memory 模块及 schema migration。
- calibration manifest、模型 lock、真实数据 manifest、标签和测量表。
- 重放工具能使用 bundle 的历史 TF，不访问当前真实机器人。
- 带错误类型和不确定性的可视化结果，不把无效定位画成可靠目标。
- P2 原始误差、precision/recall、失败样本、latency/resource 报告。

## 部署与验收

```bash
./scripts/project models fetch --group perception
./scripts/project test --level unit
./scripts/project test --level integration --profile mock
./scripts/project accept --phase P2 --mode replay
./scripts/project up --profile robot-readonly
./scripts/project accept --phase P2 --mode hardware
```

hardware P2 默认只在停稳车上采集，不发导航。不同观察位置由已有有效会话下的 P1 移动或现场人员按规程摆放；验收 runner 不暗中移动机器人。数据不足时准备采集列表并报告 BLOCKED，不能通过重复同一帧凑足样本。

P2-BUNDLE～P2-LATENCY 门槛见 [验收规范](../acceptance.md)。反投影至少有已知几何的数学测试、TF 方向错误测试、深度单位错误测试和真实测量验证。

## 失败处理与退出条件

RGB-depth 对齐错误、TF 时间不一致或 map_id 不匹配时拒绝生成可导航坐标。检测不够好先分析误检/漏检；更换模型必须重跑冻结检测集。可考虑分割掩膜改善深度取样，但应记录对内存/延迟的影响。

P2 PASS 后提供：可查询物体 ID、最新观测位置/范围/不确定性、静止捕获与观测接口，以及真实几何精度证据。
