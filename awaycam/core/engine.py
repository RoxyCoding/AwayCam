"""カメラ・検出・在席判定を束ねるワーカースレッド。

UI スレッドをブロックしないよう、推論は全てこのスレッドで行い、
結果は Qt シグナルで UI へ渡す。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

from ..logging_setup import get_logger
from ..settings import Settings
from .camera import Camera, CameraState
from .detector import DetectionResult, create_detector, model_path_for
from .fullscreen_monitor import FullscreenMonitor
from .input_monitor import InputMonitor
from .presence import PresenceSnapshot, PresenceState, PresenceTracker

log = get_logger("engine")

# 全画面をこの回数連続で観測してから一時停止する。
# Alt+Tab や検索画面のように一瞬だけ全画面になるものを無視するため。
FULLSCREEN_DEBOUNCE_CHECKS = 3


class DetectionEngine(QThread):
    """常駐する判定ループ。"""

    # UI 更新用シグナル
    snapshot_ready = Signal(object)         # PresenceSnapshot
    state_changed = Signal(object, object)  # 旧 PresenceState, 新 PresenceState
    frame_ready = Signal(object, object)    # np.ndarray(BGR), DetectionResult
    camera_error = Signal(str)              # エラーメッセージ（空文字なら復旧）

    def __init__(self, settings: Settings, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._running = False

        self.camera = Camera(index=settings.camera_index)
        self.detector = create_detector(settings)
        self._detector_backend = settings.detector_backend
        self.input_monitor = InputMonitor()
        self.fullscreen_monitor = FullscreenMonitor()
        self.tracker = PresenceTracker(
            away_seconds=settings.away_seconds,
            return_consecutive_hits=settings.return_consecutive_hits,
            return_on_user_input=settings.return_on_user_input,
            on_state_change=self._emit_state_change,
        )

        self._paused = False
        self._pause_until: Optional[float] = None  # None かつ _paused=True なら無期限
        self._preview_requested = False
        # 全画面アプリによる自動一時停止。手動の一時停止とは別に管理する
        # （全画面をやめたら自動で再開するが、手動停止は勝手に解除しない）。
        self._auto_paused = False
        self._auto_pause_reason = ""
        # 全画面が連続で何回観測されたか。Alt+Tab や検索画面のような
        # 一瞬だけ全画面になるものでいちいち止めないためのデバウンス。
        self._fullscreen_streak = 0
        self._last_reported_error = ""
        self._pending_reconfigure = False

    # --- 外部からの操作（UI スレッドから呼ばれる） ---

    def stop(self) -> None:
        self._running = False
        self.wait(3000)

    def set_enabled(self, enabled: bool) -> None:
        self.settings.enabled = enabled
        self.tracker.set_enabled(enabled)
        log.info("AwayCam を%sにしました", "有効" if enabled else "無効")

    def pause(self, minutes: int) -> None:
        """一時停止する。minutes=0 なら「再開するまで」。"""
        self._paused = True
        self._pause_until = None if minutes <= 0 else time.monotonic() + minutes * 60
        self.tracker.set_paused(True)
        label = "再開するまで" if minutes <= 0 else f"{minutes}分間"
        log.info("一時停止しました（%s）", label)

    def resume(self) -> None:
        self._paused = False
        self._pause_until = None
        self.tracker.set_paused(False)
        log.info("一時停止を解除しました")

    @property
    def is_paused(self) -> bool:
        """手動での一時停止中か（全画面による自動停止は含まない）。"""
        return self._paused

    @property
    def is_auto_paused(self) -> bool:
        return self._auto_paused

    @property
    def auto_pause_reason(self) -> str:
        return self._auto_pause_reason

    @property
    def pause_remaining_seconds(self) -> Optional[float]:
        if not self._paused or self._pause_until is None:
            return None
        return max(0.0, self._pause_until - time.monotonic())

    def force_away(self) -> None:
        self.tracker.force_away()

    def force_present(self) -> None:
        self.tracker.force_present()

    def set_preview_enabled(self, enabled: bool) -> None:
        """設定画面が開いている間だけフレームを送る（無駄なコピーを避ける）。"""
        self._preview_requested = enabled

    def apply_settings(self, settings: Settings) -> None:
        """設定変更を次のループで反映する。"""
        self.settings = settings
        self._pending_reconfigure = True

    # --- ループ本体 ---

    def run(self) -> None:
        self._running = True
        if not self.detector.load():
            self.camera_error.emit(self.detector.last_error)

        while self._running:
            cycle_started = time.monotonic()

            if self._pending_reconfigure:
                self._reconfigure()

            if not self.settings.enabled:
                self._ensure_camera_released()
                self._emit_snapshot(PresenceState.DISABLED)
            elif self._handle_pause():
                pass  # 一時停止の処理内で snapshot 送信済み
            else:
                self._run_detection_cycle()

            # チェック間隔を守る（推論に要した時間を差し引く）
            elapsed = time.monotonic() - cycle_started
            sleep_ms = max(20, int(self._current_interval_ms() - elapsed * 1000))
            self.msleep(sleep_ms)

        self.camera.release()
        self.detector.close()
        log.info("判定ループを終了しました")

    def _run_detection_cycle(self) -> None:
        if not self.camera.is_open and self.camera.state is CameraState.CLOSED:
            self.camera.open()

        frame = self.camera.read()
        # カメラが生きているかは「今回フレームが取れたか」ではなく接続状態で判断する。
        # 1枚のコマ落ちで「カメラエラー」に転落すると、判定が在席とエラーを往復して
        # 離席がいつまでも確定しなくなるため。
        camera_healthy = self.camera.state is CameraState.RUNNING

        if frame is None and camera_healthy:
            # 一時的なコマ落ち。状態は変えず、表示だけ更新してこの周期は見送る。
            self.snapshot_ready.emit(self.tracker.peek())
            return

        camera_ok = camera_healthy
        self._report_camera_error(
            "" if camera_ok else (self.camera.last_error or "カメラを準備中です")
        )

        result = DetectionResult(False, [])
        if frame is not None:
            result = self.detector.detect(frame, int(time.monotonic() * 1000))
            if self._preview_requested:
                self.frame_ready.emit(frame, result)

        # モデルが読めていない場合も「判定不能」として扱い、離席にはしない
        if not self.detector.is_ready:
            camera_ok = False
            self._report_camera_error(self.detector.last_error)

        snapshot = self.tracker.update(
            person_present=result.person_present,
            camera_ok=camera_ok,
            user_input_recent=self._had_recent_input(),
            best_score=result.best_score,
        )
        self.snapshot_ready.emit(snapshot)

    def _current_interval_ms(self) -> int:
        """現在の状態に応じたチェック間隔。

        離席中は短い間隔で回して、席に戻ったときの復帰を速くする。
        """
        if self.tracker.state is PresenceState.AWAY:
            return self.settings.away_check_interval_ms
        return self.settings.check_interval_ms

    def _had_recent_input(self) -> bool:
        """直近のチェック間隔内にキーボード/マウス操作があったか。"""
        if not self.settings.return_on_user_input:
            return False
        window_s = max(1.0, self.settings.check_interval_ms / 1000.0 * 1.5)
        return self.input_monitor.had_input_within(window_s)

    def _handle_pause(self) -> bool:
        """一時停止中なら True。手動 / 全画面アプリによる自動、両方を見る。"""
        if self._paused:
            # 時間指定の一時停止が満了したら自動再開
            if self._pause_until is not None and time.monotonic() >= self._pause_until:
                self.resume()
            else:
                self._pause_camera_and_report("")
                return True

        if self._handle_fullscreen_pause():
            return True
        return False

    def _handle_fullscreen_pause(self) -> bool:
        """全画面アプリが前面にある間だけ自動で止める。"""
        if not self.settings.pause_on_fullscreen:
            self._fullscreen_streak = 0
            if self._auto_paused:
                self._end_auto_pause()
            return False

        status = self.fullscreen_monitor.check()
        if not status.active:
            # 解除は即座に行う（ゲームを閉じたらすぐ再開してほしいため）
            self._fullscreen_streak = 0
            if self._auto_paused:
                self._end_auto_pause()
            return False

        self._fullscreen_streak += 1
        if self._fullscreen_streak < FULLSCREEN_DEBOUNCE_CHECKS:
            return False  # まだ様子見。判定は通常どおり続ける

        if not self._auto_paused:
            self._auto_paused = True
            self._auto_pause_reason = status.reason
            self.tracker.set_paused(True)
            log.info(
                "%s を検知したため自動的に一時停止します（%s）",
                status.reason, status.window_title or "タイトル不明",
            )
        self._pause_camera_and_report(self._auto_pause_reason)
        return True

    def _end_auto_pause(self) -> None:
        self._fullscreen_streak = 0
        log.info("全画面アプリが終了したため自動一時停止を解除します")
        self._auto_paused = False
        self._auto_pause_reason = ""
        # 全画面が連続で何回観測されたか。Alt+Tab や検索画面のような
        # 一瞬だけ全画面になるものでいちいち止めないためのデバウンス。
        self._fullscreen_streak = 0
        self.tracker.set_paused(False)

    def _pause_camera_and_report(self, reason: str) -> None:
        if self.settings.release_camera_while_paused:
            self._ensure_camera_released()
        self._emit_snapshot(PresenceState.PAUSED, reason)

    def _ensure_camera_released(self) -> None:
        if self.camera.state is not CameraState.CLOSED:
            self.camera.release()

    def _reconfigure(self) -> None:
        self._pending_reconfigure = False
        settings = self.settings

        if settings.camera_index != self.camera.index:
            log.info("カメラを %d から %d に切り替えます", self.camera.index, settings.camera_index)
            self.camera.release()
            self.camera.index = settings.camera_index

        # 検出方式そのものが変わったら作り直す
        if settings.detector_backend != self._detector_backend:
            log.info(
                "検出方式を %s から %s に切り替えます",
                self._detector_backend, settings.detector_backend,
            )
            self.detector.close()
            self.detector = create_detector(settings)
            self.detector.load()
            self._detector_backend = settings.detector_backend
        elif str(self.detector.model_path) != model_path_for(settings):
            self.detector.model_path = Path(model_path_for(settings))
            self.detector.load()
        else:
            self.detector.set_confidence(settings.detection_confidence)
        self.detector.set_min_height_ratio(settings.min_person_height_ratio)
        self.detector.set_min_shoulder_ratio(settings.min_shoulder_width_ratio)

        self.tracker.configure(
            away_seconds=settings.away_seconds,
            return_consecutive_hits=settings.return_consecutive_hits,
            return_on_user_input=settings.return_on_user_input,
        )
        self.tracker.set_enabled(settings.enabled)

    def _report_camera_error(self, message: str) -> None:
        if message != self._last_reported_error:
            self._last_reported_error = message
            self.camera_error.emit(message)

    def _emit_snapshot(self, state: PresenceState, message: str = "") -> None:
        self.snapshot_ready.emit(
            PresenceSnapshot(
                state=state,
                person_present=False,
                seconds_until_away=float(self.settings.away_seconds),
                consecutive_hits=0,
                message=message,
            )
        )

    def _emit_state_change(self, old: PresenceState, new: PresenceState) -> None:
        log.info("状態遷移: %s から %s", old.value, new.value)
        self.state_changed.emit(old, new)
