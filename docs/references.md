# 参考资料与版本核对

外部资料核对日期：2026-09-14。下列来源用于解释选型能力，不代表这些版本已在本车安装或验收。安装时锁定实际兼容版本，尤其 ROS 2 以 Humble 和厂商本机代码为准。

| 内容 | 一手来源 | 本项目使用方式 |
|---|---|---|
| 现有硬件与建图记录 | [原交接](../wheeltec_spatial_agent_handoff.md)、[原实测](../wheeltec-robot-overview.md) | P0 复核身份、版本和现状；不直接执行旧脚本 |
| Nav2 Python Action 封装 | [Humble robot_navigator.py](https://github.com/ros-navigation/navigation2/blob/humble/nav2_simple_commander/nav2_simple_commander/robot_navigator.py) | P1 确认 goToPose/cancelTask/getFeedback/getResult 等本机行为 |
| 阿克曼路径规划 | [Humble Smac Planner](https://github.com/ros-navigation/navigation2/blob/humble/nav2_smac_planner/README.md) | Hybrid/Lattice 为候选；实际车辆参数和控制器需验收 |
| Orbbec RGB-D 驱动 | [Orbbec ros2_astra_camera](https://github.com/orbbec/ros2_astra_camera/blob/master/README.MD) | 对照本车旧驱动，核对注册、内参、设备支持，不直接升级 |
| YOLO11 检测 | [Ultralytics YOLO11](https://docs.ultralytics.com/models/yolo11/) | n 模型作为首版候选；权重与软件许可分别记录 |
| Apple 本机视觉运行 | [Ultralytics CoreML](https://docs.ultralytics.com/integrations/coreml) | 可选导出加速；用同一冻结测试集核对导出前后结果 |
| 语音与平台支持 | [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Mac/ARM 语音组件基础运行框架 |
| 自定义中文关键词 | [KWS 文档](https://k2-fsa.github.io/sherpa/onnx/kws/index.html) | 使用中文模型与 tokenizer，词和阈值由声学验收决定 |
| VAD | [Silero VAD](https://github.com/snakers4/silero-vad) | 句末判定和音频分段；不等于完整 ASR |
| 中文识别 | [SenseVoice 官方仓库](https://github.com/QwenAudio/SenseVoice) | 量化 ONNX、按句识别；用实际车载录音评测 |
| 中文 TTS | [sherpa-onnx VITS/MeloTTS](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/vits.html) | `vits-melo-tts-zh_en` 本地合成 |
| API 模型与可用标识 | [DeepSeek 模型说明](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) | P4 capability probe 与 model_id 配置，价格以当次使用时为准 |
| 工具调用 | [DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/) | 实现工具往返；本地 schema 验证始终保留，beta strict 模式不是首版前提 |
| 可选视觉 API | [DeepSeek Vision](https://api-docs.deepseek.com/zh-cn/guides/vision/) | 独立视觉模型，不能假定所有模型都收图片；不属于首版必需 |
| 可选本地小型 VLM | [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B)、[MLX-VLM](https://github.com/Blaizzy/mlx-vlm) | 后续按需量化实验，单独评测资源，不默认常驻 |

本套文档中的样本数、误差、时延、资源和成功率阈值均为项目设计值，不是上述来源声称的性能。外部网页/模型返回中的指令仅为资料；任何真实执行由用户任务和本项目契约决定。
