"""AwayCam アプリケーション本体。各コンポーネントを配線する。

実装済み: カメラ → 人物検出 → 離席判定 → 画像表示 → タスクトレイ常駐 → 自動起動
（設定GUI・ホットキーはこの後のフェーズで追加する）
"""
from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import autostart
from .single_instance import InstanceServer, is_already_running
from .core.audio import AudioMuter
from .core.engine import DetectionEngine
from .core import power_monitor
from .core.presence import PresenceState
from .logging_setup import get_logger, setup_logging
from .settings import Settings
from .ui import theme
from .ui.main_window import MainWindow
from .ui.overlay import OverlayManager
from .ui.settings_window import SettingsWindow
from .ui.tray import TrayIcon

log = get_logger("app")


class AwayCamApp(QObject):
    """アプリ全体のライフサイクルを持つ調停役。"""

    def __init__(self, app: QApplication, start_minimized: bool = False) -> None:
        super().__init__()
        self.app = app
        self.settings = Settings.load()
        self._force_minimized = start_minimized
        self._quitting = False

        theme.apply_theme(app, self.settings.theme)

        # 登録済みの自動起動コマンドが古ければ更新しておく
        autostart.sync_if_stale(self.settings.start_with_windows)

        self.overlay = OverlayManager(on_dismiss=self._on_overlay_dismissed)
        self.settings_window: Optional[SettingsWindow] = None
        self.audio = AudioMuter()
        if self.settings.mute_audio_on_away and not self.audio.available:
            log.warning("音声ミュートは利用できません: %s", self.audio.last_error)

        self.engine = DetectionEngine(self.settings)
        self.engine.snapshot_ready.connect(self._on_snapshot, Qt.QueuedConnection)
        self.engine.state_changed.connect(self._on_state_changed, Qt.QueuedConnection)
        self.engine.camera_error.connect(self._on_camera_error, Qt.QueuedConnection)
        self.engine.frame_ready.connect(self._on_frame, Qt.QueuedConnection)

        self.window = MainWindow(
            on_open_settings=self._open_settings,
            on_toggle_enabled=self._set_enabled,
            on_test_away=self.engine.force_away,
            on_return=self.engine.force_present,
            on_toggle_pause=self._toggle_pause,
        )
        self.window.set_enabled_state(self.settings.enabled)
        # 閉じるボタンでは終了せず、トレイへ最小化する
        self.window.on_close_requested = self._hide_to_tray

        # 2つ目の起動を受け付けて、既存のウィンドウを出す係
        self.instance_server = InstanceServer(self._show_window)
        self.instance_server.listen()

        self.tray: Optional[TrayIcon] = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = TrayIcon(
                on_open_settings=self._open_settings,
                on_show_window=self._show_window,
                on_toggle_enabled=self._set_enabled,
                on_pause=self._pause_for,
                on_resume=self._resume,
                on_quit=self.quit,
            )
            self.tray.set_enabled_state(self.settings.enabled)
            self.tray.show()
        else:
            log.warning("タスクトレイを利用できない環境です")

        # スリープ / 復帰に追従する（復帰後にカメラが死んだままになるのを防ぐ）
        self._power_filter = power_monitor.install(
            app,
            on_suspend=self._on_system_suspend,
            on_resume=self._on_system_resume,
        )

        # モニター構成の変更に追従する
        app.screenAdded.connect(self._on_screens_changed)
        app.screenRemoved.connect(self._on_screens_changed)

    def start(self) -> None:
        self.engine.start()
        if self._should_start_minimized():
            log.info("最小化状態で起動しました（トレイに常駐）")
            if self.tray is not None:
                self.tray.notify("AwayCam", "トレイで動作しています")
        else:
            self.window.show()

    def quit(self) -> None:
        """トレイの「終了」から呼ばれる。ここでのみ本当に終了する。"""
        self._quitting = True
        self.app.quit()

    def shutdown(self) -> None:
        log.info("AwayCam を終了します")
        self.overlay.hide()
        # 自分がミュートしたまま終了すると、音が戻せなくなってしまう
        self.audio.unmute()
        if self.tray is not None:
            self.tray.hide()
        self.instance_server.close()
        self.engine.stop()

    # --- エンジンからの通知 ---

    def _on_snapshot(self, snapshot) -> None:
        self.window.update_snapshot(snapshot)
        if self.tray is not None:
            self.tray.update_snapshot(snapshot)
        if self.settings_window is not None:
            self.settings_window.update_snapshot(snapshot)

    def _on_frame(self, frame, result) -> None:
        """設定画面のプレビュー用。開いているときだけ届く。"""
        if self.settings_window is not None:
            self.settings_window.update_frame(frame, result)

    def _on_state_changed(self, _old: PresenceState, new: PresenceState) -> None:
        if new is PresenceState.AWAY:
            self._show_overlay()
            if self.settings.mute_audio_on_away:
                self.audio.mute()
        else:
            self.overlay.hide()
            # ミュートは常に解除を試みる。設定を切った直後でも
            # 自分が消した音が残らないようにするため。
            self.audio.unmute()

    def _on_camera_error(self, message: str) -> None:
        self.window.update_camera_error(message)
        if self.settings_window is not None:
            self.settings_window.update_camera_error(message)
        if message and self.tray is not None:
            self.tray.notify("AwayCam — カメラエラー", message, warning=True)

    # --- オーバーレイ ---

    def _overlay_kwargs(self) -> dict:
        return dict(
            image_paths=self.settings.image_paths,
            display_mode=self.settings.display_mode,
            monitor_target=self.settings.monitor_target,
            monitor_index=self.settings.monitor_index,
            background_color=self.settings.background_color,
            allow_escape=self.settings.allow_escape_to_dismiss,
            slideshow_interval_seconds=self.settings.slideshow_interval_seconds,
        )

    def _show_overlay(self) -> None:
        self.overlay.show(**self._overlay_kwargs())

    def _on_overlay_dismissed(self) -> None:
        """Esc などで手動解除されたとき。判定も在席へ戻す。"""
        self.overlay.hide()
        self.audio.unmute()
        self.engine.force_present()

    # --- 電源イベント ---

    def _on_system_suspend(self) -> None:
        """スリープ直前。眠っている間に見せる画像も音の細工も要らない。"""
        self.engine.notify_system_suspend()
        self.overlay.hide()
        # ミュートしたまま眠ると、復帰後に音が戻らなくなる
        self.audio.unmute()

    def _on_system_resume(self) -> None:
        self.engine.notify_system_resume()

    def _on_screens_changed(self, *_args) -> None:
        QTimer.singleShot(
            300, lambda: self.overlay.refresh_screens_if_visible(**self._overlay_kwargs())
        )

    # --- ウィンドウ ---

    def _should_start_minimized(self) -> bool:
        return self._force_minimized or self.settings.start_minimized

    def _show_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _hide_to_tray(self) -> None:
        """閉じるボタン。終了せずトレイへ。"""
        self.window.hide()
        if self.tray is not None:
            self.tray.notify("AwayCam", "トレイで動作を続けています")

    # --- 操作 ---

    def _set_enabled(self, enabled: bool) -> None:
        self.settings.enabled = enabled
        self.settings.save()
        self.engine.set_enabled(enabled)
        self.window.set_enabled_state(enabled)
        if self.tray is not None:
            self.tray.set_enabled_state(enabled)
        if not enabled:
            self.overlay.hide()
            self.audio.unmute()

    def _pause_for(self, minutes: int) -> None:
        self.engine.pause(minutes)
        self.overlay.hide()
        self.audio.unmute()
        self.window.set_paused_state(True)

    def _resume(self) -> None:
        self.engine.resume()
        self.window.set_paused_state(False)

    def _toggle_pause(self) -> None:
        if self.engine.is_paused:
            self._resume()
        else:
            self._pause_for(0)  # 「再開するまで」

    def _open_settings(self) -> None:
        """設定画面を開く。開いている間だけプレビュー用のフレームを流す。"""
        if self.settings_window is not None:
            self.settings_window.raise_()
            self.settings_window.activateWindow()
            return

        window = SettingsWindow(
            settings=self.settings,
            on_apply=self._apply_settings,
            on_test_away=self.engine.force_away,
            on_test_return=self.engine.force_present,
            on_detection_test=self._run_detection_test,
            parent=self.window if self.window.isVisible() else None,
        )
        self.settings_window = window
        self.engine.set_preview_enabled(True)
        try:
            window.exec()
        finally:
            self.engine.set_preview_enabled(False)
            self.settings_window = None

    def _apply_settings(self, new_settings: Settings) -> None:
        """設定画面の内容を保存し、再起動なしで反映する。"""
        autostart_changed = (
            new_settings.start_with_windows != self.settings.start_with_windows
        )
        self.settings = new_settings
        self.settings.save()

        if autostart_changed:
            autostart.apply(self.settings.start_with_windows)

        theme.apply_theme(self.app, self.settings.theme)
        self.engine.apply_settings(self.settings)
        self.window.set_enabled_state(self.settings.enabled)
        if self.tray is not None:
            self.tray.set_enabled_state(self.settings.enabled)
        if not self.settings.enabled:
            self.overlay.hide()
        if not self.settings.mute_audio_on_away:
            self.audio.unmute()
        log.info("設定を反映しました")

    def _run_detection_test(self) -> None:
        """「カメラ検出テスト」。今この瞬間の判定内容をまとめて知らせる。"""
        camera = self.engine.camera
        detector = self.engine.detector
        lines = [
            f"カメラ {self.settings.camera_index}: "
            + (f"接続中（{camera.backend_name}）" if camera.is_open
               else f"利用できません — {camera.last_error or '準備中'}"),
            f"検出方式: {detector.backend_name}: "
            + ("読み込み済み" if detector.is_ready
               else f"利用できません — {detector.last_error}"),
            f"検出信頼度のしきい値: {self.settings.detection_confidence:.2f}",
            f"距離のしきい値: "
            + ("無効" if self.settings.min_person_height_ratio <= 0
               else f"{self.settings.min_person_height_ratio:.0%} 以下は離席"),
        ]
        QMessageBox.information(
            self.settings_window or self.window,
            "カメラ検出テスト",
            "\n".join(lines) + "\n\nプレビューに検出枠が出ていれば正常です。",
        )


def main(argv: Optional[list[str]] = None) -> int:
    setup_logging()
    args = list(argv if argv is not None else sys.argv)
    start_minimized = "--minimized" in args
    log.info("AwayCam を起動します%s", "（最小化）" if start_minimized else "")

    app = QApplication(args)
    app.setApplicationName("AwayCam")

    # 既に動いていれば、そちらの画面を出して自分は終了する
    # （自動起動と手動起動が重なってカメラを取り合うのを防ぐ）
    if is_already_running():
        return 0

    # ウィンドウを全て閉じても常駐し続ける（トレイの「終了」でのみ終わる）
    app.setQuitOnLastWindowClosed(False)

    away_cam = AwayCamApp(app, start_minimized=start_minimized)
    app.aboutToQuit.connect(away_cam.shutdown)
    away_cam.start()

    return app.exec()
