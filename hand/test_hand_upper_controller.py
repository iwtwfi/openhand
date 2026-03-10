#!/usr/bin/env python3
"""16 路手部控制独立运行入口。

本文件职责：
1. 读取 YAML 配置并做基础结构校验。
2. 初始化串口驱动与 16 路调度器。
3. 创建上层语义控制器（HandUpperController）。
4. 启动调度线程并保持主循环存活，等待外部控制逻辑调用上层接口。
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from hand_low_level_driver import GPIO16Controller
from hand_upper_controller import HandUpperController
from servo16_manager import Servo16Manager

try:
    import yaml
except ModuleNotFoundError as exc:
    raise SystemExit("missing dependency: pyyaml (pip install pyyaml)") from exc

CONFIG_PATH = Path(__file__).with_name("hand_runtime.yaml")


def _require_dict(root: dict[str, Any], key: str) -> dict[str, Any]:
    """确保配置根节点下的指定字段是字典。"""
    value = root.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"config.{key} must be a mapping")
    return value


def load_config(path: str) -> dict[str, Any]:
    """加载 YAML 配置文件并返回字典。"""
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"config file not found: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("config root must be a mapping")
    return data


def main() -> None:
    """运行主流程：加载配置 -> 初始化 -> 启动循环 -> 安全退出。"""
    # 1) 读取整份配置（下层与上层共享同一份配置源）。
    cfg = load_config(str(CONFIG_PATH))
    # 2) 主程序只关心串口、调度、空转节拍这三段。
    serial_cfg = _require_dict(cfg, "serial")
    manager_cfg = _require_dict(cfg, "manager")
    runtime_cfg = _require_dict(cfg, "runtime")

    # 3) 初始化串口底层驱动。
    controller = GPIO16Controller(
        port=str(serial_cfg["port"]),
        baudrate=int(serial_cfg["baudrate"]),
        timeout=float(serial_cfg["timeout"]),
    )
    if not controller.connect():
        print("failed to connect serial device")
        return

    # 4) 初始化 16 路调度器（真实输出由其后台线程执行）。
    manager = Servo16Manager(
        gpio=controller,
        period_s=float(manager_cfg["period_s"]),
        quantize_us=int(manager_cfg["quantize_us"]),
        verbose=bool(manager_cfg["verbose"]),
    )

    # 5) 初始化上层语义控制器（在内部解析 calibration）。
    upper = HandUpperController(
        manager=manager,
        config=cfg,
    )
    # 主线程空转周期，只用于保持进程与轮询等待。
    idle_sleep_s = float(runtime_cfg["idle_sleep_s"])

    try:
        # 6) 启动下层调度线程。
        manager.start()
        print("runtime started, waiting for external controller, press Ctrl+C to exit")
        while True:
            # 7) 主循环不直接下发动作，仅等待外部逻辑调用：
            #    upper.set_joint_u / upper.set_finger_u / upper.set_hand_u
            upper.set_finger_u(
                finger="thumb",
                u_list=[0.0, 0.0, 0.5, 0.5],
                enable=True,
                settle_s=0.5,
                relax_after_settle=True,
            )
            time.sleep(idle_sleep_s)
    except KeyboardInterrupt:
        print("stopped by user")
    finally:
        # 8) 统一收尾：关闭输出、停止调度线程、断开串口并打印统计。
        manager.set_all_enabled(False)
        manager.stop()
        controller.disconnect()
        print(f"stats: {manager.get_stats()}")


if __name__ == "__main__":
    main()
