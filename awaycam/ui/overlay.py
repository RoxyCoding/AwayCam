"""離席中に表示するフルスクリーン画像オーバーレイ。

- マルチモニター対応（全画面 / メインのみ / 指定モニター）
- Esc（または設定したホットキー）でいつでも手動解除できる
  ※カメラ故障時にユーザーが操作不能になるのを防ぐため必須
- これは画面ロックではない。セキュリティ機能ではない。
- 排他フルスクリーンのゲーム上では最前面化が効かないことがあるが、
  エラーにせずログに残して静かに継続する。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap, QScreen
from PySide6.QtWidgets import QWidget

from ..logging_setup import get_logger
from ..settings import SUPPORTED_IMAGE_SUFFIXES

log = get_logger("overlay")


class OverlayWindow(QWidget):
    """1つのモニターを覆う画像表示ウィンドウ。"""

    def __init__(
        self,
        screen: QScreen,
        pixmap: Optional[QPixmap],
        display_mode: str,
        background: QColor,
        on_dismiss: Callable[[], None],
        allow_escape: bool,
        fallback_text: str = "",
    ) -> None:
        super().__init__(None)
        self._pixmap = pixmap
        self._display_mode = display_mode
        self._background = background
        self._on_dismiss = on_dismiss
        self._allow_escape = allow_escape
        self._fallback_text = fallback_text

        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool  # タスクバーに出さない
        )
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setCursor(Qt.BlankCursor)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())

    def set_pixmap(self, pixmap: Optional[QPixmap], fallback_text: str = "") -> None:
        """表示中の画像を差し替える（スライドショーの切り替え用）。"""
        self._pixmap = pixmap
        self._fallback_text = fallback_text
        self.update()

    # --- 描画 ---

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt の命名規則)
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._background)

        if self._pixmap is None or self._pixmap.isNull():
            self._paint_fallback(painter)
            painter.end()
            return

        target = self._compute_target_rect(self._pixmap, self.rect())
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self._display_mode == "fill":
            # 画面全体を埋める: はみ出す部分は切り抜く
            painter.setClipRect(self.rect())
        painter.drawPixmap(target, self._pixmap)
        painter.end()

    def _compute_target_rect(self, pixmap: QPixmap, area: QRect) -> QRect:
        pw, ph = pixmap.width(), pixmap.height()
        aw, ah = area.width(), area.height()
        if pw <= 0 or ph <= 0:
            return area

        if self._display_mode == "center":
            # 原寸を中央に表示（画面より大きい場合はそのままはみ出させる）
            width, height = pw, ph
        else:
            scale_fit = min(aw / pw, ah / ph)
            scale_fill = max(aw / pw, ah / ph)
            scale = scale_fill if self._display_mode == "fill" else scale_fit
            width, height = int(pw * scale), int(ph * scale)

        return QRect((aw - width) // 2, (ah - height) // 2, width, height)

    def _paint_fallback(self, painter: QPainter) -> None:
        """画像が指定されていない/読めない場合の代替表示。"""
        painter.setPen(QColor("#e6e6e6"))
        font = painter.font()
        font.setPointSize(28)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, self._fallback_text or "離席中")

    # --- 入力 ---

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._allow_escape and event.key() == Qt.Key_Escape:
            log.info("Esc キーによりオーバーレイを解除しました")
            self._on_dismiss()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        # 逃げ道をもう一つ用意しておく
        if self._allow_escape:
            log.info("ダブルクリックによりオーバーレイを解除しました")
            self._on_dismiss()


class OverlayManager(QObject):
    """全モニター分のオーバーレイをまとめて管理する。

    画像が複数指定されている場合は、一定間隔で順番に切り替え、
    最後まで行ったら先頭へ戻る（ループ表示）。
    """

    def __init__(self, on_dismiss: Optional[Callable[[], None]] = None) -> None:
        super().__init__()
        self._windows: list[OverlayWindow] = []
        self._on_dismiss = on_dismiss or (lambda: None)
        self.last_error: str = ""

        # --- スライドショー ---
        self._image_paths: list[str] = []
        self._index = 0
        self._slide_timer = QTimer(self)
        self._slide_timer.timeout.connect(self._advance_slide)

    @property
    def is_visible(self) -> bool:
        return bool(self._windows)

    def show(
        self,
        image_paths: list[str],
        display_mode: str = "fit",
        monitor_target: str = "all",
        monitor_index: int = 0,
        background_color: str = "#000000",
        allow_escape: bool = True,
        slideshow_interval_seconds: int = 10,
    ) -> None:
        """オーバーレイを表示する。画像が読めなくても必ず何かを表示する。"""
        self.hide()

        self._image_paths = [p for p in (image_paths or []) if p]
        self._index = 0
        pixmap, message = self._load_current()
        screens = self._select_screens(monitor_target, monitor_index)
        if not screens:
            log.warning("表示対象のモニターが見つからないため、メイン画面を使います")
            primary = QGuiApplication.primaryScreen()
            screens = [primary] if primary else []
        if not screens:
            self.last_error = "利用可能なモニターがありません"
            log.error(self.last_error)
            return

        background = QColor(background_color)
        if not background.isValid():
            background = QColor("#000000")

        for screen in screens:
            window = OverlayWindow(
                screen=screen,
                pixmap=pixmap,
                display_mode=display_mode,
                background=background,
                on_dismiss=self._on_dismiss,
                allow_escape=allow_escape,
                fallback_text=message,
            )
            window.showFullScreen()
            self._raise_quietly(window)
            self._windows.append(window)

        log.info(
            "オーバーレイを %d 画面に表示しました（画像 %d 枚）",
            len(self._windows), len(self._image_paths),
        )

        # 2枚以上あるときだけ切り替えを始める
        if len(self._image_paths) > 1:
            self._slide_timer.start(max(1, slideshow_interval_seconds) * 1000)

    def hide(self) -> None:
        self._slide_timer.stop()
        for window in self._windows:
            window.close()
        self._windows.clear()

    def refresh_screens_if_visible(self, **kwargs) -> None:
        """モニター構成が変わったときに貼り直す。"""
        if self.is_visible:
            log.info("モニター構成の変更を検知したためオーバーレイを再構築します")
            self.show(**kwargs)

    # --- スライドショー ---

    def _advance_slide(self) -> None:
        """次の画像へ進む。最後まで行ったら先頭に戻る。"""
        if not self._windows or len(self._image_paths) < 2:
            return
        self._index = (self._index + 1) % len(self._image_paths)
        pixmap, message = self._load_current()
        for window in self._windows:
            window.set_pixmap(pixmap, message)

    def _load_current(self) -> tuple[Optional[QPixmap], str]:
        """現在の番号の画像を読む。読めなければ次の候補を順に試す。

        一部の画像が消えていてもスライドショーが止まらないようにする。
        """
        if not self._image_paths:
            return self._load_pixmap("")

        message = ""
        for _ in range(len(self._image_paths)):
            pixmap, message = self._load_pixmap(self._image_paths[self._index])
            if pixmap is not None:
                return pixmap, message
            # 読めなかったので次の画像を試す
            self._index = (self._index + 1) % len(self._image_paths)

        # すべて読めなかった場合は、最後のメッセージをそのまま出す
        return None, message

    # --- 内部処理 ---

    def _load_pixmap(self, image_path: str) -> tuple[Optional[QPixmap], str]:
        if not image_path:
            return None, "離席中\n（表示する画像が設定されていません）"

        path = Path(image_path)
        if not path.exists():
            message = f"離席中\n（画像が見つかりません: {path.name}）"
            self.last_error = f"指定された画像が存在しません: {path}"
            log.warning(self.last_error)
            return None, message

        if path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            self.last_error = f"未対応の画像形式です: {path.suffix}"
            log.warning(self.last_error)

        image = QImage(str(path))
        if image.isNull():
            self.last_error = f"画像を読み込めません: {path}"
            log.warning(self.last_error)
            return None, f"離席中\n（画像を読み込めません: {path.name}）"

        self.last_error = ""
        return QPixmap.fromImage(image), ""

    def _select_screens(self, monitor_target: str, monitor_index: int) -> list[QScreen]:
        screens = QGuiApplication.screens()
        if monitor_target == "primary":
            primary = QGuiApplication.primaryScreen()
            return [primary] if primary else []
        if monitor_target == "index":
            if 0 <= monitor_index < len(screens):
                return [screens[monitor_index]]
            log.warning(
                "指定モニター %d は存在しません（現在 %d 台）。全画面に表示します",
                monitor_index, len(screens),
            )
            return screens
        return screens

    def _raise_quietly(self, window: OverlayWindow) -> None:
        """最前面化を試みる。失敗しても例外にせずログに残すだけ。

        排他フルスクリーンのゲーム上では効かないことがあるが、それは想定内。
        """
        try:
            window.raise_()
            window.activateWindow()
        except Exception as exc:
            log.info("最前面化に失敗しました（排他フルスクリーンの可能性）: %s", exc)
