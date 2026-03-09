# 五指上层抽象与主程序独立运行方案

## 1. 目标与边界

本方案将系统拆成三层：

1. 底层驱动层：`hand_low_level_driver.py`，负责串口连接与 3B 帧发送。
2. 调度层：`servo16_manager.py`，负责 16 路软件 PWM 实时调度与下发。
3. 上层抽象层（建议新建）：负责五指语义控制、归一化输入映射与关节标定。

边界约束：

1. 上层抽象层不负责 `connect/start/stop/disconnect` 生命周期。
2. 主程序独立负责启动与退出流程。
3. 上层只覆盖目标数据；真实发送由 `Servo16Manager` 调度线程执行。

---

## 2. 五指与通道映射

### 2.1 自由度定义

1. 拇指：4 自由度。
2. 其余四指：每指 3 自由度。
3. 每指通用语义：
   - `DOF1`：左右摆动（外展/内收）。
   - `DOF2`：近掌心关节（近端屈伸）。
   - `DOF3`：远掌心关节（远端屈伸）。
4. 拇指额外：
   - `DOF4`：拇指额外自由度（例如对掌/旋转，按机构定义）。

### 2.2 固定通道编号

1. 拇指：`CH1-CH4`（`DOF1, DOF2, DOF3, DOF4`）
2. 食指：`CH5-CH7`（`DOF1, DOF2, DOF3`）
3. 中指：`CH8-CH10`（`DOF1, DOF2, DOF3`）
4. 无名指：`CH11-CH13`（`DOF1, DOF2, DOF3`）
5. 小指：`CH14-CH16`（`DOF1, DOF2, DOF3`）

建议将映射表做成常量，禁止在业务逻辑中散落硬编码通道号。

---

## 3. 上层输入与标定

### 3.1 统一输入

上层控制输入统一为归一化值 `u ∈ [0, 1]`：

1. `u=0` 语义定义：
   - 左右摆动自由度处于最左侧。
   - 屈伸关节处于最展开状态。
2. `u=1` 语义定义：
   - 左右摆动自由度处于最右侧。
   - 屈伸关节处于最收拢状态。
3. 通过每路 calibration 的 `deg_min/deg_max/reverse` 将上述统一语义映射到真实机械方向。

### 3.2 每关节 Calibration（必须按关节配置）

每个关节独立维护以下参数：

1. `deg_min`：最小安全角度。
2. `deg_max`：最大安全角度。
3. `reverse`：方向是否反转。
4. `offset_deg`：零位修正（可选）。

说明：

1. 这是“每个关节一套”，不是“每根手指一套”。
2. 目标是吸收装配偏差、避免机械撞限位、统一动作语义。

### 3.3 映射规则

对每个关节执行：

1. `u = clip(u, 0, 1)`
2. 如果 `reverse=True`，则 `u = 1 - u`
3. `angle_deg = deg_min + u * (deg_max - deg_min) + offset_deg`
4. 再对 `angle_deg` 做安全裁剪（确保不越界）

上层只做 `u -> angle_deg`，不做脉宽转换；脉宽映射由 `Servo16Manager` 完成。

---

## 4. 上层接口设计

建议提供以下核心接口：

1. `set_joint_u(joint_id, u)`
   - 用途：单关节调试、标定、微调。
   - 行为：仅覆盖该关节目标。
2. `set_finger_u(finger_id, u_list)`
   - 用途：单指动作控制。
   - 约束：拇指长度为 4，其余手指长度为 3。
   - 行为：覆盖该手指所有关节目标。
3. `set_hand_u(hand_u_map)`
   - 用途：整手联动、手势切换。
   - 行为：将多关节更新聚合成同一帧目标并批量下发，优先保证同步性。

---

## 5. 上层策略

当前实现不包含防抖状态机，保持最小语义：

1. 输入 `u` 直接映射到角度并限幅。
2. `enable=False` 时关闭对应通道。
3. 同步动作通过批量 `set_targets(...)` 实现。

---

## 6. 与 Servo16Manager 的交互原则

统一原则：上层覆盖目标，下层调度发送。

1. 上层通过 `set_targets(...)` 写入目标角度缓存。
2. 上层通过 `set_channel_enabled(...)` 控制关节输出使能。
3. 串口发包由 `Servo16Manager.start()` 启动的调度线程周期执行。

因此，上层所有接口都应设计为“状态更新接口”，而非“立即发送接口”。

---

## 7. 主程序独立方案

建议新建主程序文件（例如：`main_hand_runtime.py`），仅负责生命周期和业务编排。

### 7.1 启动阶段

1. 加载配置：
   - 串口参数（port/baudrate/timeout）
   - 通道映射表（代码常量）
   - 16 关节 calibration
2. 创建并连接 `GPIO16Controller`。
3. 创建 `Servo16Manager(period_s=0.020, quantize_us=100)`。
4. 调用 `manager.start()` 启动调度线程。
5. 创建上层控制器（注入 `manager + 配置`）。
6. 下发安全初始姿态（可选）。

### 7.2 运行阶段

1. 主循环接收外部输入（UI、脚本、算法输出等）。
2. 调用上层接口：
   - 单关节：`set_joint_u`
   - 单手指：`set_finger_u`
   - 整手联动：`set_hand_u`（推荐）
3. 上层完成映射，再批量写入目标。
4. 下层线程按周期持续执行发送。

### 7.3 退出阶段

1. 停止接收新命令。
2. 统一 disable 或回安全姿态后 disable。
3. `manager.stop()`
4. `controller.disconnect()`
5. 读取并记录 `manager.get_stats()`。

---

## 8. 落地优先级

建议按以下顺序实现：

1. 先做：映射表 + calibration 数据结构 + 三个核心接口。
2. 再做：手势播放与轨迹插值（例如线性/S 曲线）。

这样可以先快速打通可控链路，再逐步提升稳定性和动作质量。

---

## 9. 参考实现文件（已落地）

1. `hand_upper_controller.py`
   - 提供 `JointCalibration`、`HandUpperController`
   - `HandUpperController.__init__` 必须接收整份配置并自动解析 calibration
   - 不支持代码侧覆盖配置，所有参数仅来自 YAML
   - 实现 `set_joint_u` / `set_finger_u` / `set_hand_u`
2. `main_hand_runtime.py`
   - 独立主程序入口
   - 从 YAML 读取全部配置，负责 connect/start/loop/stop 生命周期
   - 提供空运行骨架，等待外部控制器调用上层接口
3. `hand_runtime.yaml`
   - 统一配置文件（serial / manager / runtime / calibration）

运行命令示例：

```bash
python3 main_hand_runtime.py --config hand_runtime.yaml
```

说明：`--config` 为必填参数，不传会直接报错退出。
