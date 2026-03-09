#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DemoGesturePlayer 单手势播放测试。"""

from __future__ import annotations

from demo_gesture_player import DemoGesturePlayer

CONFIG_PATH = "hand_runtime.yaml"
DEMO_PATH = "demo_gestures.yaml"

def main() -> None:
    """单手势播放测试入口。"""
    player = DemoGesturePlayer(CONFIG_PATH, DEMO_PATH)
    try:
        player.start()
        player.play_gesture("digit_1", transition_ms=300, hold_ms=300, enable=True)
        stats = player.get_stats()
        assert isinstance(stats, dict), "stats 应为字典"
    finally:
        player.close()


if __name__ == "__main__":
    main()
