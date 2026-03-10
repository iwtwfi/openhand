#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""舵机管理器测试：仅 CH1~CH4 同步扫动。"""

import time

from hand_low_level_driver import GPIO16Controller
from servo16_manager import Servo16Manager


def main() -> None:
    print("=" * 70)
    print("  舵机管理器测试（仅 CH1~CH4 同步）")
    print("=" * 70)
    print("说明：按 Ctrl+C 结束测试")

    controller = GPIO16Controller(
        port="/dev/ttyUSB0",  # 请按实际串口修改
        baudrate=921600,
        timeout=0.3,
    )

    if not controller.connect():
        print("\n✗ 无法连接到串口设备，请检查端口和权限")
        return

    manager = Servo16Manager(
        gpio=controller,
        period_s=0.020,
        quantize_us=100,
        verbose=False,
    )

    channels = [1, 2, 3, 4,5,6,7,8,9,10,11,12,13,14,15,16]
    for channel in channels:
        manager.set_channel_config(
            channel=channel,
            enabled=True,
            min_pulse_us=500,
            max_pulse_us=2500,
        )
    step_angles = list(range(0, 181, 15))

    try:
        manager.start()
        print("\n[*] 开始往返：CH1~CH4 同步（参数与 test_servo_driver.py 一致）")
        while True:
            for channel in channels:
                manager.set_channel_enabled(channel, True)
            for angle in step_angles:
                print(f"→ CH1~CH4 目标角度: {angle:3d}°")
                manager.set_targets({channel: angle for channel in channels}, enable=True)
                time.sleep(0.05)

            for channel in channels:
                manager.set_channel_enabled(channel, False)
            time.sleep(1)

            for channel in channels:
                manager.set_channel_enabled(channel, True)
            for angle in reversed(step_angles):
                print(f"→ CH1~CH4 目标角度: {angle:3d}°")
                manager.set_targets({channel: angle for channel in channels}, enable=True)
                time.sleep(0.05)

            for channel in channels:
                manager.set_channel_enabled(channel, False)
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n用户中断操作")
    finally:
        print("\n[*] 停止调度并断开串口...")
        manager.stop()
        controller.disconnect()
        print(f"统计: {manager.get_stats()}")
        print("程序已退出")


if __name__ == "__main__":
    main()
