from typing import Optional

from loonpythonsdk.comms import decode_frame, describe_payload, encode_frame, parse_motor_telemetry
from loonpythonsdk.transport import Transport, WebSocketTransport
from loonpythonsdk.enums import MsgType


class Client:
    def __init__(self, transport: Optional[Transport] = None, on_telemetry=None):
        """on_telemetry, if given, is called as on_telemetry(list_of_motor_dicts)
        (see parse_motor_telemetry()) every time a MOTOR_TELEMETRY frame arrives,
        regardless of show_telemetry -- that flag only controls console printing.
        Runs on the transport's own background thread, same as every other
        callback here; a caller consuming this from another thread (e.g. a
        pygame main loop) needs its own locking around any shared state."""
        self.transport = transport
        self.on_telemetry = on_telemetry

        # Telemetry (~5/sec) and heartbeat (~1/3sec) are broadcast continuously by the
        # ESP32 and quickly bury any other output, so they're hidden by default.
        self.show_telemetry = False
        self.show_heartbeat = False

    @classmethod
    def from_websocket(cls, url: str, on_telemetry=None) -> "Client":
        instance = None
        transport = WebSocketTransport(
            url, on_frame_received=lambda frame: instance._handle_frame(frame)
        )
        instance = cls(transport, on_telemetry=on_telemetry)
        return instance

    def start(self, timeout: float = 10.0):
        if self.transport is None:
            raise RuntimeError("No transport configured for client.")
        self.transport.start(timeout=timeout)

    def _handle_frame(self, message: bytes):
        try:
            msg_type, payload = decode_frame(message)
        except ValueError as e:
            print(f"[recv] malformed frame ({e}): {message.hex()}")
            return
        if msg_type == MsgType.MOTOR_TELEMETRY:
            if self.on_telemetry is not None:
                self.on_telemetry(parse_motor_telemetry(payload))
            if not self.show_telemetry:
                return
        if msg_type == MsgType.PONG and not self.show_heartbeat:
            return
        print(f"[recv] {describe_payload(msg_type, payload)}")

    def send(self, msg_type: int, payload: bytes = b""):
        if self.transport is None:
            raise RuntimeError("No transport configured for client.")
        frame = encode_frame(msg_type, payload)
        self.transport.send_bytes(frame)

    def close(self):
        if self.transport is not None:
            self.transport.close()
