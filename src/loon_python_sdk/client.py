from typing import Callable, Dict, List, Optional

from loon_python_sdk.comms import (
    decode_frame,
    describe_payload,
    encode_frame,
    pack_homing_cmd,
    pack_homing_config,
    pack_joint_angles,
    pack_motor_enable,
    pack_motor_pid,
    pack_motor_position,
    pack_pose,
    parse_motor_telemetry,
)
from loon_python_sdk.enums import MsgType
from loon_python_sdk.transport import SerialTransport, Transport, WebSocketTransport


class Loon5Arm:
    """High-level client for communicating with the Loon 5 robotic arm.

    Provides high-level commands for joint positioning, Cartesian pose control (IK),
    homing, motor PID tuning, telemetry tracking, and heartbeat monitoring across
    different communication transports (WebSocket or Serial).
    """

    def __init__(
        self,
        transport: Optional[Transport] = None,
        on_telemetry: Optional[Callable[[List[dict]], None]] = None,
    ):
        """Initialize a Loon robot arm client.

        Args:
            transport: The underlying communication transport (WebSocketTransport or
                SerialTransport). If None, can be configured later or initialized via
                factory classmethods `from_websocket()` or `from_serial()`.
            on_telemetry: Optional callback invoked whenever a MOTOR_TELEMETRY frame
                arrives. Receives a list of dictionaries with per-motor states
                (position_deg, speed_rpm, current gains, etc.). Runs on the
                transport's background receiver thread; callers sharing state across
                threads (e.g., in a GUI or game loop) should apply appropriate locking.
        """
        self.transport = transport
        self.on_telemetry = on_telemetry
        self.telemetry: Dict[int, dict] = {}
        self.started: bool = False

        # Telemetry (~5/sec) and heartbeat (~1/3sec) are broadcast continuously by the
        # ESP32 and quickly bury any other output, so they're hidden by default.
        self.show_telemetry: bool = False
        self.show_heartbeat: bool = False

    @classmethod
    def from_websocket(
        cls,
        url: str,
        on_telemetry: Optional[Callable[[List[dict]], None]] = None,
    ) -> "Loon5Arm":
        """Factory method to create and configure a Client using WebSocket transport.

        Args:
            url: WebSocket URL of the ESP32 (e.g., 'ws://192.168.4.1:80/ws').
            on_telemetry: Optional callback invoked when telemetry frames arrive.

        Returns:
            A configured Client instance ready to be started via `client.start()`.
        """
        instance = None
        transport = WebSocketTransport(
            url, on_frame_received=lambda frame: instance._handle_frame(frame)
        )
        instance = cls(transport, on_telemetry=on_telemetry)
        return instance

    @classmethod
    def from_serial(
        cls,
        port: str,
        baudrate: int = 115200,
        on_telemetry: Optional[Callable[[List[dict]], None]] = None,
    ) -> "Loon5Arm":
        """Factory method to create and configure a Client using Serial transport.

        Args:
            port: Serial device path or COM port (e.g., '/dev/ttyUSB0' or 'COM3').
            baudrate: Communication baud rate in bits/sec (default: 115200).
            on_telemetry: Optional callback invoked when telemetry frames arrive.

        Returns:
            A configured Client instance ready to be started via `client.start()`.
        """
        instance = None
        transport = SerialTransport(
            port=port,
            baudrate=baudrate,
            on_frame_received=lambda frame: instance._handle_frame(frame),
        )
        instance = cls(transport, on_telemetry=on_telemetry)
        return instance

    def start(self, timeout: float = 10.0) -> None:
        """Start the transport background communication thread and connect.

        Args:
            timeout: Maximum seconds to wait for connection confirmation before
                raising a RuntimeError.

        Raises:
            RuntimeError: If no transport is attached, or if connection fails.
        """
        if self.transport is None:
            raise RuntimeError("No transport configured for client.")
        self.transport.start(timeout=timeout)
        self.started = True

    def _handle_frame(self, message: bytes) -> None:
        """Internal callback invoked when raw binary frames are received from transport.

        Decodes the frame boundary, parses telemetry and status packets, updates
        internal telemetry cache, triggers user callbacks, and prints console messages.

        Args:
            message: Raw bytes containing a single validated packet.
        """
        try:
            msg_type, payload = decode_frame(message)
        except ValueError as e:
            print(f"[recv] malformed frame ({e}): {message.hex()}")
            return

        # Handle motor telemetry broadcasts (CAN status, angles, speeds, PID gains)
        if msg_type == MsgType.MOTOR_TELEMETRY:
            parsed = parse_motor_telemetry(payload)
            for m in parsed:
                self.telemetry[m["can_id"]] = m
            if self.on_telemetry is not None:
                self.on_telemetry(parsed)
            if not self.show_telemetry:
                return

        # Suppress heartbeat pong prints unless explicitly enabled
        if msg_type == MsgType.PONG and not self.show_heartbeat:
            return

        print(f"[recv] {describe_payload(msg_type, payload)}")

    def send(self, msg_type: int, payload: bytes = b"") -> None:
        """Encode and transmit a binary command frame to the robot controller.

        Frames follow the wire protocol format:
            [START 0x7E][TYPE 1B][SIZE 1B][PAYLOAD 0-200B][CHECKSUM 1B]

        Args:
            msg_type: Packet command identifier (from MsgType enum or integer).
            payload: Binary payload bytes (little-endian encoded).

        Raises:
            RuntimeError: If client transport is not configured.
            ValueError: If payload length exceeds MAX_PAYLOAD (200 bytes).
        """
        if self.transport is None:
            raise RuntimeError("No transport configured for client.")
        frame = encode_frame(msg_type, payload)
        self.transport.send_bytes(frame)

    def home_arm(self) -> None:
        """Execute automated sequential homing of arm motors 2, 3, and 4.

        Sends MsgType.HOME_ARM (0x26). The ESP32 executes homing in the background:
        Motor 2 (Shoulder) -> Motor 3 (Elbow) -> Motor 4 (Wrist) in order.
        An immediate ACK indicates the routine started; watch console LOG messages
        for intermediate motor completion and the final result.
        """
        self.send(MsgType.HOME_ARM)

    def home_motor(self, can_id: int) -> None:
        """Execute homing sequence for a single specified motor.

        Sends MsgType.EXECUTE_HOMING (0x25) with target CAN ID.

        Args:
            can_id: CAN bus identifier of the motor to home (e.g., 2, 3, or 4).
        """
        self.send(MsgType.EXECUTE_HOMING, pack_homing_cmd(can_id))

    def config_homing(
        self,
        can_id: int,
        direction: int,
        speed: int,
        mode: int,
        offset: int,
        current: int,
    ) -> None:
        """Configure homing parameters for a motor before homing is executed.

        Sends MsgType.CONFIG_HOMING (0x24) to program the motor's homing behavior.

        Args:
            can_id: CAN bus ID of the target motor.
            direction: Search direction (0 = Clockwise, 1 = Counter-Clockwise).
            speed: Homing seek speed in RPM (0 to 3000 RPM).
            mode: Homing mode (0 = origin-switch, 1 = mechanical-limit, 2 = single-lap).
            offset: Origin offset count from triggered position.
            current: Zero-return threshold current in mA (for stall/limit detection).
        """
        self.send(
            MsgType.CONFIG_HOMING,
            pack_homing_config(can_id, direction, speed, mode, offset, current),
        )

    def set_pose(
        self,
        x: float,
        y: float = 0.0,
        z: float = 0.0,
        roll: float = 0.0,
        pitch: float = 0.0,
        yaw: float = 0.0,
        grip: float = 0.0,
    ) -> None:
        """Command end-effector Cartesian pose using the ESP32 on-board Inverse Kinematics (IK).

        Sends MsgType.POSE_CMD (0x10). The controller's IK solver computes target
        joint angles to position and orient the gripper tool center point (TCP).

        Args:
            x: Forward Cartesian position from base center.
            y: Lateral Cartesian position (set to 0.0 to prevent base rotation if wired).
            z: Vertical Cartesian height position.
            roll: Tool wrist roll angle (degrees).
            pitch: Tool wrist pitch angle (degrees).
            yaw: Tool wrist yaw angle (degrees).
            grip: Claw gripper position value (0 = closed, higher = open).
        """
        self.send(MsgType.POSE_CMD, pack_pose(x, y, z, roll, pitch, yaw, grip))

    def set_angle(self, can_id: int, degrees: float) -> None:
        """Command an individual motor directly to an absolute target angle.

        Sends MsgType.MOTOR_POSITION (0x23).

        Args:
            can_id: Target motor CAN bus identifier (1 to 6).
            degrees: Target position in degrees.
        """
        self.send(MsgType.MOTOR_POSITION, pack_motor_position(can_id, degrees))

    def set_joint_angles(
        self,
        base: float = 0.0,
        shoulder: float = 0.0,
        elbow: float = 0.0,
        wrist: float = 0.0,
        twist: float = 0.0,
        claw: float = 0.0,
    ) -> None:
        """Directly command all 6 arm joints simultaneously, bypassing IK.

        Sends MsgType.JOINT_ANGLES_CMD (0x11).

        Args:
            base: Base rotation joint angle in degrees (Joint 1).
            shoulder: Shoulder pitch joint angle in degrees (Joint 2).
            elbow: Elbow pitch joint angle in degrees (Joint 3).
            wrist: Wrist pitch joint angle in degrees (Joint 4).
            twist: Wrist roll/twist joint angle in degrees (Joint 5).
            claw: End-effector claw opening in degrees (Joint 6).
        """
        self.send(
            MsgType.JOINT_ANGLES_CMD,
            pack_joint_angles(base, shoulder, elbow, wrist, twist, claw),
        )

    def set_angles(
        self,
        base: float = 0.0,
        shoulder: float = 0.0,
        elbow: float = 0.0,
        wrist: float = 0.0,
        twist: float = 0.0,
        claw: float = 0.0,
    ) -> None:
        """Convenience alias for `set_joint_angles()`."""
        self.set_joint_angles(base, shoulder, elbow, wrist, twist, claw)

    def set_pid(self, can_id: int, kp: float, ki: float, kd: float) -> None:
        """Configure PID controller gains for a specific motor on the fly.

        Sends MsgType.MOTOR_SET_PID (0x22).

        Args:
            can_id: CAN bus identifier of the motor.
            kp: Proportional gain (determines stiffness and rise time).
            ki: Integral gain (eliminates steady-state offset and gravity droop).
            kd: Derivative gain (damps oscillations and prevents overshoot).
        """
        self.send(MsgType.MOTOR_SET_PID, pack_motor_pid(can_id, kp, ki, kd))

    def enable_motor(self, can_id: int, enabled: bool = True) -> None:
        """Enable or disable drive torque for a motor.

        Sends MsgType.MOTOR_ENABLE (0x20).

        Args:
            can_id: CAN bus identifier of the motor.
            enabled: True to engage active torque control, False to freewheel.
        """
        self.send(MsgType.MOTOR_ENABLE, pack_motor_enable(can_id, enabled))

    def ping(self) -> None:
        """Send a PING heartbeat request (MsgType.PING / 0x00) to verify link connectivity.

        The ESP32 responds with a PONG packet upon receipt.
        """
        self.send(MsgType.PING)

    def close(self) -> None:
        """Close the active communication transport and release underlying resources."""
        if self.transport is not None:
            self.transport.close()
            self.started = False
