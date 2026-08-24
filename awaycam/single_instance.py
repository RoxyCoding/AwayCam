"""多重起動の防止。

自動起動と手動起動が重なると、2つの AwayCam が同じカメラを取り合って
「カメラエラー」になってしまう。そこで最初の1つだけを動かし、
2つ目は既存のウィンドウを前面に出させてから終了する。

QLocalServer / QLocalSocket を使う（名前付きパイプ。後片付けが不要）。
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .logging_setup import get_logger

log = get_logger("single_instance")

SERVER_NAME = "AwayCam-single-instance"
SHOW_WINDOW_MESSAGE = b"show"
CONNECT_TIMEOUT_MS = 500


def is_already_running() -> bool:
    """既に AwayCam が動いていれば、その画面を出させて True を返す。"""
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
        return False

    # 先に起動している方にウィンドウを表示させる
    socket.write(SHOW_WINDOW_MESSAGE)
    socket.waitForBytesWritten(CONNECT_TIMEOUT_MS)
    socket.disconnectFromServer()
    log.info("既に AwayCam が起動しています。既存のウィンドウを表示して終了します")
    return True


class InstanceServer(QObject):
    """2つ目の起動を受け付け、メイン画面の表示要求として扱う。"""

    def __init__(self, on_show_window: Callable[[], None], parent=None) -> None:
        super().__init__(parent)
        self._on_show_window = on_show_window
        self._server: Optional[QLocalServer] = None

    def listen(self) -> bool:
        server = QLocalServer(self)
        # 前回異常終了でパイプが残っていることがあるので掃除してから待ち受ける
        QLocalServer.removeServer(SERVER_NAME)
        if not server.listen(SERVER_NAME):
            log.warning("多重起動の監視を開始できませんでした: %s", server.errorString())
            return False
        server.newConnection.connect(self._handle_connection)
        self._server = server
        return True

    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(SERVER_NAME)
            self._server = None

    def _handle_connection(self) -> None:
        if self._server is None:
            return
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        socket.readyRead.connect(lambda: self._handle_message(socket))
        socket.disconnected.connect(socket.deleteLater)

    def _handle_message(self, socket: QLocalSocket) -> None:
        data = bytes(socket.readAll())
        if SHOW_WINDOW_MESSAGE in data:
            log.info("2つ目の起動を検知しました。メイン画面を表示します")
            self._on_show_window()
