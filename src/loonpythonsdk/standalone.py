import argparse
import sys

from loonpythonsdk.client import Client
from loonpythonsdk.comms import (
    pack_homing_cmd,
    pack_homing_config,
    pack_joint_angles,
    pack_motor_enable,
    pack_motor_pid,
    pack_motor_position,
    pack_motor_zero,
    pack_pose,
)
from loonpythonsdk.enums import MsgType


HELP = """
Commands:
  ping                                          send Ping, expect Pong back
  status                                        request immediate motor telemetry
  pose x y z roll pitch yaw grip                send a pose command (floats)
  joints base shoulder elbow wrist twist claw   send direct joint angles (bypasses IK)
  enable <id> <0|1>                             enable/disable a motor
  zero <id>                                     zero a motor's position
  pid <id> kp ki kd                             set a motor's PID gains
  position <id> degrees                         command a motor directly to an absolute angle
  homecfg <id> <dir> <speed> <mode> <offset> <current>
                                                 configure homing (dir: 0=CW/1=CCW, speed: 0-3000 RPM,
                                                 mode: 0=origin-switch/1=mechanical-limit/2=single-lap,
                                                 offset: origin-offset counts, current: zero-return mA)
  home <id>                                     execute the previously configured homing sequence
  homeall                                        home the whole arm: motors 2, 3, 4 in order, each
                                                 waiting for completion before the next starts.
                                                 Runs on the ESP32 in the background (can take tens
                                                 of seconds); an immediate ACK means "started", watch
                                                 for a LOG message for the final result.
  log <text>                                    send a free-form log/text message
  raw <hex bytes>                               send a raw malformed frame, e.g. for checksum-resync testing
  telemetry [on|off]                            toggle/set printing of MOTOR_TELEMETRY broadcasts (default off)
  heartbeat [on|off]                            toggle/set printing of PONG heartbeats (default off)
  help                                           show this message
  quit                                           disconnect and exit
"""


def parse_on_off(args, current: bool) -> bool:
    if not args:
        return not current
    value = args[0].lower()
    if value in ("on", "true", "1"):
        return True
    if value in ("off", "false", "0"):
        return False
    raise ValueError(f"expected 'on' or 'off', got {args[0]!r}")


def run_cli_client():
    parser = argparse.ArgumentParser(description="Interactive test client for the Loon ESP32 comm protocol")
    parser.add_argument("--host", default="192.168.4.1", help="ESP32 AP IP address (default: 192.168.4.1)")
    parser.add_argument("--port", type=int, default=80)
    args = parser.parse_args()

    url = f"ws://{args.host}:{args.port}/ws"
    client = Client().from_websocket(url)
    try:
        client.start()
    except RuntimeError as e:
        sys.exit(str(e))

    print(HELP)

    try:
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                break
            if not line:
                continue
            parts = line.split()
            cmd = parts[0].lower()
            rest = parts[1:]

            try:
                if cmd in ("quit", "exit"):
                    break
                elif cmd == "help":
                    print(HELP)
                elif cmd == "ping":
                    client.send(MsgType.PING)
                elif cmd == "status":
                    client.send(MsgType.STATUS_REQUEST)
                elif cmd == "pose":
                    x, y, z, roll, pitch, yaw, grip = (float(v) for v in rest)
                    client.send(MsgType.POSE_CMD, pack_pose(x, y, z, roll, pitch, yaw, grip))
                elif cmd == "joints":
                    base, shoulder, elbow, wrist, twist, claw = (float(v) for v in rest)
                    client.send(
                        MsgType.JOINT_ANGLES_CMD,
                        pack_joint_angles(base, shoulder, elbow, wrist, twist, claw),
                    )
                elif cmd == "enable":
                    can_id, enabled = int(rest[0]), int(rest[1])
                    client.send(MsgType.MOTOR_ENABLE, pack_motor_enable(can_id, enabled))
                elif cmd == "zero":
                    can_id = int(rest[0])
                    client.send(MsgType.MOTOR_ZERO, pack_motor_zero(can_id))
                elif cmd == "pid":
                    can_id = int(rest[0])
                    kp, ki, kd = (float(v) for v in rest[1:4])
                    client.send(MsgType.MOTOR_SET_PID, pack_motor_pid(can_id, kp, ki, kd))
                elif cmd == "position":
                    can_id = int(rest[0])
                    degrees = float(rest[1])
                    client.send(MsgType.MOTOR_POSITION, pack_motor_position(can_id, degrees))
                elif cmd == "homecfg":
                    can_id, direction, speed, mode, offset, current = (int(v) for v in rest[:6])
                    client.send(
                        MsgType.CONFIG_HOMING,
                        pack_homing_config(can_id, direction, speed, mode, offset, current),
                    )
                elif cmd == "home":
                    can_id = int(rest[0])
                    client.send(MsgType.EXECUTE_HOMING, pack_homing_cmd(can_id))
                elif cmd == "homeall":
                    client.send(MsgType.HOME_ARM)
                elif cmd == "log":
                    text = " ".join(rest)
                    client.send(MsgType.LOG, text.encode())
                elif cmd == "raw":
                    raw_bytes = bytes.fromhex("".join(rest))
                    client.transport.send_bytes(raw_bytes)
                elif cmd == "telemetry":
                    client.show_telemetry = parse_on_off(rest, client.show_telemetry)
                    print(f"telemetry display: {'on' if client.show_telemetry else 'off'}")
                elif cmd == "heartbeat":
                    client.show_heartbeat = parse_on_off(rest, client.show_heartbeat)
                    print(f"heartbeat display: {'on' if client.show_heartbeat else 'off'}")
                else:
                    print(f"unknown command: {cmd!r} (type 'help')")
            except (ValueError, IndexError) as e:
                print(f"bad arguments: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    run_cli_client()