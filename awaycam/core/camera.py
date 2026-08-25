"""Webカメラの開閉・フレーム取得・自動再接続。

重要な設計方針:
- カメラが使えない間は「フレーム無し」を返すだけで、離席判定は行わせない
  （真っ黒な画面を離席と誤認しないため）。
- 一時停止時は release() でデバイスを完全に解放し、他アプリが使えるようにする。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import cv2
import numpy as np

from ..logging_setup import get_logger

log = get_logger("camera")

# 開ける順に試すキャプチャバックエンド。
# DirectShow で開けず Media Foundation なら開けるカメラがあるため両方持つ。
BACKENDS = [
    ("DirectShow", cv2.CAP_DSHOW),
    ("MediaFoundation", cv2.CAP_MSMF),
    ("既定", cv2.CAP_ANY),
]


class CameraState(Enum):
    CLOSED = "closed"          # 意図的に閉じている（一時停止・無効時）
    OPENING = "opening"        # 接続試行中
    RUNNING = "running"        # 正常
    ERROR = "error"            # 失敗中（再接続待ち）


@dataclass
class CameraDevice:
    index: int
    name: str


def enumerate_cameras(max_probe: int = 8) -> list[CameraDevice]:
    """接続されているカメラを列挙する。

    まず pygrabber で DirectShow のデバイス名を取得し、失敗したら
    インデックスを総当たりして「カメラ N」という名前で返す。
    """
    try:
        from pygrabber.dshow_graph import FilterGraph

        names = FilterGraph().get_input_devices()
        if names:
            return [CameraDevice(i, n) for i, n in enumerate(names)]
    except Exception as exc:  # pygrabber 未導入や COM 失敗
        log.debug("pygrabber でのデバイス列挙に失敗: %s", exc)

    devices: list[CameraDevice] = []
    for index in range(max_probe):
        capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if capture.isOpened():
            devices.append(CameraDevice(index, f"カメラ {index}"))
        capture.release()
    return devices


class Camera:
    """1台のWebカメラを保持し、失敗時は指数バックオフで再接続する。"""

    def __init__(
        self,
        index: int = 0,
        width: int = 640,
        height: int = 480,
        reconnect_min_s: float = 2.0,
        reconnect_max_s: float = 30.0,
    ) -> None:
        self.index = index
        self.width = width
        self.height = height
        self.state = CameraState.CLOSED
        self.last_error: str = ""
        self.backend_name: str = ""

        self._capture: Optional[cv2.VideoCapture] = None
        self._reconnect_min_s = reconnect_min_s
        self._reconnect_max_s = reconnect_max_s
        self._reconnect_delay_s = reconnect_min_s
        self._next_retry_at = 0.0
        self._consecutive_read_failures = 0

    # --- 開閉 ---

    def open(self) -> bool:
        """カメラを開く。成功したら True。

        カメラによって使えるバックエンドが異なる（DirectShow で開けず
        Media Foundation なら開ける機種がある）ため、順に試す。
        """
        self.release()
        self.state = CameraState.OPENING

        could_open_but_no_frames = False
        for backend_name, backend in BACKENDS:
            capture = self._try_backend(backend)
            if capture is None:
                continue
            if not self._warm_up(capture):
                # 開けたのに映像が来ない = 他アプリが専有している典型パターン
                could_open_but_no_frames = True
                capture.release()
                continue

            self._capture = capture
            self.backend_name = backend_name
            self.state = CameraState.RUNNING
            self.last_error = ""
            self._reconnect_delay_s = self._reconnect_min_s
            self._consecutive_read_failures = 0
            log.info("カメラ %d を開きました (%s)", self.index, backend_name)
            return True

        if could_open_but_no_frames:
            return self._fail(
                "カメラは認識されていますが映像を取得できません"
                "（他のアプリが使用中、またはアクセスが拒否されています）"
            )
        return self._fail("カメラを開けません（未接続、または他のアプリが使用中）")

    def _try_backend(self, backend: int) -> Optional[cv2.VideoCapture]:
        """指定バックエンドで開いてみる。失敗したら None。"""
        try:
            capture = cv2.VideoCapture(self.index, backend)
        except Exception as exc:
            log.debug("バックエンド %s で例外: %s", backend, exc)
            return None
        if not capture.isOpened():
            capture.release()
            return None

        # 解像度は判定に十分な最低限に落とし、CPU 負荷と遅延を抑える
        for prop, value in (
            (cv2.CAP_PROP_FRAME_WIDTH, self.width),
            (cv2.CAP_PROP_FRAME_HEIGHT, self.height),
            (cv2.CAP_PROP_BUFFERSIZE, 1),
        ):
            try:
                capture.set(prop, value)
            except Exception:
                pass  # 設定を受け付けないカメラもあるが致命的ではない
        return capture

    def _warm_up(self, capture: cv2.VideoCapture, attempts: int = 8) -> bool:
        """最初の数フレームは空で返るカメラがあるため、少し待って確かめる。"""
        for _ in range(attempts):
            try:
                ok, frame = capture.read()
            except Exception:
                return False
            if ok and frame is not None and frame.size > 0:
                return True
            time.sleep(0.1)
        return False

    def release(self) -> None:
        """デバイスを解放する。一時停止時に必ず呼ぶ。"""
        if self._capture is not None:
            try:
                self._capture.release()
            except Exception:
                pass
            self._capture = None
            log.info("カメラ %d を解放しました", self.index)
        self.state = CameraState.CLOSED

    def reset(self) -> None:
        """デバイスを捨てて、次の周期で即座に開き直せる状態にする。

        スリープ復帰後は OS 側でデバイスが再列挙され、開いたままの
        ハンドルは無効になっている。再接続の待ち時間（指数バックオフ）も
        持ち越さず、すぐ開き直せるようにここで初期化する。
        """
        self.release()
        self._reconnect_delay_s = self._reconnect_min_s
        self._next_retry_at = 0.0
        self._consecutive_read_failures = 0
        self.last_error = ""

    @property
    def is_open(self) -> bool:
        return self._capture is not None and self.state is CameraState.RUNNING

    # --- フレーム取得 ---

    def read(self) -> Optional[np.ndarray]:
        """BGR フレームを返す。取得できない場合は None（＝判定を行わない）。"""
        if self._capture is None:
            self._try_reconnect()
            return None

        # 1枚落ちただけで諦めず、同じ周期内で数回だけ取り直す
        for attempt in range(3):
            try:
                ok, frame = self._capture.read()
            except Exception as exc:
                self._fail(f"フレーム取得で例外が発生しました: {exc}")
                return None

            if ok and frame is not None and frame.size > 0:
                self._consecutive_read_failures = 0
                return frame
            if attempt < 2:
                time.sleep(0.05)

        # 一時的なコマ落ちは許容し、続いたら切断とみなす
        self._consecutive_read_failures += 1
        if self._consecutive_read_failures >= 5:
            self._fail("カメラとの接続が切断されました")
        return None

    # --- 内部処理 ---

    def _fail(self, message: str) -> bool:
        if self.last_error != message:
            log.warning("カメラエラー: %s", message)
        self.last_error = message
        self.state = CameraState.ERROR
        if self._capture is not None:
            try:
                self._capture.release()
            except Exception:
                pass
            self._capture = None
        self._schedule_retry()
        return False

    def _schedule_retry(self) -> None:
        self._next_retry_at = time.monotonic() + self._reconnect_delay_s
        self._reconnect_delay_s = min(self._reconnect_delay_s * 2, self._reconnect_max_s)

    def _try_reconnect(self) -> None:
        if self.state is CameraState.CLOSED:
            return  # 意図的に閉じている
        if time.monotonic() < self._next_retry_at:
            return
        log.info("カメラ %d への再接続を試みます", self.index)
        self.open()

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, *_exc_info) -> None:
        self.release()
