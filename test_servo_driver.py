#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""舵机驱动测试：让信号口1舵机往返运动。"""

import time

from hand_low_level_driver import GPIO16Controller
from servo_driver import ServoController


def main() -> None:
    print("=" * 70)
    print("  舵机测试（信号口1） - 往返运动")
    print("=" * 70)
    print("说明：按 Ctrl+C 结束测试")

    controller = GPIO16Controller(
        port="/dev/ttyUSB0",  # 请按实际串口修改
        baudrate=115200,
        timeout=0.3,
    )

    if not controller.connect():
        print("\n✗ 无法连接到串口设备，请检查端口和权限")
        return

    servo = ServoController(controller, channel=1, verbose=False)
    step_angles = list(range(0, 181, 15))

    try:
        print("\n[*] 开始往返扫动：0° -> 180° -> 0°")
        while True:
            for angle in step_angles:
                print(f"→ 当前目标角度: {angle:3d}°")
                servo.hold_angle(angle, duration_s=0.05)
            time.sleep(1)

            for angle in reversed(step_angles):
                print(f"→ 当前目标角度: {angle:3d}°")
                servo.hold_angle(angle, duration_s=0.05)
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n用户中断操作")
    finally:
        print("\n[*] 关闭舵机信号并断开串口...")
        servo.release()
        controller.disconnect()
        print("程序已退出")


if __name__ == "__main__":
    main()
