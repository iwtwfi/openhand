# Hand 手势说明文档

## 1. 作用范围

本文档说明 `hand/` 目录下手势相关配置与运行行为，重点对应以下文件：

- `demo_gestures.yaml`：手势语义配置（归一化值 `u`）。
- `demo_gesture_player.py`：手势播放与运行时初始化入口。
- `hand_upper_controller.py`：`u -> angle` 映射与通道下发。
- `hand_runtime.yaml`：每通道标定与串口/调度参数。

## 2. 归一化语义

手势值统一使用 `u ∈ [0, 1]`：

- `u=0`：左右摆动自由度最左；屈伸关节最展开。
- `u=1`：左右摆动自由度最右；屈伸关节最收拢。
- 真实机械方向由 `hand_runtime.yaml` 中各通道 `calibration.reverse` 决定。

## 3. 手指自由度顺序

每个手势必须严格按以下顺序给值：

- `thumb`: `[DOF1, DOF2, DOF3, DOF4]`
- `index`: `[DOF1, DOF2, DOF3]`
- `middle`: `[DOF1, DOF2, DOF3]`
- `ring`: `[DOF1, DOF2, DOF3]`
- `little`: `[DOF1, DOF2, DOF3]`

语义定义：

- `DOF1`：左右摆动
- `DOF2`：近掌心关节屈伸
- `DOF3`：远掌心关节屈伸
- `DOF4`：拇指额外自由度

## 4. 当前可用手势

配置来源：`demo_gestures.yaml -> gestures`。

| 手势名 | 含义 |
|---|---|
| `open_hand` | 五指展开 |
| `fist` | 五指收拢 |
| `half_fist` | 半握拳（过渡姿态） |
| `point` | 食指展开，其余收拢 |
| `peace` | 食指/中指展开（V） |
| `thumbs_up` | 拇指展开，四指收拢 |
| `call_me` | 拇指+小指展开 |
| `rock` | 食指+小指展开 |
| `ok_sign` | 拇指与食指靠近，三指展开 |
| `pinch_index` | 拇指+食指捏合 |
| `pinch_middle` | 拇指+中指捏合 |
| `digit_1` | 数字 1 |
| `digit_2` | 数字 2 |
| `digit_3` | 数字 3 |
| `digit_4` | 数字 4 |
| `digit_5` | 数字 5 |

## 5. 播放器初始化流程

`DemoGesturePlayer.start()` 在连接硬件并启动调度线程后，会自动调用 `initialize_runtime()`。

初始化动作顺序：

1. 全通道到最左（`u=0.0`）
2. 等待 `hold_s`（默认 `1.0s`）
3. 全通道到最右（`u=1.0`）
4. 等待 `hold_s`
5. 全通道到中间（`u=0.5`）
6. 等待 `hold_s`

每一步下发都开启以下参数：

- `relax_after_settle=True`
- `settle_s=0.5`

即每个姿态会先给 `0.5s` 到位缓冲后自动松弛，再进入该步 `hold_s` 等待。

## 6. 运行示例

```bash
python3 hand/test_demo_gesture_player.py
```

在脚本里可直接按名称播放：

```python
from demo_gesture_player import DemoGesturePlayer

player = DemoGesturePlayer()
player.start()  # 自动执行初始化
player.play_gesture("peace", hold_ms=800, enable=True)
player.close()
```

## 7. 新增手势写法

在 `demo_gestures.yaml` 的 `gestures:` 下新增条目，结构必须完整：

```yaml
gestures:
  my_gesture:
    thumb:  [0.0, 0.0, 0.0, 0.0]
    index:  [0.0, 0.0, 0.0]
    middle: [0.0, 0.0, 0.0]
    ring:   [0.0, 0.0, 0.0]
    little: [0.0, 0.0, 0.0]
```

约束：

- 每个值必须可转为 `float`。
- 每个手指长度必须匹配自由度数量（拇指 4，其余 3）。
- 名称在 `DemoGesturePlayer.play_gesture(name)` 中按字符串精确匹配。
