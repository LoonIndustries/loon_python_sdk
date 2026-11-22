from abc import ABC, abstractmethod
import threading
from typing import Callable

import websocket


class Transport(ABC):
    def __init__(self, on_frame_received: Callable[[bytes], None]):
        self.on_frame_received = on_frame_received

    @abstractmethod
    def start(self, timeout: float = 10.0) -> None:
        pass

    @abstractmethod
    def send_bytes(self, data: bytes) -> None:
        pass

    @abstractmethod
    def close(self) -> None:
        pass


class WebSocketTransport(Transport):
    def __init__(self, url: str, on_frame_received: Callable[[bytes], None]):
        super().__init__(on_frame_received)
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
        self._thread.start()
        if not self._connected.wait(timeout=timeout):
            raise RuntimeError(f"could not connect to {self.url}")

    def _on_open(self, _ws):
        print(f"[connected] {self.url}")
        self._connected.set()

    def _on_message(self, _ws, message):
        if isinstance(message, str):
            message = message.encode()
        self.on_frame_received(message)

    def _on_error(self, _ws, error):
        print(f"[error] {error}")

    def _on_close(self, _ws, status_code, msg):
        print(f"[closed] {status_code} {msg}")
        self._connected.clear()

    def send_bytes(self, data: bytes) -> None:
        self.ws.send(data, opcode=websocket.ABNF.OPCODE_BINARY)

    def close(self) -> None:
        self.ws.close()
