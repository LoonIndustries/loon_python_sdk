from enum import IntEnum


class MsgType(IntEnum):
    PING = 0x00
    PONG = 0x01
    ACK = 0x02
    LOG = 0x03
    STATUS_REQUEST = 0x04
    POSE_CMD = 0x10
    JOINT_ANGLES_CMD = 0x11
    MOTOR_ENABLE = 0x20
    MOTOR_ZERO = 0x21
    MOTOR_SET_PID = 0x22
    MOTOR_POSITION = 0x23
    CONFIG_HOMING = 0x24
    EXECUTE_HOMING = 0x25
    HOME_ARM = 0x26
    MOTOR_SET_CURRENT = 0x27
    MOTOR_SET_ACCEL = 0x28
    MOTOR_SET_SPEED = 0x29
    MOTOR_TELEMETRY = 0x30

class TransportType(IntEnum):
    WEBSOCKET = 0
    SERIAL = 1
