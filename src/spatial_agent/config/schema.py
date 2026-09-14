"""Runtime configuration schema, mirroring docs/templates/runtime.example.json.

Strict validation: unknown fields are rejected, floats must be finite, and
profile is one of mock/replay/hardware. There is no runtime fallback to mock
(development-requirements.md §4): the profile is explicit and load-bearing.
"""

from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"
FIRST_VERSION_MAX_LINEAR_SPEED_MPS = 0.1


class Profile(StrEnum):
    MOCK = "mock"
    REPLAY = "replay"
    HARDWARE = "hardware"


class PathsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifacts: str = "artifacts"
    datasets: str = "datasets"
    model_lock: str = "models.lock.json"
    database: str = "artifacts/state/spatial.sqlite3"


class RobotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_id: str | None = None
    ssh_host: str | None = None
    ssh_user: str | None = None
    gateway_url: str = "http://127.0.0.1:8765"
    gateway_token_env: str = "ROBOT_GATEWAY_TOKEN"
    expected_ros_distro: str = "humble"


class MacConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    listen_host: str = "127.0.0.1"
    listen_port: int = 8080


class MapConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    map_id: str | None = None
    manifest: str | None = None
    frame_id: str = "map"


class MotionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    max_linear_speed_mps: float = 0.1
    allow_reverse: bool = False
    allow_spin_recovery: bool = False
    min_obstacle_clearance_m: float = 0.3
    footprint_m: list[float] | None = None
    wheelbase_m: float | None = None
    min_turning_radius_m: float | None = None
    session_file: str | None = None
    lease_period_ms: int = 250
    lease_timeout_ms: int = 1000
    sensor_stale_ms: int = 500
    navigation_timeout_s: float = 180

    @field_validator("max_linear_speed_mps", "min_obstacle_clearance_m", "wheelbase_m", "min_turning_radius_m")
    @classmethod
    def _finite_positive(cls, v):
        if v is None:
            return v
        if not math.isfinite(v) or v <= 0:
            raise ValueError("must be a finite positive number")
        return v

    @field_validator("footprint_m")
    @classmethod
    def _footprint_shape(cls, v):
        if v is None:
            return v
        if len(v) != 2 or any(not math.isfinite(x) or x <= 0 for x in v):
            raise ValueError("footprint_m must be [length_m, width_m] with finite positive values")
        return v


class PerceptionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    detector_model_id: str = "yolo11n"
    runtime: str = "onnx"
    calibration_id: str | None = None
    max_rgb_depth_skew_ms: float = 50
    stationary_capture_only: bool = True
    max_concurrent_captures: int = 1
    capture_timeout_s: float = 5
    goal_validity_s: float = 5
    arrival_distance_from_object_boundary_m: list[float] = Field(default_factory=lambda: [0.6, 1.0])

    @field_validator("max_rgb_depth_skew_ms", "capture_timeout_s", "goal_validity_s")
    @classmethod
    def _positive(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError("must be a finite positive number")
        return v

    @field_validator("arrival_distance_from_object_boundary_m")
    @classmethod
    def _range_shape(cls, v):
        if len(v) != 2 or not (0 <= v[0] < v[1]) or not all(math.isfinite(x) for x in v):
            raise ValueError("must be [min_m, max_m] with 0 <= min < max")
        return v


class MemoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    movable_object_reverify_after_s: float = 60
    require_map_id: bool = True
    preserve_observations: bool = True


class TasksConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeout_s: float = 300
    max_active_tasks: int = 1
    max_viewpoints: int = 3
    max_replans: int = 2
    max_stationary_verification_retries: int = 2
    resume_motion_after_restart: bool = False


class PlannerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    provider: str = "deepseek"
    base_url: str = "https://api.deepseek.com"
    model_id: str | None = None
    api_key_env: str = "DEEPSEEK_API_KEY"
    image_input_enabled: bool = False
    request_timeout_s: float = 30
    max_retries: int = 2
    max_model_requests_per_task: int = 8
    max_tool_calls_per_task: int = 20
    max_input_tokens_per_task: int = 40000
    max_output_tokens_per_task: int = 4000
    allow_silent_model_fallback: bool = False


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    sample_rate_hz: int = 16000
    channels: int = 1
    encoding: str = "s16le"
    frame_ms: int = 20
    max_input_buffer_s: float = 2
    pre_roll_ms: int = 500
    wake_phrase: str = "你好小轮"
    wake_phrase_is_provisional: bool = True
    kws_model_id: str | None = None
    kws_threshold: float | None = None
    stop_phrase: str = "停止"
    stop_requires_wake: bool = False
    vad_model_id: str = "silero-vad"
    asr_model_id: str = "SenseVoiceSmall"
    tts_model_id: str = "vits-melo-tts-zh_en"
    max_utterance_s: float = 15
    end_silence_ms: int = 800
    no_speech_timeout_s: float = 5
    barge_in_enabled: bool = False
    gate_input_during_playback: bool = True


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = SCHEMA_VERSION
    example_only: bool = False
    profile: Profile = Profile.MOCK
    paths: PathsConfig = Field(default_factory=PathsConfig)
    robot: RobotConfig = Field(default_factory=RobotConfig)
    mac: MacConfig = Field(default_factory=MacConfig)
    map: MapConfig = Field(default_factory=MapConfig)
    motion: MotionConfig = Field(default_factory=MotionConfig)
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    tasks: TasksConfig = Field(default_factory=TasksConfig)
    planner: PlannerConfig = Field(default_factory=PlannerConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)

    @field_validator("schema_version")
    @classmethod
    def _schema_version(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION!r}, got {v!r}")
        return v
