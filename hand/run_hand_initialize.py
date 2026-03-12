#!/usr/bin/env python3
"""Manual hand initialization entrypoint.

Usage:
  python3 run_hand_initialize.py
  python3 run_hand_initialize.py --hold-s 1.2
"""

from __future__ import annotations

import argparse

from demo_gesture_player import DemoGesturePlayer


def main() -> None:
    parser = argparse.ArgumentParser(description="Run hand initialization sequence once")
    parser.add_argument("--hold-s", type=float, default=2.0, help="Hold time for each init pose")
    args = parser.parse_args()

    player = DemoGesturePlayer()
    try:
        player.start()
        player.initialize_runtime(hold_s=args.hold_s, force=True)
        print("manual initialization finished")
    finally:
        player.close()


if __name__ == "__main__":
    main()
