#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3B 指令测试文件：仅保留 demo 与 main。"""

import time

from hand_low_level_driver import GPIO16Controller


def demo_batch_control(controller: GPIO16Controller) -> None:
    """演示 3B 连续批量控制。"""
    print("\n" + "=" * 60)
    print("演示：连续批量控制GPIO（3B协议）")
    print("=" * 60)

    print("\n[示例1] 设置通道 1、5、10 为高电平，其他为低电平")
    states = [False] * 16
    states[0] = True
    states[4] = True
    states[9] = True

    print(f"目标状态: {['H' if s else 'L' for s in states]}")
    print("组帧过程:")
    print("  1. 帧头: 0x3B")
    print("  2. 后续16字节: GPIO1~GPIO16 电平值(0/1)")
    success = controller.set_gpio_batch(states)
    if success:
        print("✓ 批量控制成功执行！")

    time.sleep(1)


def main() -> None:
    print("=" * 70)
    print("  024 十六路GPIO读写模块 - 测试文件（仅3B）")
    print("=" * 70)
    print()
    print("本程序通过 hand 底层驱动文件调用 3B 连续写协议")
    print()

    controller = GPIO16Controller(
        port="/dev/ttyUSB0",  # 请按实际串口修改
        baudrate=2000000,
        timeout=0.3,
    )

    if not controller.connect():
        print("\n✗ 无法连接到串口设备，请检查端口和权限")
        return

    try:
        demo_batch_control(controller)
    except KeyboardInterrupt:
        print("\n\n用户中断操作")
    finally:
        print("\n[*] 正在关闭所有GPIO...")
        controller.set_gpio_batch([False] * 16)
        controller.disconnect()
        print("\n程序已退出")


if __name__ == "__main__":
    main()
