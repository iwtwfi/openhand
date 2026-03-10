#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""16 路舵机管理器：基于 3B 指令做统一软件 PWM 调度。"""

from dataclasses import dataclass
import threading
import time
from typing import Dict, List, Optional

from hand_low_level_driver import GPIO16Controller


@dataclass
class ServoChannelConfig:
    """单路舵机参数。"""

    min_pulse_us: int = 500
    max_pulse_us: int = 2500
    trim_us: int = 0
    reverse: bool = False
    enabled: bool = False
    max_speed_deg_s: float = 360.0


class Servo16Manager:
    """16 路舵机统一调度器（单线程周期调度）。"""

    CHANNEL_COUNT = 16

    def __init__(
        self,
        gpio: GPIO16Controller,
        period_s: float = 0.020,
        quantize_us: int = 100,
        verbose: bool = False,
    ):
        if period_s <= 0:
            raise ValueError("period_s 必须大于 0")
        if quantize_us <= 0:
            raise ValueError("quantize_us 必须大于 0")

        self.gpio = gpio
        self.period_s = period_s
        self.period_ns = int(period_s * 1_000_000_000)
        self.quantize_us = quantize_us
        self.verbose = verbose

        self._configs: List[ServoChannelConfig] = [ServoChannelConfig() for _ in range(self.CHANNEL_COUNT)]
        self._targets: List[float] = [90.0] * self.CHANNEL_COUNT
        self._currents: List[float] = [90.0] * self.CHANNEL_COUNT

        self._lock = threading.Lock()
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_states: List[bool] = [False] * self.CHANNEL_COUNT
        self._last_tx_len = 1

        self._stats = {
            "cycles": 0,
            "overruns": 0,
            "tx_failures": 0,
        }

    @staticmethod
    def _clamp_angle(angle_deg: float) -> float:
        return max(0.0, min(180.0, angle_deg))

    @staticmethod
    def _assert_channel(channel: int) -> int:
        if not (1 <= channel <= Servo16Manager.CHANNEL_COUNT):
            raise ValueError("channel 必须在 1~16")
        return channel - 1

    def set_target_angle(self, channel: int, angle_deg: float, enable: bool = True) -> None:
        idx = self._assert_channel(channel)
        with self._lock:
            self._targets[idx] = self._clamp_angle(angle_deg)
            if enable:
                self._configs[idx].enabled = True

    def set_targets(self, target_map: Dict[int, float], enable: bool = True) -> None:
        # 快速路径：完整 16 路覆盖更新，避免逐路赋值开销。
        if len(target_map) == self.CHANNEL_COUNT:
            try:
                ordered = [self._clamp_angle(target_map[ch]) for ch in range(1, self.CHANNEL_COUNT + 1)]
            except KeyError:
                ordered = []
            if ordered:
                with self._lock:
                    self._targets = ordered
                    if enable:
                        for cfg in self._configs:
                            cfg.enabled = True
                return

        with self._lock:
            for channel, angle in target_map.items():
                idx = self._assert_channel(channel)
                self._targets[idx] = self._clamp_angle(angle)
                if enable:
                    self._configs[idx].enabled = True

    def set_targets_and_relax(self, target_map: Dict[int, float], settle_s: float = 0.5) -> None:
        """下发目标，等待到位后自动关闭对应通道，减少保持抖动。"""
        if settle_s < 0:
            raise ValueError("settle_s 必须 >= 0")
        self.set_targets(target_map, enable=True)
        if settle_s > 0:
            time.sleep(settle_s)
        with self._lock:
            for channel in target_map.keys():
                idx = self._assert_channel(channel)
                self._configs[idx].enabled = False

    def set_target_list(self, angles_deg: List[float], enable: bool = True) -> None:
        if len(angles_deg) != self.CHANNEL_COUNT:
            raise ValueError("angles_deg 长度必须为 16")

        clamped = [self._clamp_angle(angle) for angle in angles_deg]
        with self._lock:
            self._targets = clamped
            if enable:
                for cfg in self._configs:
                    cfg.enabled = True

    def set_all_targets(self, angle_deg: float, enable: bool = True) -> None:
        angle = self._clamp_angle(angle_deg)
        self.set_target_list([angle] * self.CHANNEL_COUNT, enable=enable)

    def set_channel_enabled(self, channel: int, enabled: bool) -> None:
        idx = self._assert_channel(channel)
        with self._lock:
            self._configs[idx].enabled = enabled

    def set_all_enabled(self, enabled: bool) -> None:
        with self._lock:
            for cfg in self._configs:
                cfg.enabled = enabled

    def set_channel_config(
        self,
        channel: int,
        min_pulse_us: Optional[int] = None,
        max_pulse_us: Optional[int] = None,
        trim_us: Optional[int] = None,
        reverse: Optional[bool] = None,
        enabled: Optional[bool] = None,
        max_speed_deg_s: Optional[float] = None,
    ) -> None:
        idx = self._assert_channel(channel)
        with self._lock:
            cfg = self._configs[idx]
            if min_pulse_us is not None:
                cfg.min_pulse_us = int(min_pulse_us)
            if max_pulse_us is not None:
                cfg.max_pulse_us = int(max_pulse_us)
            if trim_us is not None:
                cfg.trim_us = int(trim_us)
            if reverse is not None:
                cfg.reverse = bool(reverse)
            if enabled is not None:
                cfg.enabled = bool(enabled)
            if max_speed_deg_s is not None:
                if max_speed_deg_s <= 0:
                    raise ValueError("max_speed_deg_s 必须大于 0")
                cfg.max_speed_deg_s = float(max_speed_deg_s)

            if cfg.min_pulse_us <= 0 or cfg.max_pulse_us <= cfg.min_pulse_us:
                raise ValueError("min_pulse_us/max_pulse_us 参数非法")

    def get_stats(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._stats)

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="servo16-manager", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._send_states([False] * self.CHANNEL_COUNT, frame_len=self.CHANNEL_COUNT)

    def _angle_to_pulse_us(self, angle_deg: float, cfg: ServoChannelConfig) -> int:
        angle = 180.0 - angle_deg if cfg.reverse else angle_deg
        ratio = angle / 180.0
        pulse = cfg.min_pulse_us + ratio * (cfg.max_pulse_us - cfg.min_pulse_us)
        pulse += cfg.trim_us
        pulse = max(cfg.min_pulse_us, min(cfg.max_pulse_us, pulse))
        quantized = int(round(pulse / self.quantize_us) * self.quantize_us)
        return max(cfg.min_pulse_us, min(cfg.max_pulse_us, quantized))

    def _send_states(self, states: List[bool], frame_len: int) -> bool:
        tx_len = max(1, min(self.CHANNEL_COUNT, frame_len))
        tx_len = max(tx_len, self._last_tx_len)
        payload = states[:tx_len]

        ok = self.gpio.set_gpio_batch(payload, verbose=self.verbose)
        if not ok:
            with self._lock:
                self._stats["tx_failures"] += 1
            return False

        self._last_states = list(states)
        self._last_tx_len = tx_len
        return True

    @staticmethod
    def _sleep_until_ns(deadline_ns: int) -> None:
        while True:
            now = time.perf_counter_ns()
            remain = deadline_ns - now
            if remain <= 0:
                return

            # 长等待用 sleep，最后阶段短忙等降低调度抖动。
            if remain > 300_000:
                time.sleep((remain - 150_000) / 1_000_000_000)

    def _loop(self) -> None:
        while self._running.is_set():
            cycle_start_ns = time.perf_counter_ns()

            with self._lock:
                targets = list(self._targets)
                configs = [ServoChannelConfig(**vars(cfg)) for cfg in self._configs]

            states = [False] * self.CHANNEL_COUNT
            fall_events: Dict[int, List[int]] = {}
            active_indexes = [i for i, cfg in enumerate(configs) if cfg.enabled]
            active_frame_len = (max(active_indexes) + 1) if active_indexes else 1

            for idx in active_indexes:
                max_step = configs[idx].max_speed_deg_s * self.period_s
                delta = targets[idx] - self._currents[idx]
                if delta > max_step:
                    delta = max_step
                elif delta < -max_step:
                    delta = -max_step
                self._currents[idx] += delta

                pulse_us = self._angle_to_pulse_us(self._currents[idx], configs[idx])
                states[idx] = True
                fall_events.setdefault(pulse_us, []).append(idx)

            if states != self._last_states and not self._send_states(states, frame_len=active_frame_len):
                self._sleep_until_ns(cycle_start_ns + self.period_ns)
                continue

            base_ns = time.perf_counter_ns()
            for pulse_us in sorted(fall_events.keys()):
                deadline_ns = base_ns + pulse_us * 1_000
                self._sleep_until_ns(deadline_ns)
                for idx in fall_events[pulse_us]:
                    states[idx] = False
                if states != self._last_states and not self._send_states(states, frame_len=active_frame_len):
                    break

            cycle_deadline_ns = cycle_start_ns + self.period_ns
            now_ns = time.perf_counter_ns()
            if now_ns > cycle_deadline_ns:
                with self._lock:
                    self._stats["overruns"] += 1
            else:
                self._sleep_until_ns(cycle_deadline_ns)

            with self._lock:
                self._stats["cycles"] += 1
