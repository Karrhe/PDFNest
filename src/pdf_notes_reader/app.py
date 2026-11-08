"""Application entry point: single instance, and pdfnest:// links or .pdf paths to open.

Windows (and Linux) pass links and files on the command line. macOS never does for an app bundle:
Finder, "Open With" and clicked pdfnest:// links reach the running app as ``QFileOpenEvent``s,
which :class:`FileOpenReceiver` turns into the same requests.
"""

from __future__ import annotations

import getpass
import json
import re
import sys

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMainWindow

from pdf_notes_reader.ui.main_window import MainWindow

HANDOFF_TIMEOUT_MS = 1500


def instance_server_name() -> str:
    user = re.sub(r"[^A-Za-z0-9_.-]", "_", getpass.getuser() or "user")
    return f"PDFNest-{user}"


def open_requests(argv: list[str]) -> list[str]:
    """The links and PDF paths among the command-line arguments."""
    return [arg for arg in argv[1:] if arg.lower().startswith("pdfnest:") or arg.lower().endswith(".pdf")]


def file_open_request(url_scheme: str, url_text: str, file_path: str) -> str | None:
    """The open request carried by a macOS file-open event, or None when it is not for PDFNest."""
    if url_scheme.lower() == "pdfnest" and url_text:
        return url_text
    if file_path and file_path.lower().endswith(".pdf"):
        return file_path
    return None


class FileOpenReceiver(QObject):
    """Collects macOS ``QFileOpenEvent``s sent to the application.

    Events that arrive before the main window exists (the document that launched the app) are
    held until :meth:`set_ready` is called.
    """

    requests_received = Signal(list)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pending: list[str] = []
        self._ready = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if event.type() == QEvent.FileOpen:
            url = event.url()
            # Fully encoded: a decoded "+" or "&" inside the path would change what parse_qs reads.
            url_text = bytes(url.toEncoded()).decode("ascii", "replace")
            request = file_open_request(url.scheme(), url_text, event.file())
            if request is not None:
                self.add_request(request)
                return True
        return super().eventFilter(watched, event)

    def add_request(self, request: str) -> None:
        if self._ready:
            self.requests_received.emit([request])
        else:
            self._pending.append(request)

    def set_ready(self) -> None:
        self._ready = True
        if self._pending:
            pending, self._pending = self._pending, []
            self.requests_received.emit(pending)


def send_to_running_instance(requests: list[str], server_name: str, timeout_ms: int = HANDOFF_TIMEOUT_MS) -> bool:
    """Hands ``requests`` to an already running PDFNest. False when none is running."""
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(timeout_ms):
        return False
    if sys.platform == "win32":
        try:  # let the running instance bring its window to the front
            import ctypes  # noqa: PLC0415

            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
        except Exception:
            pass
    socket.write(json.dumps(requests).encode("utf-8") + b"\n")
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    # Wait for the running instance to confirm it has the message before hanging up; without the
    # acknowledgement the pipe can close before the message is read.
    deadline_ms = timeout_ms
    while b"\n" not in bytes(socket.peek(64)) and deadline_ms > 0:
        if not socket.waitForReadyRead(100):
            deadline_ms -= 100
            if socket.state() == QLocalSocket.UnconnectedState:
                break
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.UnconnectedState:
        socket.waitForDisconnected(timeout_ms)
    return True


class InstanceServer(QObject):
    """Receives the requests of later PDFNest launches (each a JSON list of links)."""

    requests_received = Signal(list)

    def __init__(self, server_name: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        if not self.server.listen(server_name):
            QLocalServer.removeServer(server_name)  # stale socket left by a crash (non-Windows)
            self.server.listen(server_name)
        self.server.newConnection.connect(self._accept)
        self._buffers: dict[QLocalSocket, bytes] = {}

    def is_listening(self) -> bool:
        return self.server.isListening()

    def close(self) -> None:
        self.server.close()

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._buffers[socket] = b""
            socket.readyRead.connect(lambda socket=socket: self._read(socket))
            socket.disconnected.connect(lambda socket=socket: self._finish(socket))

    def _read(self, socket: QLocalSocket) -> None:
        buffer = self._buffers.get(socket, b"") + bytes(socket.readAll())
        if b"\n" not in buffer:
            self._buffers[socket] = buffer
            return
        payload, _rest = buffer.split(b"\n", 1)
        self._buffers[socket] = b""
        socket.write(b"ok\n")  # acknowledgement: the sender may hang up now
        socket.flush()
        try:
            requests = json.loads(payload.decode("utf-8")) if payload else []
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if isinstance(requests, list):
            self.requests_received.emit([str(item) for item in requests])

    def _finish(self, socket: QLocalSocket) -> None:
        self._buffers.pop(socket, None)
        socket.deleteLater()


def bring_to_front(window: QMainWindow) -> None:
    if window.isMinimized():
        window.setWindowState((window.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
    window.show()
    window.raise_()
    window.activateWindow()


def handle_requests(window: MainWindow, requests: list[str]) -> None:
    for request in requests:
        window.open_url(request)
    bring_to_front(window)


def main() -> int:
    app = QApplication(sys.argv)
    file_opens = FileOpenReceiver(app)
    app.installEventFilter(file_opens)
    requests = open_requests(sys.argv)
    server_name = instance_server_name()
    if send_to_running_instance(requests, server_name):
        return 0  # the running PDFNest opens the link

    window = MainWindow()
    if window.restore_window_maximized:
        window.showMaximized()
    else:
        window.show()
    server = InstanceServer(server_name, app)
    server.requests_received.connect(lambda received: handle_requests(window, received))
    file_opens.requests_received.connect(lambda received: handle_requests(window, received))
    if requests:
        QTimer.singleShot(0, lambda: handle_requests(window, requests))
    QTimer.singleShot(0, file_opens.set_ready)
    return app.exec()
