"""全画面アプリの検出（Windows）。

ゲーム・動画・プレゼンなどを全画面で使っている間は、AwayCam を自動的に
一時停止する。理由は2つある:

- 排他フルスクリーンのゲーム上では、そもそも離席画像の最前面表示が効かない。
  効かない表示のためにカメラを回し続けるのは無駄。
- 動画を見ているときは操作もせず動きも少ないため、離席と誤判定されやすい。

2つの方法を併用する:
  1. SHQueryUserNotificationState … 「通知を出してよいか」を OS に尋ねる公式 API。
     排他フルスクリーンの Direct3D アプリやプレゼンモードを確実に拾える。
  2. 前面ウィンドウの矩形判定 … ボーダーレス全画面（多くのゲームやブラウザの
     F11）は 1 で拾えないことがあるため、モニター全体を覆っているかで判定する。

自分自身の離席オーバーレイも全画面なので、必ず自プロセスは除外する。
除外しないと「オーバーレイ表示 → 全画面と誤認 → 一時停止 → 非表示」を
延々と繰り返してしまう。
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional

from ..logging_setup import get_logger

log = get_logger("fullscreen_monitor")

# SHQueryUserNotificationState の戻り値
QUNS_NOT_PRESENT = 1
QUNS_BUSY = 2                    # 全画面アプリが動作中
QUNS_RUNNING_D3D_FULL_SCREEN = 3  # 排他フルスクリーンの D3D アプリ
QUNS_PRESENTATION_MODE = 4        # プレゼンテーションモード
QUNS_ACCEPTS_NOTIFICATIONS = 5    # 通常
QUNS_QUIET_TIME = 6
QUNS_APP = 7                      # ストアアプリが全画面

# 一時停止すべき状態と、その説明
BLOCKING_STATES = {
    QUNS_BUSY: "全画面アプリ",
    QUNS_RUNNING_D3D_FULL_SCREEN: "全画面ゲーム",
    QUNS_PRESENTATION_MODE: "プレゼンテーションモード",
    QUNS_APP: "全画面アプリ",
}

# デスクトップ・シェル・一時的なオーバーレイのウィンドウ。
# 画面全体を覆うことがあるが「全画面アプリ」ではないので除外する。
# （Windows の検索やスタートメニューは UWP のため QUNS_APP として報告される）
SHELL_WINDOW_CLASSES = {
    "Progman",                      # デスクトップ
    "WorkerW",                      # デスクトップの壁紙レイヤー
    "Shell_TrayWnd",                # タスクバー
    "Shell_SecondaryTrayWnd",       # サブモニターのタスクバー
    "Windows.UI.Core.CoreWindow",   # スタートメニュー・検索など
    "XamlExplorerHostIslandWindow", # 検索・ウィジェット
    "Windows.UI.Composition.DesktopWindowContentBridge",
    "ApplicationManager_ImmersiveShellWindow",
    "MultitaskingViewFrame",        # タスクビュー
    "ForegroundStaging",            # Alt+Tab の切り替え中
    "TaskSwitcherWnd",              # Alt+Tab
    "TaskSwitcherOverlayWnd",
}

MONITOR_DEFAULTTONEAREST = 2


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG), ("top", wintypes.LONG),
        ("right", wintypes.LONG), ("bottom", wintypes.LONG),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("rcMonitor", _RECT),
        ("rcWork", _RECT), ("dwFlags", wintypes.DWORD),
    ]


@dataclass
class FullscreenStatus:
    """全画面アプリの検出結果。"""

    active: bool
    reason: str = ""       # 「全画面ゲーム」など、UI に出す短い説明
    window_title: str = ""


class FullscreenMonitor:
    """前面で全画面アプリが動いているかを調べる。"""

    def __init__(self) -> None:
        self.available = False
        self.last_error: str = ""
        self._own_pid = os.getpid()
        try:
            self._user32 = ctypes.windll.user32
            self._shell32 = ctypes.windll.shell32
            self.check()  # 一度呼んで動作確認
            self.available = True
        except Exception as exc:
            self.last_error = f"全画面アプリの検出を利用できません: {exc}"
            log.warning(self.last_error)

    def check(self) -> FullscreenStatus:
        """今この瞬間、全画面アプリが前面にあるか。"""
        status = self._check_notification_state()
        if status.active:
            return status
        return self._check_foreground_window()

    # --- 方法1: OS に尋ねる ---

    def _check_notification_state(self) -> FullscreenStatus:
        try:
            state = ctypes.c_int()
            result = self._shell32.SHQueryUserNotificationState(ctypes.byref(state))
            if result != 0:  # S_OK 以外
                return FullscreenStatus(False)
        except Exception:
            return FullscreenStatus(False)

        reason = BLOCKING_STATES.get(state.value)
        if reason is None:
            return FullscreenStatus(False)

        hwnd = self._user32.GetForegroundWindow()
        # 自分のオーバーレイが原因なら全画面アプリ扱いしない
        if hwnd and self._window_pid(hwnd) == self._own_pid:
            return FullscreenStatus(False)
        # 検索やスタートメニューは UWP のため QUNS_APP として報告されるが、
        # 一時的なシェルの画面なので全画面アプリとは扱わない
        if hwnd and self._window_class(hwnd) in SHELL_WINDOW_CLASSES:
            return FullscreenStatus(False)
        return FullscreenStatus(True, reason, self._window_title(hwnd))

    # --- 方法2: 前面ウィンドウの大きさで判定 ---

    def _check_foreground_window(self) -> FullscreenStatus:
        try:
            hwnd = self._user32.GetForegroundWindow()
            if not hwnd:
                return FullscreenStatus(False)
            if self._window_pid(hwnd) == self._own_pid:
                return FullscreenStatus(False)  # 自分のオーバーレイ

            class_name = self._window_class(hwnd)
            if class_name in SHELL_WINDOW_CLASSES:
                return FullscreenStatus(False)  # デスクトップやタスクバー

            window = _RECT()
            if not self._user32.GetWindowRect(hwnd, ctypes.byref(window)):
                return FullscreenStatus(False)

            monitor = self._user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(_MONITORINFO)
            if not self._user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return FullscreenStatus(False)

            screen = info.rcMonitor
            covers_screen = (
                window.left <= screen.left
                and window.top <= screen.top
                and window.right >= screen.right
                and window.bottom >= screen.bottom
            )
            if not covers_screen:
                return FullscreenStatus(False)
            return FullscreenStatus(True, "全画面アプリ", self._window_title(hwnd))
        except Exception as exc:
            self.last_error = f"前面ウィンドウを調べられません: {exc}"
            return FullscreenStatus(False)

    # --- Win32 の小道具 ---

    def _foreground_is_own_window(self) -> bool:
        try:
            hwnd = self._user32.GetForegroundWindow()
            return bool(hwnd) and self._window_pid(hwnd) == self._own_pid
        except Exception:
            return False

    def _foreground_title(self) -> str:
        try:
            return self._window_title(self._user32.GetForegroundWindow())
        except Exception:
            return ""

    def _window_pid(self, hwnd) -> int:
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def _window_title(self, hwnd) -> str:
        if not hwnd:
            return ""
        buffer = ctypes.create_unicode_buffer(256)
        self._user32.GetWindowTextW(hwnd, buffer, 256)
        return buffer.value

    def _window_class(self, hwnd) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        self._user32.GetClassNameW(hwnd, buffer, 256)
        return buffer.value
