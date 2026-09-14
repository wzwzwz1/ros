"""P0.6 key-unknowns register.

Every fact that the phase documents require but that cannot be known without
on-site measurement is recorded here with an explicit ``null`` value until a
named phase/role actually measures it. Nulls are never silently replaced by
documented historical values (README: hardware conclusions conflict -> re-measure).
"""

from __future__ import annotations

UNKNOWN_ITEMS = [
    {"key": "robot_online_identity", "question": "机器人当前是否在线、实际 robot_id 与软件版本", "phase": "P0.5", "measured_by": "agent, read-only SSH"},
    {"key": "wheelbase_m", "question": "轴距 wheelbase", "phase": "P0.6/P1", "measured_by": "onsite tape measure or URDF/参数核对"},
    {"key": "track_width_m", "question": "轮距/车宽", "phase": "P0.6/P1", "measured_by": "onsite tape measure or URDF/参数核对"},
    {"key": "footprint_m", "question": "footprint（长×宽，含安全余量）", "phase": "P0.6/P1", "measured_by": "onsite tape measure + Nav2 参数核对"},
    {"key": "min_turning_radius_m", "question": "阿克曼最小转弯半径", "phase": "P0.6/P1", "measured_by": "实测或厂商参数核对"},
    {"key": "chassis_stop_mechanism", "question": "底盘命令超时/停车机制（驱动进程被杀后的行为）", "phase": "P1", "measured_by": "agent, isolated bench test"},
    {"key": "available_maps", "question": "已保存地图的实际文件与质量", "phase": "P0.5/P1", "measured_by": "agent, read-only SSH"},
    {"key": "nav2_plugins", "question": "Nav2 当前 controller/planner 插件与 AMCL 配置", "phase": "P0.5/P1", "measured_by": "agent, read-only parameter dump"},
    {"key": "rgbd_alignment", "question": "RGB-D 原始/对齐输出、深度单位", "phase": "P0.5/P2", "measured_by": "agent, read-only probe"},
    {"key": "camera_calibration", "question": "相机内参与安装外参标定", "phase": "P2", "measured_by": "agent, calibration procedure"},
    {"key": "mic_pcm_entry", "question": "麦克风原始 PCM 入口与通道", "phase": "P0.5/P5", "measured_by": "agent, arecord probe"},
    {"key": "speaker_path", "question": "扬声器播放路径与混音行为", "phase": "P0.5/P5", "measured_by": "agent, aplay probe"},
    {"key": "custom_wake_capability", "question": "厂商唤醒模块是否支持自定义词并暴露音频", "phase": "P0.5/P5", "measured_by": "agent, vendor module inspection"},
    {"key": "mac_network_plan", "question": "Mac 同时接小车与互联网的方案", "phase": "P0", "measured_by": "user + agent verification"},
    {"key": "onsite_session_facts", "question": "现场人员、限定场地、独立停车方式、测量工具", "phase": "before any motion", "measured_by": "user/operator on site"},
    {"key": "deepseek_credentials", "question": "DeepSeek 本项目凭据与实际可用模型", "phase": "P4", "measured_by": "user provides env var; agent capability probe"},
    {"key": "server_gpu", "question": "服务器 CPU/GPU/显存（可选扩展）", "phase": "optional", "measured_by": "user"},
]


def build_unknowns_register() -> dict:
    return {
        "schema_version": "1.0",
        "kind": "p0_unknowns_register",
        "items": [
            {**item, "status": "unknown", "value": None, "evidence": None} for item in UNKNOWN_ITEMS
        ],
    }
