"""タスクトレイの常駐アイコンとメニュー。

アイコンは現在の状態を示すインジケーターを兼ねる:
  緑 = 在席中 / 青 = 離席中 / 橙 = 離席カウントダウン中
  灰 = 一時停止・無効 / 赤 = エラー

画像ファイルを持たず、QPainter で描画して生成する（配布物を1つ減らすため）。
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..core.presence import PresenceSnapshot, PresenceState
from ..logging_setup import get_logger
from ..settings import PAUSE_DURATION_CHOICES
from . import theme

log = get_logger("tray")

ICON_SIZE = 64

# 状態ごとの色と説明
STATE_APPEARANCE = {
    PresenceState.PRESENT:  (theme.COLOR_PRESENT,  "在席中"),
    PresenceState.AWAY:     (theme.COLOR_AWAY,     "離席中"),
    PresenceState.PAUSED:   (theme.COLOR_PAUSED,   "一時停止中"),
    PresenceState.DISABLED: (theme.COLOR_PAUSED,   "無効"),
    PresenceState.UNKNOWN:  (theme.COLOR_ERROR,    "カメラエラー"),
}


def make_indicator_icon(color: str, hollow: bool = False) -> QIcon:
    """状態色の丸いインジケーターアイコンを作る。

    hollow=True で中抜き（無効・一時停止を一目で区別できるようにする）。
    """
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    margin = 6
    circle = QRect(margin, margin, ICON_SIZE - margin * 2, ICON_SIZE - margin * 2)

    pen_width = 8
    painter.setPen(Qt.NoPen)
    if hollow:
        # 輪郭だけ描く
        from PySide6.QtGui import QPen

        painter.setPen(QPen(QColor(color), pen_width))
        painter.setBrush(Qt.NoBrush)
        inset = pen_width // 2
        painter.drawEllipse(circle.adjusted(inset, inset, -inset, -inset))
    else:
        painter.setBrush(QColor(color))
        painter.drawEllipse(circle)
    painter.end()

    return QIcon(pixmap)


class TrayIcon(QSystemTrayIcon):
    """常駐アイコン。ウィンドウを閉じてもここに残る。"""

    def __init__(
        self,
        on_open_settings: Callable[[], None],
        on_show_window: Callable[[], None],
        on_toggle_enabled: Callable[[bool], None],
        on_pause: Callable[[int], None],
        on_resume: Callable[[], None],
        on_quit: Callable[[], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._on_show_window = on_show_window
        self._on_toggle_enabled = on_toggle_enabled
        self._on_pause = on_pause
        self._on_resume = on_resume

        self._current_color = ""
        self._current_hollow: Optional[bool] = None

        self.setIcon(make_indicator_icon(theme.COLOR_PRESENT))
        self.setToolTip("AwayCam")

        menu = QMenu()

        # 状態表示（クリック不可の見出し）
        self._status_action = QAction("起動中…", menu)
        self._status_action.setEnabled(False)
        menu.addAction(self._status_action)
        menu.addSeparator()

        self._enabled_action = QAction("有効", menu)
        self._enabled_action.setCheckable(True)
        self._enabled_action.setChecked(True)
        self._enabled_action.triggered.connect(self._on_toggle_enabled)
        menu.addAction(self._enabled_action)

        # --- 一時停止のサブメニュー ---
        self._pause_menu = QMenu("一時停止", menu)
        self._pause_group = QActionGroup(self._pause_menu)
        self._pause_group.setExclusive(True)
        for minutes in PAUSE_DURATION_CHOICES:
            label = "再開するまで" if minutes == 0 else (
                f"{minutes}分" if minutes < 60 else "1時間"
            )
            action = QAction(label, self._pause_menu)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked, m=minutes: self._on_pause(m))
            self._pause_group.addAction(action)
            self._pause_menu.addAction(action)
        menu.addMenu(self._pause_menu)

        self._resume_action = QAction("再開", menu)
        self._resume_action.triggered.connect(self._handle_resume)
        self._resume_action.setVisible(False)
        menu.addAction(self._resume_action)

        menu.addSeparator()
        open_action = QAction("設定を開く", menu)
        open_action.triggered.connect(on_open_settings)
        menu.addAction(open_action)

        show_action = QAction("AwayCam を表示", menu)
        show_action.triggered.connect(on_show_window)
        menu.addAction(show_action)

        menu.addSeparator()
        quit_action = QAction("終了", menu)
        quit_action.triggered.connect(on_quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    # --- 状態の反映 ---

    def update_snapshot(self, snapshot: PresenceSnapshot) -> None:
        state = snapshot.state
        color, label = STATE_APPEARANCE.get(state, (theme.COLOR_PAUSED, "不明"))

        # 在席中でも人物が見えていなければカウントダウン色にする
        if state is PresenceState.PRESENT and not snapshot.person_present:
            color = theme.COLOR_COUNTDOWN
            label = f"離席まであと {int(snapshot.seconds_until_away + 0.999)} 秒"

        if state is PresenceState.PAUSED and snapshot.message:
            label = f"一時停止中（{snapshot.message}）"

        hollow = state in (PresenceState.PAUSED, PresenceState.DISABLED)
        self._set_icon(color, hollow)

        self._status_action.setText(label)
        self.setToolTip(f"AwayCam — {label}")

        paused = state is PresenceState.PAUSED
        self._resume_action.setVisible(paused)
        self._pause_menu.menuAction().setVisible(not paused)

    def set_enabled_state(self, enabled: bool) -> None:
        self._enabled_action.setChecked(enabled)

    def notify(self, title: str, message: str, warning: bool = False) -> None:
        """トレイ通知を出す。対応していない環境では静かに無視される。"""
        try:
            icon = QSystemTrayIcon.Warning if warning else QSystemTrayIcon.Information
            self.showMessage(title, message, icon, 5000)
        except Exception as exc:
            log.info("トレイ通知を表示できませんでした: %s", exc)

    # --- 内部処理 ---

    def _set_icon(self, color: str, hollow: bool) -> None:
        # 同じ見た目なら描き直さない（毎秒の再生成を避ける）
        if color == self._current_color and hollow == self._current_hollow:
            return
        self._current_color = color
        self._current_hollow = hollow
        self.setIcon(make_indicator_icon(color, hollow))

    def _handle_resume(self) -> None:
        for action in self._pause_group.actions():
            action.setChecked(False)
        self._on_resume()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # 左クリック / ダブルクリックでメイン画面を出す
        if reason in (
            QSystemTrayIcon.Trigger,
            QSystemTrayIcon.DoubleClick,
        ):
            self._on_show_window()
