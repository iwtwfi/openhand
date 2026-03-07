#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
024 十六路GPIO读写模块 - 仅 3B 连续批量控制示例
=====================================
支持功能：
1. 连续批量控制 GPIO（3B 指令）

硬件连接：
- USB 转 TTL 串口模块连接至电脑
- 波特率：115200
- 数据位：8，停止位：1，校验：无

作者：Assistant
日期：2026-03-06
"""

import serial
import time
from typing import List, Optional


class GPIO16Controller:
    """
    16路GPIO控制器类（仅实现 3B 指令）。
    """

    # 协议常量定义
    CMD_WRITE_CONTINUOUS = 0x3B

    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200, timeout: float = 0.3):
        """
        初始化GPIO控制器

        参数:
            port: 串口设备路径，如 "/dev/ttyUSB0" (Linux) 或 "COM4" (Windows)
            baudrate: 波特率，默认 115200
            timeout: 串口读写超时时间，单位秒，默认 0.3秒
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser: Optional[serial.Serial] = None

    def connect(self) -> bool:
        """
        连接串口设备

        返回:
            True: 连接成功
            False: 连接失败（会打印错误信息）
        """
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout
            )
            print(f"✓ 串口连接成功: {self.port} @ {self.baudrate}bps")
            return True
        except serial.SerialException as e:
            print(f"✗ 串口连接失败: {e}")
            return False

    def disconnect(self) -> None:
        """断开串口连接"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("✓ 串口已断开")

    def _build_3b_frame(self, gpio_states: List[bool]) -> bytes:
        """
        构建 3B 连续控制帧
        格式: 3B V1 V2 ... Vn (n=1~16, V1 对应 GPIO1)
        """
        if not (1 <= len(gpio_states) <= 16):
            raise ValueError("gpio_states 长度必须在 1-16")
        return bytes([self.CMD_WRITE_CONTINUOUS] + [0x01 if s else 0x00 for s in gpio_states])

    def _ensure_connected(self) -> bool:
        if not self.ser or not self.ser.is_open:
            print("✗ 错误：串口未连接")
            return False
        return True

    def set_gpio_batch(self, gpio_states: List[bool]) -> bool:
        """
        连续批量写 GPIO（3B）
        - gpio_states 长度 1~16
        - 第1个元素对应 GPIO1
        """
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


def demo_batch_control(controller: GPIO16Controller):
    """
    演示 3B 连续批量控制
    """
    print("\n" + "="*60)
    print("演示：连续批量控制GPIO（3B协议）")
    print("="*60)

    # 示例1：设置通道1、5、10为高电平，其他为低电平
    print("\n[示例1] 设置通道 1、5、10 为高电平，其他为低电平")
    states = [False] * 16
    states[0] = True   # 通道1
    states[4] = True   # 通道5
    states[9] = True   # 通道10

    print(f"目标状态: {['H' if s else 'L' for s in states]}")
    print("组帧过程:")
    print("  1. 帧头: 0x3B")
    print("  2. 后续16字节: GPIO1~GPIO16 电平值(0/1)")
    success = controller.set_gpio_batch(states)
    if success:
        print("✓ 批量控制成功执行！")

    time.sleep(1)

    # # 示例2：跑马灯效果 - 轮流点亮每一路
    # print("\n" + "-"*60)
    # print("[示例2] 跑马灯效果 - 轮流点亮每一路GPIO")
    # print("-"*60)

    # for i in range(16):
    #     states = [False] * 16
    #     states[i] = True  # 点亮第i路
    #     print(f"点亮通道 {i+1:2d}: {'H' if states[i] else 'L'}", end="  ")

    #     success = controller.set_gpio_batch(states)
    #     if success:
    #         print("✓")
    #     else:
    #         print("✗")

    #     time.sleep(0.2)  # 200ms延迟

    # print("\n跑马灯演示完成！")

    # # 示例3：全部关闭
    # print("\n" + "-"*60)
    # print("[示例3] 关闭所有16路GPIO")
    # print("-"*60)
    # states = [False] * 16
    # print(f"目标状态: 全部低电平 (LLLL LLLL LLLL LLLL)")
    # success = controller.set_gpio_batch(states)
    # if success:
    #     print("✓ 所有GPIO已关闭")



def main():
    """
    主函数 - 演示16路GPIO控制器的使用
    """
    print("="*70)
    print("  024 十六路GPIO读写模块 - Python控制示例（仅3B）")
    print("="*70)
    print()
    print("本程序只使用 3B 连续写协议控制 GPIO")
    print()

    # 创建控制器实例
    # 注意：根据实际串口修改端口名称
    # Linux: /dev/ttyUSB0 或 /dev/ttyACM0
    # Windows: COM3, COM4 等
    controller = GPIO16Controller(
        port="/dev/ttyUSB0",  # 请根据实际串口修改
        baudrate=115200,
        timeout=0.3
    )

    # 连接串口
    if not controller.connect():
        print("\n✗ 无法连接到串口设备，请检查：")
        print("  1. 串口线是否连接正确")
        print("  2. 串口名称是否正确（当前设置: /dev/ttyUSB0）")
        print("  3. 是否有权限访问串口（尝试 sudo 运行）")
        return

    try:
        # 演示连续批量控制（3B）
        demo_batch_control(controller)

    except KeyboardInterrupt:
        print("\n\n用户中断操作")
    finally:
        # # 关闭所有GPIO（安全状态）
        # print("\n[*] 正在关闭所有GPIO...")
        # controller.set_gpio_batch([False] * 16)

        # 断开串口
        controller.disconnect()
        print("\n程序已退出")


if __name__ == "__main__":
    main()
