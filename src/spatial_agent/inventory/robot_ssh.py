"""Read-only robot inventory over SSH (P0.5).

Every check is a single read-only command executed with BatchMode SSH (keys
only — passwords are never placed on command lines). A failing check is
recorded as evidence, not swallowed. If the robot is unreachable the collector
returns a BLOCKED result with the attempt recorded. No network scanning is
performed: we only ever talk to the configured host.
"""

from __future__ import annotations

import subprocess
import time
from datetime import UTC, datetime

ROS_ENV_PREFIX = "source /opt/ros/humble/setup.bash && source ~/wheeltec_ros2/install/setup.bash 2>/dev/null; "


class RobotCheck:
    def __init__(self, name: str, command: str, timeout_s: float = 15.0, ros_env: bool = False):
        self.name = name
        self.command = (ROS_ENV_PREFIX if ros_env else "") + command
        self.timeout_s = timeout_s


ROBOT_CHECKS = [
    RobotCheck("identity", "uname -a && cat /etc/os-release | head -5 && hostname && cat /etc/machine-id 2>/dev/null | head -1"),
    RobotCheck("cpu_arch", "uname -m && nproc"),
    RobotCheck("memory", "free -m"),
    RobotCheck("disk", "df -h / /home 2>/dev/null"),
    RobotCheck("uptime_load", "uptime"),
    RobotCheck("clock", "date -u +%Y-%m-%dT%H:%M:%S.%3NZ && cat /proc/uptime"),
    RobotCheck("ros_distro", "ls /opt/ros/ 2>/dev/null && test -f /opt/ros/humble/setup.bash && echo humble-present"),
    RobotCheck("vendor_workspace", "ls ~/wheeltec_ros2 2>/dev/null | head -20; ls ~/wheeltec_ros2/src 2>/dev/null | head -40"),
    RobotCheck("ros_pkgs_nav", "ros2 pkg list 2>/dev/null | grep -E 'nav2|wheeltec|cartographer|slam' | head -40", ros_env=True),
    RobotCheck("ros_nodes", "timeout 12 ros2 node list 2>/dev/null | head -40", ros_env=True, timeout_s=20),
    RobotCheck("ros_topics", "timeout 12 ros2 topic list -t 2>/dev/null | head -80", ros_env=True, timeout_s=20),
    RobotCheck("nav2_params_presence", "find ~/wheeltec_ros2/src -maxdepth 3 -name '*nav*.yaml' 2>/dev/null | head -10"),
    RobotCheck("maps_dir", "ls -la ~/.ros 2>/dev/null | head -30"),
    RobotCheck("devices_serial", "ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null; ls -l /dev/i2c-* 2>/dev/null"),
    RobotCheck("devices_video", "ls -l /dev/video* 2>/dev/null; v4l2-ctl --list-devices 2>/dev/null | head -20"),
    RobotCheck("audio_capture", "arecord -l 2>/dev/null; arecord -L 2>/dev/null | head -30"),
    RobotCheck("audio_playback", "aplay -l 2>/dev/null"),
    RobotCheck("vendor_scripts", "ls ~/scripts 2>/dev/null; for f in ~/scripts/*.sh; do echo \"== $f\"; grep -E 'ros2 (launch|run)|kill|pkill|systemctl' \"$f\" 2>/dev/null | head -10; done"),
    RobotCheck("services", "systemctl list-units --type=service --no-pager 2>/dev/null | grep -Ei 'wheeltec|ros|voice|audio' | head -20"),
    RobotCheck("python_ros", "python3 --version && python3 -c 'import rclpy; print(\"rclpy ok\")' 2>&1 | tail -1", ros_env=True),
    RobotCheck("mem_available", "grep -E 'MemAvailable|MemFree' /proc/meminfo"),
]


def _ssh_run(host: str, user: str, command: str, timeout_s: float, port: int = 22) -> dict:
    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=4",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "LogLevel=ERROR",
        "-p", str(port),
        f"{user}@{host}",
        command,
    ]
    started = time.monotonic()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, stdin=subprocess.DEVNULL)
        return {
            "name": None,
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout[:20000],
            "stderr": result.stderr[:2000],
            "duration_s": round(time.monotonic() - started, 3),
        }
    except subprocess.TimeoutExpired:
        return {"command": command, "returncode": None, "error": f"timeout after {timeout_s}s",
                "duration_s": round(time.monotonic() - started, 3)}
    except FileNotFoundError:
        return {"command": command, "returncode": None, "error": "ssh binary not found"}


def collect_robot_inventory(host: str, user: str, port: int = 22) -> dict:
    """Run all read-only checks. Never raises. Connection failures are BLOCKED."""
    probe = _ssh_run(host, user, "true", timeout_s=8, port=port)
    collected_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    result: dict = {
        "kind": "robot_inventory_readonly",
        "collected_at_utc": collected_at,
        "target": {"host": host, "user": user, "port": port},
        "reachable": probe.get("returncode") == 0,
        "probe": probe,
        "checks": [],
    }
    if not result["reachable"]:
        result["status"] = "BLOCKED"
        detail = probe.get("error") or probe.get("stderr") or f"returncode={probe.get('returncode')}"
        result["blocker"] = f"robot not reachable via key-authenticated SSH ({detail})"
        return result

    for check in ROBOT_CHECKS:
        outcome = _ssh_run(host, user, check.command, timeout_s=check.timeout_s)
        outcome["name"] = check.name
        outcome["read_only"] = True
        result["checks"].append(outcome)
    result["status"] = "COLLECTED"
    return result
