#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hand 底层驱动文件：仅包含 3B 连续批量写驱动。"""

from typing import List, Optional

import serial


class GPIO16Controller:
    """16 路 GPIO 控制器底层驱动（仅实现 3B 指令）。"""

    CMD_WRITE_CONTINUOUS = 0x3B

    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200, timeout: float = 0.3):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser: Optional[serial.Serial] = None

    def connect(self) -> bool:
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
            )
            print(f"✓ 串口连接成功: {self.port} @ {self.baudrate}bps")
            return True
        except serial.SerialException as e:
            print(f"✗ 串口连接失败: {e}")
            return False

    def disconnect(self) -> None:
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("✓ 串口已断开")

    def _ensure_connected(self) -> bool:
        if not self.ser or not self.ser.is_open:
            print("✗ 错误：串口未连接")
            return False
        return True

    def _build_3b_frame(self, gpio_states: List[bool]) -> bytes:
        """构建 3B 连续控制帧：3B V1 V2 ... Vn（n=1~16）"""
        if not (1 <= len(gpio_states) <= 16):
            raise ValueError("gpio_states 长度必须在 1-16")
        return bytes([self.CMD_WRITE_CONTINUOUS] + [0x01 if s else 0x00 for s in gpio_states])

    def set_gpio_batch(self, gpio_states: List[bool]) -> bool:
        """发送 3B 连续批量控制指令。"""
        if not self._ensure_connected():
            return False

        try:
            frame = self._build_3b_frame(gpio_states)
            print(f"→ 发送 3B 连续写帧: {frame.hex(' ').upper()}")
            self.ser.reset_input_buffer()
            self.ser.write(frame)
            print(f"✓ 已下发 {len(gpio_states)} 路连续写指令")
            return True
        except Exception as e:
            print(f"✗ 发送失败: {e}")
            return False
