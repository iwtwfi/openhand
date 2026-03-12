# Hand Module Layout

- Runtime code: `*.py` in this directory
- Dance runtime code: `dance/`
- Runtime configs: `hand_runtime.yaml`, `demo_gestures.yaml`
- Documentation: `docs/`
- Hardware assets/specs: `assets/`

Notes:
- This stage keeps existing hand control code paths unchanged.
- Dance module composes `DemoGesturePlayer` with beat-gated scheduling.
- Tests are still the `test_*.py` files in this directory.
- Manual initialization entry: `python3 run_hand_initialize.py`.
