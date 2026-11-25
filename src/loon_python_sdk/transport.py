from abc import ABC, abstractmethod
import threading
from typing import Callable, Optional

try:
    import websocket
except ImportError:
    websocket = None

try:
    import serial
except ImportError:
    serial = None


class Transport(ABC):
    """Abstract base class defining the communication transport interface."""

    def __init__(self, on_frame_received: Callable[[bytes], None]):
        """Initialize transport with an incoming frame callback.

        Args:
            on_frame_received: Callback function receiving raw packet bytes when a
                valid frame arrives from the hardware.
        """
        self.on_frame_received = on_frame_received

    @abstractmethod
    def start(self, timeout: float = 10.0) -> None:
        """Establish connection and launch background receive worker thread.

        Args:
            timeout: Maximum seconds to wait for connection.
        """
        pass

    @abstractmethod
    def send_bytes(self, data: bytes) -> None:
        """Transmit raw framed bytes over the transport connection.

        Args:
            data: Raw binary frame to send.
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Disconnect and stop background listener threads."""
        pass


class WebSocketTransport(Transport):
    """WebSocket transport client communicating with ESP32 over WiFi/TCP."""

    def __init__(self, url: str, on_frame_received: Callable[[bytes], None]):
        """Initialize WebSocket transport.

        Args:
            url: Full WebSocket URL (e.g. 'ws://192.168.4.1:80/ws').
            on_frame_received: Callback invoked when a frame arrives.
        """
        super().__init__(on_frame_received)
        if websocket is None:
            raise ImportError(
                "websocket-client is required for WebSocketTransport. "
                "Run: pip install websocket-client"
            )
        self.url = url
        self._connected = threading.Event()
        self.ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._thread = threading.Thread(
            target=self.ws.run_forever, daemon=True, name="WebSocketThread"
        )

    def start(self, timeout: float = 10.0) -> None:
        """Launch background WebSocket thread and block until connected or timeout.

        Args:
            timeout: Maximum wait time in seconds for the connection handshake.
        """
        self._thread.start()
        if not self._connected.wait(timeout=timeout):
            raise RuntimeError(f"could not connect to {self.url}")

    def _on_open(self, _ws) -> None:
        """Internal callback invoked when WebSocket connection is opened."""
        print(f"[connected] {self.url}")
        self._connected.set()

    def _on_message(self, _ws, message) -> None:
        """Internal callback invoked when a WebSocket message is received."""
        if isinstance(message, str):
            message = message.encode()
        self.on_frame_received(message)

    def _on_error(self, _ws, error) -> None:
        """Internal callback invoked on WebSocket errors."""
        print(f"[error] {error}")

    def _on_close(self, _ws, status_code, msg) -> None:
        """Internal callback invoked when WebSocket closes."""
        print(f"[closed] {status_code} {msg}")
        self._connected.clear()

    def send_bytes(self, data: bytes) -> None:
        """Send raw binary frame over WebSocket as binary opcode."""
        self.ws.send(data, opcode=websocket.ABNF.OPCODE_BINARY)

    def close(self) -> None:
        """Close WebSocket connection and terminate thread."""
        self.ws.close()


class SerialTransport(Transport):
    """Serial UART transport communicating with ESP32 over USB-to-UART or COM port."""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        on_frame_received: Optional[Callable[[bytes], None]] = None,
    ):
        """Initialize Serial transport.

        Args:
            port: Serial device path (e.g. '/dev/ttyUSB0' or 'COM3').
            baudrate: Baud rate in bits/second (default: 115200).
            on_frame_received: Callback invoked when a complete frame is reassembled.
        """
        super().__init__(on_frame_received or (lambda _: None))
        if serial is None:
            raise ImportError(
                "pyserial is required for SerialTransport. "
                "Run: pip install pyserial"
            )
        self.port = port
        self.baudrate = baudrate
        self.ser: Optional[serial.Serial] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self, timeout: float = 10.0) -> None:
        """Open the serial port and start the stream frame-parser thread.

        Args:
            timeout: Unused timeout compatibility parameter.
        """
        self.ser = serial.Serial(self.port, self.baudrate, timeout=1.0)
        self._running = True
        self._thread = threading.Thread(
            target=self._read_loop, daemon=True, name="SerialThread"
        )
        self._thread.start()
        print(f"[connected] Serial on {self.port} @ {self.baudrate} baud")

    def _read_loop(self) -> None:
        """Stream reader thread: synchronizes on 0x7E and extracts complete frames."""
        while self._running and self.ser and self.ser.is_open:
            try:
                # 1. Sync on start byte (0x7E)
                b = self.ser.read(1)
                if not b or b[0] != 0x7E:
                    continue

                # 2. Read msg_type (1B) and size (1B)
                header = self.ser.read(2)
                if len(header) < 2:
                    continue
                size = header[1]

                # 3. Read payload + checksum (size + 1 bytes)
                rest = self.ser.read(size + 1)
                if len(rest) < size + 1:
                    continue

                frame = bytes([0x7E]) + header + rest
                self.on_frame_received(frame)
            except Exception as e:
                if not self._running:
                    break
                print(f"[serial error] {e}")

    def send_bytes(self, data: bytes) -> None:
        """Send raw binary frame over open serial port."""
        if self.ser and self.ser.is_open:
            self.ser.write(data)

    def close(self) -> None:
        """Signal read loop to terminate and close serial port."""
        self._running = False
        if self.ser and self.ser.is_open:
            self.ser.close()
