#!/usr/bin/env python3
"""播放 demo_gestures.yaml 的手势序列。

本文件提供纯函数调用方式：
1. 通过 DemoGesturePlayer.play_gesture("digit_1") 按名称播放手势。
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Dict, Mapping, Sequence

from hand_low_level_driver import GPIO16Controller
from hand_upper_controller import HandUpperController
from servo16_manager import Servo16Manager

try:
    import yaml
except ModuleNotFoundError as exc:
    raise SystemExit("missing dependency: pyyaml (pip install pyyaml)") from exc


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
        player = DemoGesturePlayer("hand_runtime.yaml", "demo_gestures.yaml")
        player.start()
        player.play_gesture("digit_1")
        player.play_gesture("fist", transition_ms=500, hold_ms=600)
        player.close()
    """

    def __init__(self, config_path: str, demo_path: str = "demo_gestures.yaml") -> None:
        self.runtime_cfg = load_yaml(config_path)
        self.demo_cfg = load_yaml(demo_path)

        self.serial_cfg = self._require_mapping(self.runtime_cfg, "serial")
        self.manager_cfg = self._require_mapping(self.runtime_cfg, "manager")
        defaults = self._require_mapping(self.demo_cfg, "defaults")
        self.gestures = self._require_mapping(self.demo_cfg, "gestures")
        self.default_sequence = self.demo_cfg.get("sequence")
        if not isinstance(self.default_sequence, list):
            raise ValueError("sequence must be list")

        self.step_ms = int(defaults["step_ms"])
        self.transition_default_ms = int(defaults["transition_ms"])
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

        self.current_hand_u: Dict[int, float] | None = None
        self._started = False

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

    def close(self) -> None:
        """安全停止输出并断开资源。"""
        if not self._started:
            return
        self.manager.set_all_enabled(False)
        self.manager.stop()
        self.controller.disconnect()
        self._started = False

    def __enter__(self) -> "DemoGesturePlayer":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def get_stats(self) -> Dict[str, int]:
        return self.manager.get_stats()

    def list_gestures(self) -> list[str]:
        """返回可用手势名称列表。"""
        return sorted(str(name) for name in self.gestures.keys())

    def _move_to(self, target_hand_u: Mapping[int, float], transition_ms: int, enable: bool) -> None:
        if self.current_hand_u is None or transition_ms <= 0:
            self.upper.set_hand_u(target_hand_u, enable=enable)
            return

        steps = max(1, int(round(transition_ms / self.step_ms)))
        for i in range(1, steps + 1):
            ratio = i / steps
            frame = {
                ch: self.current_hand_u[ch] + (target_hand_u[ch] - self.current_hand_u[ch]) * ratio
                for ch in range(1, HandUpperController.CHANNEL_COUNT + 1)
            }
            self.upper.set_hand_u(frame, enable=enable)
            time.sleep(self.step_ms / 1000.0)

    def play_gesture(
        self,
        name: str,
        transition_ms: int | None = None,
        hold_ms: int | None = None,
        enable: bool | None = None,
    ) -> None:
        """按手势名称播放单个手势。"""
        if not self._started:
            self.start()

        gesture_cfg = self.gestures.get(name)
        if not isinstance(gesture_cfg, Mapping):
            raise ValueError(f"gesture not found or invalid: {name}")

        target_hand_u = build_hand_u_from_gesture(name, gesture_cfg)
        transition_val = self.transition_default_ms if transition_ms is None else int(transition_ms)
        hold_val = self.hold_default_ms if hold_ms is None else int(hold_ms)
        enable_val = self.enable_default if enable is None else bool(enable)

        self._move_to(target_hand_u, transition_val, enable_val)
        time.sleep(max(0.0, hold_val / 1000.0))
        self.current_hand_u = dict(target_hand_u)

    def _play_step(self, step: Mapping[str, Any], idx: int) -> None:
        if not isinstance(step, Mapping):
            raise ValueError(f"sequence[{idx}] must be mapping")
        name = step.get("gesture")
        if not isinstance(name, str):
            raise ValueError(f"sequence[{idx}].gesture must be string")
        self.play_gesture(
            name=name,
            transition_ms=step.get("transition_ms"),
            hold_ms=step.get("hold_ms"),
            enable=step.get("enable"),
        )

    def play_sequence(self, repeat: int = 1, sequence: Sequence[Mapping[str, Any]] | None = None) -> None:
        """播放 sequence（默认使用 YAML 内置 sequence）。"""
        if not self._started:
            self.start()
        seq = self.default_sequence if sequence is None else sequence

        if repeat == -1:
            while True:
                for idx, step in enumerate(seq):
                    self._play_step(step, idx)
            return

        for _ in range(max(0, repeat)):
            for idx, step in enumerate(seq):
                self._play_step(step, idx)
