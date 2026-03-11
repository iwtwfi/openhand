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
        baudrate=2000000,
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
    try:
        manager.start()
        print("\n[*] 开始往返：CH1~CH4 同步（参数与 test_servo_driver.py 一致）")
        while True:
            for channel in channels:
                manager.set_channel_enabled(channel, True)
            print("→ CH1~CH4 目标角度:   0°")
            manager.set_targets({channel: 0 for channel in channels}, enable=True)
            time.sleep(1.0)

            for channel in channels:
                manager.set_channel_enabled(channel, False)
            time.sleep(1.0)

            for channel in channels:
                manager.set_channel_enabled(channel, True)
            print("→ CH1~CH4 目标角度: 180°")
            manager.set_targets({channel: 180 for channel in channels}, enable=True)
            time.sleep(1.0)

            for channel in channels:
                manager.set_channel_enabled(channel, False)
            time.sleep(1.0)
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
