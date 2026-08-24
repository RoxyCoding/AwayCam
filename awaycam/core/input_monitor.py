"""キーボード/マウス操作の検知（Windows）。

Win32 の GetLastInputInfo を使う。フックを張らないので負荷ゼロで、
入力内容は一切取得しない（最後に入力があった時刻のみ）。

カメラが人物を見落としたときの救済として重要:
操作があれば、カメラ判定を待たず即座に「在席」とみなす。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from ..logging_setup import get_logger

log = get_logger("input_monitor")


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class InputMonitor:
    """最後のユーザー操作からの経過時間を返す。"""

    def __init__(self) -> None:
        self.available = False
        try:
            self._user32 = ctypes.windll.user32
            self._kernel32 = ctypes.windll.kernel32
            self._info = _LASTINPUTINFO()
            self._info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
            self.idle_seconds()  # 一度呼んで動作確認
            self.available = True
        except Exception as exc:
            log.warning("入力監視を利用できません（キー/マウス即復帰は無効）: %s", exc)

    def idle_seconds(self) -> float:
        """最後のキーボード/マウス操作からの経過秒。取得不能なら 0.0。"""
        try:
            if not self._user32.GetLastInputInfo(ctypes.byref(self._info)):
                return 0.0
            now_ms = self._kernel32.GetTickCount()
            # GetTickCount は約49日でラップするので符号なし32bitで差を取る
            elapsed_ms = (now_ms - self._info.dwTime) & 0xFFFFFFFF
            return elapsed_ms / 1000.0
        except Exception:
            return 0.0

    def had_input_within(self, seconds: float) -> bool:
        """直近 seconds 秒以内に操作があったか。"""
        if not self.available:
            return False
        return self.idle_seconds() <= seconds
