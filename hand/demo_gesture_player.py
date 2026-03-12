#!/usr/bin/env python3
"""播放 demo_gestures.yaml 的单个手势动作。

本文件提供纯函数调用方式：
1. 通过 DemoGesturePlayer.play_gesture("digit_1") 按名称播放手势。
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Dict, Mapping

from hand_low_level_driver import GPIO16Controller
from hand_upper_controller import HandUpperController
from servo16_manager import Servo16Manager

try:
    import yaml
except ModuleNotFoundError as exc:
    raise SystemExit("missing dependency: pyyaml (pip install pyyaml)") from exc

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_CONFIG_PATH = BASE_DIR / "hand_runtime.yaml"
DEMO_GESTURES_PATH = BASE_DIR / "demo_gestures.yaml"


def load_yaml(path: str) -> Dict[str, Any]:
    """加载 YAML 文件并返回字典对象。"""
    yaml_path = Path(path)
    if not yaml_path.exists():
        raise FileNotFoundError(f"yaml not found: {yaml_path}")
    with yaml_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"yaml root must be mapping: {yaml_path}")
    return data


def build_hand_u_from_gesture(
    gesture_name: str,
    gesture_cfg: Mapping[str, Any],
) -> Dict[int, float]:
    """将单个手势定义转换为 {channel: u}。

    例如：
        thumb: [u1,u2,u3,u4], index: [u1,u2,u3], ...
    会根据 HandUpperController.FINGER_CHANNELS 固定映射表，
    转为 1~16 通道的归一化目标字典。
    """
    hand_u: Dict[int, float] = {}
    for finger, channels in HandUpperController.FINGER_CHANNELS.items():
        values = gesture_cfg.get(finger)
        if not isinstance(values, list):
            raise ValueError(f"gesture '{gesture_name}' missing finger '{finger}' list")
        if len(values) != len(channels):
            raise ValueError(
                f"gesture '{gesture_name}' finger '{finger}' expects {len(channels)} values, got {len(values)}"
            )
        for ch, u in zip(channels, values):
            hand_u[ch] = float(u)
    return hand_u


class DemoGesturePlayer:
    """Demo 手势播放器。

    典型用法：
        player = DemoGesturePlayer()
        player.start()  # start() 内部会自动执行初始化
        player.play_gesture("digit_1")
        player.play_gesture("fist", hold_ms=600)
        player.close()
    """

    def __init__(self) -> None:
        self.runtime_cfg = load_yaml(str(RUNTIME_CONFIG_PATH))
        self.demo_cfg = load_yaml(str(DEMO_GESTURES_PATH))

        self.serial_cfg = self._require_mapping(self.runtime_cfg, "serial")
        self.manager_cfg = self._require_mapping(self.runtime_cfg, "manager")
        defaults = self._require_mapping(self.demo_cfg, "defaults")
        self.gestures = self._require_mapping(self.demo_cfg, "gestures")

        self.hold_default_ms = int(defaults["hold_ms"])
        self.enable_default = bool(defaults["enable"])

        self.controller = GPIO16Controller(
            port=str(self.serial_cfg["port"]),
            baudrate=int(self.serial_cfg["baudrate"]),
            timeout=float(self.serial_cfg["timeout"]),
        )
        self.manager = Servo16Manager(
            gpio=self.controller,
            period_s=float(self.manager_cfg["period_s"]),
            quantize_us=int(self.manager_cfg["quantize_us"]),
            verbose=bool(self.manager_cfg["verbose"]),
        )
        self.upper = HandUpperController(manager=self.manager, config=self.runtime_cfg)

        self._started = False
        self._initialized = False

    @staticmethod
    def _require_mapping(root: Mapping[str, Any], key: str) -> Mapping[str, Any]:
        value = root.get(key)
        if not isinstance(value, Mapping):
            raise ValueError(f"{key} must be mapping")
        return value

    def start(self) -> None:
        """连接硬件并启动调度线程。"""
        if self._started:
            return
        if not self.controller.connect():
            raise RuntimeError("failed to connect serial device")
        self.manager.start()
        self._started = True
        self.initialize_runtime()

    def close(self) -> None:
        """安全停止输出并断开资源。"""
        if not self._started:
            return
        self.manager.set_all_enabled(False)
        self.manager.stop()
        self.controller.disconnect()
        self._started = False
        self._initialized = False

    def __enter__(self) -> "DemoGesturePlayer":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def play_gesture(
        self,
        name: str,
        hold_ms: int | None = None,
        enable: bool | None = None,
        settle_s: float | None = None,
        relax_after_settle: bool = False,
    ) -> None:
        """按手势名称播放单个手势。"""
        if not self._started:
            self.start()

        gesture_cfg = self.gestures.get(name)
        if not isinstance(gesture_cfg, Mapping):
            raise ValueError(f"gesture not found or invalid: {name}")

        target_hand_u = build_hand_u_from_gesture(name, gesture_cfg)
        hold_val = self.hold_default_ms if hold_ms is None else int(hold_ms)
        enable_val = self.enable_default if enable is None else bool(enable)

        self.upper.set_hand_u(target_hand_u, enable=enable_val)
        if enable_val and relax_after_settle:
            settle_val = 0.5 if settle_s is None else float(settle_s)
            if settle_val < 0:
                raise ValueError("settle_s must be >= 0")
            if settle_val > 0:
                time.sleep(settle_val)
            self.manager.set_all_enabled(False)
        time.sleep(max(0.0, hold_val / 1000.0))

    def initialize_runtime(self, hold_s: float = 1.0, force: bool = False) -> None:
        """执行启动初始化：最左 -> 最右 -> 最中间。"""
        if not self._started:
            self.start()
            return
        if self._initialized and not force:
            return
        hold_val = float(hold_s)
        if hold_val < 0:
            raise ValueError("hold_s must be >= 0")
        settle_val = 0.5

        all_channels = {
            ch: 0.0
            for channels in HandUpperController.FINGER_CHANNELS.values()
            for ch in channels
        }
        self.upper.set_hand_u(
            all_channels,
            enable=True,
            settle_s=settle_val,
            relax_after_settle=True,
        )
        if hold_val > 0:
            time.sleep(hold_val)

        right_pose = {ch: 1.0 for ch in all_channels.keys()}
        self.upper.set_hand_u(
            right_pose,
            enable=True,
            settle_s=settle_val,
            relax_after_settle=True,
        )
        if hold_val > 0:
            time.sleep(hold_val)

        center_pose = {ch: 0.5 for ch in all_channels.keys()}
        self.upper.set_hand_u(
            center_pose,
            enable=True,
            settle_s=settle_val,
            relax_after_settle=True,
        )
        if hold_val > 0:
            time.sleep(hold_val)

        self._initialized = True
        print("initial OK")
        time.sleep(1)
