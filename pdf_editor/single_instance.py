"""Forward a second launch (print PDF) into the already running app."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QByteArray
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

SERVER_NAME = "TinyPDFEditor.SingleInstance"


def offer_to_running_instance(paths: list[str]) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(250):
        socket.close()
        return False
    payload = "\n".join(paths).encode("utf-8")
    socket.write(QByteArray(payload))
    socket.waitForBytesWritten(800)
    socket.flush()
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        socket.waitForDisconnected(400)
    return True


def start_instance_server() -> QLocalServer | None:
    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    if not server.listen(SERVER_NAME):
        return None
    return server


def bind_instance_server(
    server: QLocalServer,
    on_paths: Callable[[list[str]], None],
    *,
    on_activate: Callable[[], None] | None = None,
) -> None:
    def _accept() -> None:
        sock = server.nextPendingConnection()
        if sock is None:
            return
        if sock.bytesAvailable() == 0:
            sock.waitForReadyRead(800)
        text = bytes(sock.readAll()).decode("utf-8", errors="replace")
        sock.close()
        paths = [line.strip() for line in text.splitlines() if line.strip()]
        if not paths:
            if on_activate is not None:
                on_activate()
            return
        on_paths(paths)

    server.newConnection.connect(_accept)
