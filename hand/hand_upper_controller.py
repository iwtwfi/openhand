#!/usr/bin/env python3
"""五指上层抽象控制层。

职责：
1. 对外暴露手指语义接口（单关节 / 单手指 / 整手）。
2. 将上层归一化输入 u(0~1) 映射为具体角度（degree）。
3. 将角度批量下发给 Servo16Manager（由下层线程完成真实发送）。

边界：
1. 本层不负责串口连接与线程生命周期管理。
2. 本层不做脉宽计算，脉宽映射由 Servo16Manager 负责。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple

from servo16_manager import Servo16Manager


FingerName = str


@dataclass(frozen=True)
class JointCalibration:
    """单关节标定参数。

    deg_min / deg_max:
        该关节允许的角度范围（单位：度）。
    reverse:
        是否反向映射。True 时 u=0 对应 deg_max，u=1 对应 deg_min。
    offset_deg:
        零位偏移补偿（单位：度），在映射后叠加。
    """

    deg_min: float
    deg_max: float
    reverse: bool
    offset_deg: float


class HandUpperController:
    """五指语义控制器（上层）。

    说明：
    1. 通过固定手指-通道映射将语义动作转换为通道动作。
    2. 所有配置（尤其是 calibration）只从 config 读取，不接受代码覆盖。
    """

    CHANNEL_COUNT = 16
    FINGER_CHANNELS: Mapping[FingerName, Tuple[int, ...]] = {
        "thumb": (1, 2, 3, 4),
        "index": (5, 6, 7),
        "middle": (8, 9, 10),
        "ring": (11, 12, 13),
        "little": (14, 15, 16),
    }

    def __init__(
        self,
        manager: Servo16Manager,
        config: Mapping[str, Any],
    ) -> None:
        """初始化上层控制器。

        参数：
            manager: 已创建好的 16 路调度器实例。
            config: 运行配置字典，必须包含 calibration 段。
        """
        self.manager = manager
        # 读取并固化每路关节标定参数。
        self.calibration_by_channel = dict(self._parse_calibration_from_config(config))
        # 启动阶段即做一次严格校验，尽早发现配置问题。
        self._validate_calibration()

    def set_joint_u(
        self,
        channel: int,
        u: float,
        enable: bool = True,
        settle_s: float | None = None,
        relax_after_settle: bool = False,
    ) -> None:
        """设置单关节归一化目标。

        参数：
            channel: 通道号（1~16）。
            u: 归一化目标值，建议范围 [0, 1]（内部会裁剪）。
            enable: 是否使能该通道输出。False 时会主动关闭该通道。
            settle_s: 到位等待时间（秒）。仅在 relax_after_settle=True 且 enable=True 时生效。
            relax_after_settle: True 时会在等待后自动关闭该通道输出。
        """
        self._assert_channel(channel)
        updates = self._build_updates({channel: u})
        if updates:
            if enable and relax_after_settle:
                self.manager.set_targets_and_relax(
                    updates,
                    settle_s=0.5 if settle_s is None else float(settle_s),
                )
            else:
                self.manager.set_targets(updates, enable=enable)
        if not enable:
            self.manager.set_channel_enabled(channel, False)

    def set_finger_u(
        self,
        finger: FingerName,
        u_list: Sequence[float],
        enable: bool = True,
        settle_s: float | None = None,
        relax_after_settle: bool = False,
    ) -> None:
        """设置单个手指的归一化目标。

        参数：
            finger: 手指名（thumb/index/middle/ring/little）。
            u_list: 该手指各自由度的目标列表。
                    thumb 必须 4 个值，其余手指必须 3 个值。
            enable: 是否使能该手指对应通道输出。
            settle_s: 到位等待时间（秒）。仅在 relax_after_settle=True 且 enable=True 时生效。
            relax_after_settle: True 时会在等待后自动关闭该手指对应通道输出。
        """
        channels = self._finger_channels(finger)
        if len(u_list) != len(channels):
            raise ValueError(f"{finger} expects {len(channels)} values, got {len(u_list)}")
        # 将该手指每个自由度与对应通道配对后统一下发。
        updates = self._build_updates({ch: u for ch, u in zip(channels, u_list)})
        if updates:
            if enable and relax_after_settle:
                self.manager.set_targets_and_relax(
                    updates,
                    settle_s=0.5 if settle_s is None else float(settle_s),
                )
            else:
                self.manager.set_targets(updates, enable=enable)
        if not enable:
            for ch in channels:
                self.manager.set_channel_enabled(ch, False)

    def set_hand_u(
        self,
        hand_u_map: Mapping[int, float],
        enable: bool = True,
        settle_s: float | None = None,
        relax_after_settle: bool = False,
    ) -> None:
        """设置整手/多通道归一化目标。

        参数：
            hand_u_map: {channel: u} 的映射，支持一次更新多路。
            enable: 是否使能这些通道输出。False 时会关闭传入的对应通道。
            settle_s: 到位等待时间（秒）。仅在 relax_after_settle=True 且 enable=True 时生效。
            relax_after_settle: True 时会在等待后自动关闭本次传入通道输出。
        """
        updates = self._build_updates(hand_u_map)
        if updates:
            if enable and relax_after_settle:
                self.manager.set_targets_and_relax(
                    updates,
                    settle_s=0.5 if settle_s is None else float(settle_s),
                )
            else:
                self.manager.set_targets(updates, enable=enable)
        if not enable:
            for ch in hand_u_map.keys():
                self._assert_channel(ch)
                self.manager.set_channel_enabled(ch, False)

    def _build_updates(self, u_map: Mapping[int, float]) -> Dict[int, float]:
        """将 {channel: u} 转换为 {channel: angle_deg}。

        这是上层的核心转换过程，不直接发送串口帧：
        1. 校验通道号。
        2. 将 u 裁剪到 [0, 1]。
        3. 依据 calibration 映射到角度。
        """
        updates: Dict[int, float] = {}

        for ch, raw_u in u_map.items():
            self._assert_channel(ch)
            u = self._clip01(float(raw_u))
            angle = self._u_to_angle(ch, u)
            updates[ch] = angle

        return updates

    def _u_to_angle(self, channel: int, u: float) -> float:
        """单通道 u->角度映射。

        映射公式：
            angle = deg_min + u * (deg_max - deg_min) + offset_deg
        若 reverse=True，则先将 u 变换为 (1-u)。
        最终会再次限制在 [deg_min, deg_max] 内，防止越界。
        """
        cal = self.calibration_by_channel[channel]
        uu = self._clip01(u)
        if cal.reverse:
            uu = 1.0 - uu
        angle = cal.deg_min + uu * (cal.deg_max - cal.deg_min) + cal.offset_deg
        return max(cal.deg_min, min(cal.deg_max, angle))

    @classmethod
    def _parse_calibration_from_config(
        cls,
        config: Mapping[str, Any],
    ) -> Dict[int, JointCalibration]:
        """从配置读取 16 路标定参数。

        要求：
        1. config.calibration 必须存在且为映射。
        2. 1~16 每一路都必须有配置。
        3. 每路必须提供 deg_min/deg_max/reverse/offset_deg。
        """
        calibration_cfg = config.get("calibration")
        if not isinstance(calibration_cfg, Mapping):
            raise ValueError("config.calibration must be a mapping")

        result: Dict[int, JointCalibration] = {}
        for ch in range(1, cls.CHANNEL_COUNT + 1):
            item = calibration_cfg.get(str(ch))
            if not isinstance(item, Mapping):
                item = calibration_cfg.get(ch)
            if not isinstance(item, Mapping):
                raise ValueError(f"config.calibration.{ch} must be a mapping")
            try:
                deg_min = float(item["deg_min"])
                deg_max = float(item["deg_max"])
                reverse = bool(item["reverse"])
                offset_deg = float(item["offset_deg"])
            except KeyError as exc:
                raise ValueError(f"config.calibration.{ch} missing field: {exc}") from exc

            result[ch] = JointCalibration(
                deg_min=deg_min,
                deg_max=deg_max,
                reverse=reverse,
                offset_deg=offset_deg,
            )
        return result

    def _validate_calibration(self) -> None:
        """校验标定完整性与合法性。"""
        missing = [ch for ch in range(1, self.CHANNEL_COUNT + 1) if ch not in self.calibration_by_channel]
        if missing:
            raise ValueError(f"missing calibration channels: {missing}")
        for ch, cal in self.calibration_by_channel.items():
            self._assert_channel(ch)
            if cal.deg_max <= cal.deg_min:
                raise ValueError(f"invalid calibration at channel {ch}: deg_max <= deg_min")

    def _finger_channels(self, finger: FingerName) -> Tuple[int, ...]:
        """按手指名返回通道序列。"""
        try:
            return self.FINGER_CHANNELS[finger]
        except KeyError as exc:
            support = ", ".join(sorted(self.FINGER_CHANNELS.keys()))
            raise ValueError(f"invalid finger={finger}, supported: {support}") from exc

    @staticmethod
    def _clip01(v: float) -> float:
        """将值裁剪到 [0, 1]。"""
        return max(0.0, min(1.0, v))

    @staticmethod
    def _assert_channel(channel: int) -> None:
        """校验通道号是否合法（1~16）。"""
        if not (1 <= channel <= HandUpperController.CHANNEL_COUNT):
            raise ValueError("channel must be in 1..16")
