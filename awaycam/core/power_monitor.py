"""Windows の電源イベント（スリープ / 復帰）の受信。

スリープ復帰後にカメラが二度と開かなくなる問題への対策。時間の飛びを
見て推測するより、OS からの通知を直接受け取る方が確実なため、
WM_POWERBROADCAST を Qt のネイティブイベントフィルタで拾う。

- スリープに入る前にカメラを解放しておく
  （デバイスが消えた状態のハンドルを read() すると、そのまま
    戻ってこないことがあり、判定ループごと固まってしまう）
- 復帰したらカメラを開き直す

Windows 以外や、通知を受け取れない環境では静かに何もしない。
"""
from __future__ import annotations

import ctypes
import sys
import time
from typing import Callable, Optional

from PySide6.QtCore import QAbstractNativeEventFilter

from ..logging_setup import get_logger

log = get_logger("power_monitor")

WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004            # これからスリープに入る
PBT_APMRESUMESUSPEND = 0x0007      # ユーザー操作による復帰
PBT_APMRESUMEAUTOMATIC = 0x0012    # 自動（タイマーなど）での復帰

_RESUME_EVENTS = (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC)

# Windows は復帰時に上記2つを続けて送ってくる。開き直したばかりのカメラを
# もう一度閉じてしまわないよう、短時間に続いた復帰通知は1回として扱う。
RESUME_DEDUPE_SECONDS = 10.0


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]


class PowerEventFilter(QAbstractNativeEventFilter):
    """WM_POWERBROADCAST を監視して、スリープ前後にコールバックする。"""

    def __init__(
        self,
        on_suspend: Callable[[], None],
        on_resume: Callable[[], None],
    ) -> None:
        super().__init__()
        self._on_suspend = on_suspend
        self._on_resume = on_resume
        self._last_resume_at = 0.0
        self._clock = time.monotonic

    @property
    def available(self) -> bool:
        return sys.platform == "win32"

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (Qt の命名)
        # 受け取れない形式でも例外は投げない。電源通知は「あれば嬉しい」機能で、
        # ここで落ちると AwayCam 本体が巻き添えになるため。
        try:
            if bytes(event_type) != b"windows_generic_MSG":
                return False, 0
            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
            if msg.message == WM_POWERBROADCAST:
                self._dispatch(msg.wParam)
        except Exception as exc:
            log.debug("電源イベントの解釈に失敗: %s", exc)
        return False, 0  # 常に Qt の通常処理へ渡す

    def _dispatch(self, event: int) -> None:
        if event == PBT_APMSUSPEND:
            log.info("スリープに入ります。カメラを解放します")
            self._on_suspend()
        elif event in _RESUME_EVENTS:
            now = self._clock()
            if now - self._last_resume_at < RESUME_DEDUPE_SECONDS:
                log.debug("復帰通知が続けて届いたため、2回目は無視します")
                return
            self._last_resume_at = now
            log.info("スリープから復帰しました。カメラを開き直します")
            self._on_resume()


def install(
    app,
    on_suspend: Callable[[], None],
    on_resume: Callable[[], None],
) -> Optional[PowerEventFilter]:
    """アプリに電源イベントフィルタを取り付ける。使えなければ None。"""
    if sys.platform != "win32":
        return None
    event_filter = PowerEventFilter(on_suspend, on_resume)
    try:
        app.installNativeEventFilter(event_filter)
    except Exception as exc:
        log.warning("電源イベントを監視できません: %s", exc)
        return None
    log.info("スリープ / 復帰の監視を開始しました")
    # 参照が切れると Qt 側から呼ばれなくなるため、呼び出し元で保持してもらう
    return event_filter
