"""メイン画面。現在の状態を大きく表示する。

  在席中 / 離席まであと5秒 / 離席中 / 一時停止中 / カメラエラー
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.presence import PresenceSnapshot, PresenceState
from ..logging_setup import get_logger
from . import theme

log = get_logger("main_window")


class MainWindow(QWidget):
    """状態表示と基本操作をまとめた常駐アプリのメイン画面。"""

    def __init__(
        self,
        on_open_settings: Callable[[], None],
        on_toggle_enabled: Callable[[bool], None],
        on_test_away: Callable[[], None],
        on_return: Callable[[], None],
        on_toggle_pause: Callable[[], None],
    ) -> None:
        super().__init__()
        self._on_open_settings = on_open_settings
        self._on_toggle_enabled = on_toggle_enabled
        self._on_toggle_pause = on_toggle_pause
        self._enabled = True
        self._camera_error = ""  # 直近の具体的なエラー文言
        # 閉じるボタンの動作。app 側で「トレイへ最小化」を差し込む。
        self.on_close_requested: Optional[Callable[[], None]] = None

        self.setWindowTitle("AwayCam")
        self.setMinimumSize(480, 380)

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(24)

        # --- 状態カード ---
        card = QFrame()
        card.setProperty("role", "card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 32, 28, 32)
        card_layout.setSpacing(10)

        self.status_dot = QLabel("●")
        self.status_dot.setAlignment(Qt.AlignCenter)
        self.status_dot.setStyleSheet(f"font-size: 26px; color: {theme.COLOR_PRESENT};")

        self.status_label = QLabel("起動中…")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 34px; font-weight: 600;")

        self.detail_label = QLabel("カメラを準備しています")
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_label.setWordWrap(True)
        self.detail_label.setProperty("role", "muted")

        card_layout.addWidget(self.status_dot)
        card_layout.addWidget(self.status_label)
        card_layout.addWidget(self.detail_label)
        root.addWidget(card, stretch=1)

        # --- 操作ボタン ---
        buttons = QHBoxLayout()
        buttons.setSpacing(10)

        self.enable_button = QPushButton("無効にする")
        self.enable_button.clicked.connect(self._toggle_enabled)

        self.pause_button = QPushButton("一時停止")
        self.pause_button.clicked.connect(self._on_toggle_pause)

        self.test_button = QPushButton("離席をテスト")
        self.test_button.clicked.connect(on_test_away)

        self.return_button = QPushButton("復帰")
        self.return_button.clicked.connect(on_return)

        settings_button = QPushButton("設定")
        settings_button.setProperty("role", "accent")
        settings_button.clicked.connect(on_open_settings)

        for button in (self.enable_button, self.pause_button, self.test_button, self.return_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(settings_button)
        root.addLayout(buttons)

        # --- プライバシー注記（常に見える場所に置く） ---
        privacy = QLabel(
            "カメラ映像はこのPC内でのみ処理され、保存も外部送信も行いません。"
        )
        privacy.setProperty("role", "muted")
        privacy.setAlignment(Qt.AlignCenter)
        privacy.setWordWrap(True)
        root.addWidget(privacy)

    # --- 状態の反映 ---

    def update_snapshot(self, snapshot: PresenceSnapshot) -> None:
        state = snapshot.state

        if state is PresenceState.AWAY:
            self._set_status("離席中", theme.COLOR_AWAY,
                             "人物を検出すると自動で復帰します（Esc で手動解除）")
        elif state is PresenceState.PAUSED:
            detail = (
                f"{snapshot.message}を検知したため自動で停止しています"
                if snapshot.message else "カメラは解放されています"
            )
            self._set_status("一時停止中", theme.COLOR_PAUSED, detail)
        elif state is PresenceState.DISABLED:
            self._set_status("無効", theme.COLOR_PAUSED,
                             "AwayCam は停止しています")
        elif state is PresenceState.UNKNOWN:
            # 原因が分かる具体的な文言を優先する（汎用文言で上書きしない）
            detail = self._camera_error or snapshot.message or "カメラを利用できません"
            self._set_status("カメラエラー", theme.COLOR_ERROR,
                             f"{detail}\n離席判定は行いません")
        elif snapshot.person_present:
            self._set_status("在席中", theme.COLOR_PRESENT,
                             f"人物を検出中（信頼度 {snapshot.best_score:.0%}）")
        else:
            remaining = int(snapshot.seconds_until_away + 0.999)
            self._set_status(
                f"離席まであと {remaining} 秒",
                theme.COLOR_COUNTDOWN,
                "人物が検出されていません",
            )

    def update_camera_error(self, message: str) -> None:
        """エンジンからの具体的なエラー文言を覚えておく（空文字なら復旧）。"""
        self._camera_error = message
        if message:
            self.detail_label.setText(message)

    def set_enabled_state(self, enabled: bool) -> None:
        self._enabled = enabled
        self.enable_button.setText("有効にする" if not enabled else "無効にする")

    def set_paused_state(self, paused: bool) -> None:
        self.pause_button.setText("再開" if paused else "一時停止")

    # --- ウィンドウ操作 ---

    def closeEvent(self, event) -> None:
        """閉じるボタンでは終了せず、トレイへ最小化する（常駐アプリのため）。"""
        if self.on_close_requested is not None:
            event.ignore()
            self.on_close_requested()
        else:
            super().closeEvent(event)

    # --- 内部処理 ---

    def _set_status(self, text: str, color: str, detail: str) -> None:
        self.status_label.setText(text)
        self.status_dot.setStyleSheet(f"font-size: 26px; color: {color};")
        self.detail_label.setText(detail)

    def _toggle_enabled(self) -> None:
        self._enabled = not self._enabled
        self.set_enabled_state(self._enabled)
        self._on_toggle_enabled(self._enabled)
