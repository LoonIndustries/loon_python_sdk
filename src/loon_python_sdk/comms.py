import struct

from loon_python_sdk.enums import MsgType

START_BYTE = 0x7E
MAX_PAYLOAD = 200

def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def encode_frame(msg_type: int, payload: bytes = b"") -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload too large ({len(payload)} > {MAX_PAYLOAD})")
    body = bytes([msg_type & 0xFF, len(payload)]) + payload
    return bytes([START_BYTE]) + body + bytes([checksum(body)])


def decode_frame(data: bytes):
    if len(data) < 4:
        raise ValueError(f"frame too short ({len(data)} bytes)")
    if data[0] != START_BYTE:
        raise ValueError(f"bad start byte: 0x{data[0]:02X}")
    msg_type = data[1]
    size = data[2]
    if len(data) != 3 + size + 1:
        raise ValueError(f"length mismatch: expected {3 + size + 1}, got {len(data)}")
    payload = data[3:3 + size]
    expected = checksum(data[1:3 + size])
    actual = data[3 + size]
    if expected != actual:
        raise ValueError(f"checksum mismatch: expected 0x{expected:02X}, got 0x{actual:02X}")
    return msg_type, payload


# ---- payload helpers (match include/comm.h struct layouts, little-endian) ----

def pack_pose(x, y, z, roll, pitch, yaw, grip):
    return struct.pack("<7f", x, y, z, roll, pitch, yaw, grip)


def pack_joint_angles(base, shoulder, elbow, wrist, twist, claw):
    return struct.pack("<7f", base, shoulder, elbow, wrist, twist, claw, 0.0)  # trailing padding float


def pack_motor_enable(can_id, enabled):
    return struct.pack("<BB", can_id, 1 if enabled else 0)


def pack_motor_zero(can_id):
    return struct.pack("<B", can_id)


def pack_motor_pid(can_id, kp, ki, kd):
    return struct.pack("<Bfff", can_id, kp, ki, kd)


def pack_motor_position(can_id, degrees):
    return struct.pack("<Bf", can_id, degrees)


# Mirrors HomingConfig in include/comm.h: canId, direction, speed, mode, offset, current
# (packed, no padding). Note the firmware's ConfigHoming handler currently hardcodes the
# CAN-level "trig"/limitEnable fields to 0 -- those aren't exposed over this protocol yet.
def pack_homing_config(can_id, direction, speed, mode, offset, current):
    return struct.pack("<BBHBIH", can_id, direction, speed, mode, offset, current)


def pack_homing_cmd(can_id):
    return struct.pack("<B", can_id)


MOTOR_STATE_WIRE_FMT = "<BBB6fBH"
MOTOR_STATE_WIRE_SIZE = struct.calcsize(MOTOR_STATE_WIRE_FMT)  # 30 bytes (trailing `reversed` flag)
ACK_FMT = "<BB32s"
MOTOR_STATUS_NAMES = {0: "offline", 1: "online", 2: "error"}


def parse_motor_telemetry(payload: bytes) -> list:
    """Decode a MOTOR_TELEMETRY payload into a list of dicts, one per motor.
    Mirrors MotorStateWire in include/comm.h / parseMotorTelemetry in data/app.js."""
    count = len(payload) // MOTOR_STATE_WIRE_SIZE
    motors = []
    for i in range(count):
        chunk = payload[i * MOTOR_STATE_WIRE_SIZE:(i + 1) * MOTOR_STATE_WIRE_SIZE]
        can_id, enabled, status, pos, target, speed, kp, ki, kd, reversed_, workingCurrentMa = struct.unpack(MOTOR_STATE_WIRE_FMT, chunk)
        motors.append({
            "can_id": can_id,
            "enabled": bool(enabled),
            "status": status,
            "position_deg": pos,
            "target_position_deg": target,
            "speed_rpm": speed,
            "kp": kp,
            "ki": ki,
            "kd": kd,
            "reversed": bool(reversed_),
            "working_current_ma": workingCurrentMa
        })
    return motors


def describe_payload(msg_type: int, payload: bytes) -> str:
    try:
        t = MsgType(msg_type)
    except ValueError:
        return f"unknown type 0x{msg_type:02X}, {len(payload)} bytes: {payload.hex()}"

    if t == MsgType.PONG:
        return "PONG (heartbeat)"
    if t == MsgType.ACK:
        acked_type, success, message = struct.unpack(ACK_FMT, payload)
        text = message.split(b"\x00", 1)[0].decode(errors="replace")
        try:
            acked_name = MsgType(acked_type).name
        except ValueError:
            acked_name = f"0x{acked_type:02X}"
        status = "OK" if success else "FAIL"
        return f"ACK[{acked_name}] {status}" + (f" ({text})" if text else "")
    if t == MsgType.LOG:
        return f"LOG: {payload.decode(errors='replace')}"
    if t == MsgType.MOTOR_TELEMETRY:
        lines = []
        for m in parse_motor_telemetry(payload):
            lines.append(
                f"  motor {m['can_id']}: {'enabled' if m['enabled'] else 'disabled'}, "
                f"{MOTOR_STATUS_NAMES.get(m['status'], m['status'])}, "
                f"pos={m['position_deg']:.2f} target={m['target_position_deg']:.2f} speed={m['speed_rpm']:.2f} "
                f"pid=({m['kp']:.3f},{m['ki']:.3f},{m['kd']:.3f})"
                f"{' REVERSED' if m['reversed'] else ''}"
                f"current={m['working_current_ma']}mA "
            )
        return "MOTOR_TELEMETRY:\n" + "\n".join(lines)
    return f"{t.name}, {len(payload)} bytes: {payload.hex()}"


