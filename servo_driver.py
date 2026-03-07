#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""舵机上层驱动：基于 hand 底层 3B 指令实现软件 PWM。"""

import time

from hand_low_level_driver import GPIO16Controller


class ServoController:
    """将角度映射为 PWM 脉宽并输出到指定 GPIO 通道。"""

    def __init__(
        self,
        gpio: GPIO16Controller,
        channel: int = 1,
        period_s: float = 0.020,
        min_pulse_s: float = 0.0005,
        max_pulse_s: float = 0.0025,
        verbose: bool = False,
    ):
        if not (1 <= channel <= 16):
            raise ValueError("channel 必须在 1~16")
        if period_s <= 0:
            raise ValueError("period_s 必须大于 0")
        if not (0 < min_pulse_s < max_pulse_s < period_s):
            raise ValueError("脉宽/周期参数非法，请满足 0 < min < max < period")

        self.gpio = gpio
        self.channel = channel
        self.period_s = period_s
        self.min_pulse_s = min_pulse_s
        self.max_pulse_s = max_pulse_s
        self.verbose = verbose

        self._high_states = [False] * channel
        self._low_states = [False] * channel
        self._high_states[channel - 1] = True

    @staticmethod
    def _clamp_angle(angle_deg: float) -> float:
        return max(0.0, min(180.0, angle_deg))

    def angle_to_pulse_width(self, angle_deg: float) -> float:
        """角度(0~180) -> 脉宽秒数(0.5ms~2.5ms)。"""
        angle = self._clamp_angle(angle_deg)
        ratio = angle / 180.0
        return self.min_pulse_s + ratio * (self.max_pulse_s - self.min_pulse_s)

    def _write_level(self, high: bool) -> None:
        states = self._high_states if high else self._low_states
        ok = self.gpio.set_gpio_batch(states, verbose=self.verbose)
        if not ok:
            raise RuntimeError("GPIO 写入失败")

    def output_pwm_cycle(self, angle_deg: float) -> None:
        """输出 1 个 20ms PWM 周期。"""
        pulse_width = self.angle_to_pulse_width(angle_deg)
        cycle_start = time.perf_counter()

        self._write_level(True)
        time.sleep(pulse_width)
        self._write_level(False)

        elapsed = time.perf_counter() - cycle_start
        remain = self.period_s - elapsed
        if remain > 0:
            time.sleep(remain)

    def hold_angle(self, angle_deg: float, duration_s: float) -> None:
        """在给定时长内持续输出目标角度 PWM。"""
        if duration_s <= 0:
            return

        end_time = time.perf_counter() + duration_s
        while time.perf_counter() < end_time:
            self.output_pwm_cycle(angle_deg)

    def release(self) -> None:
        """释放舵机信号，输出低电平。"""
        self._write_level(False)
