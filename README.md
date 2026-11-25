# Loon Python SDK

Official Python SDK for communicating with and controlling the **Loon Industries robotic arm**.

Python APIs for both **WebSocket (WiFi)** and **Serial (USB)** communication, supporting direct joint angle commands, Cartesian pose control (Inverse Kinematics), motor homing, PID gain configuration, and real-time telemetry streaming.

---

## Features

- **Dual Transports**: Seamlessly switch between WiFi WebSocket (`ws://...`) and USB Serial (`/dev/ttyUSB0` or `COM3`).
- **Joint & IK Control**: Command direct joint angles or stream Cartesian end-effector coordinates solved by the on-board IK engine.
- **Real-Time Telemetry**: Automatically parses and tracks angles, target positions, RPM speeds, and CAN bus states.
---

## Installation

```bash
pip install loon-python-sdk
```

Or install locally in editable mode:

```bash
git clone https://github.com/LoonIndustries/loon_python_sdk.git
cd loon_python_sdk
pip install -e .
```

---

## Quickstart

### 1. Control Over WiFi (WebSocket)

```python
from loonpythonsdk import Loon5Arm

# Connect to the ESP32 access point (default: 192.168.4.1)
arm = Loon5Arm.from_websocket("ws://192.168.4.1:80/ws")
arm.start()

# 1. Command all 6 joint angles directly (degrees)
# (base, shoulder, elbow, wrist, twist, claw)
arm.set_joint_angles(base=0.0, shoulder=20.0, elbow=45.0, wrist=-15.0, twist=0.0, claw=50.0)

# 2. Command an individual motor angle
arm.set_angle(can_id=6, degrees=70.0)  # Open claw

# 3. Disconnect
arm.close()
```

### 2. Control Over USB (Serial)

```python
from loonpythonsdk import Loon5Arm

# Connect via USB serial
arm = Loon5Arm.from_serial("/dev/ttyUSB0", baudrate=115200)
arm.start()

# Home arm motors 2, 3, and 4 in sequence
arm.home_arm()

arm.close()
```

### 3. Cartesian Pose Control (Inverse Kinematics)

```python
# Command end-effector pose (x, y, z, roll, pitch, yaw, grip)
# The ESP32's on-board IK solver computes target joint angles automatically
arm.set_pose(x=200.0, y=0.0, z=150.0, roll=0.0, pitch=15.0, yaw=0.0, grip=30.0)
```

### 4. Listening to Real-Time Telemetry

```python
def on_telemetry(motors):
    for m in motors:
        print(f"Motor {m['can_id']}: pos={m['position_deg']:.1f}°, speed={m['speed_rpm']} RPM")

arm = Loon5Arm.from_websocket("ws://192.168.4.1:80/ws", on_telemetry=on_telemetry)
arm.start()
```

---

## License

This project is licensed under the [Apache-2.0 License](LICENSE).
