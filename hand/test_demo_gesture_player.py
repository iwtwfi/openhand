#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DemoGesturePlayer 单手势播放测试。"""

from __future__ import annotations

import time

from demo_gesture_player import DemoGesturePlayer


def main() -> None:
    """手势播放测试入口（连续两个明显姿态）。"""
    player = DemoGesturePlayer()
    try:
        player.start()
        print("play: open_hand")
        player.play_gesture(
            "open_hand",
            hold_ms=5000,
            enable=True,
            settle_s=1.0,
            relax_after_settle=True,
        )
        print("play: fist")
        player.play_gesture(
            "peace",
            hold_ms=5000,
            enable=True,
            settle_s=1.0,
            relax_after_settle=True,
        )
        print("play: open_hand")
        player.play_gesture(
            "open_hand",
            hold_ms=5000,
            enable=True,
            settle_s=1.0,
            relax_after_settle=True,
        )
    finally:
        player.close()


if __name__ == "__main__":
    main()
