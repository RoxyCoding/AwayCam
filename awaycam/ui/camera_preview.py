"""設定画面のカメラプレビュー。

映像に検出結果を重ねて表示する:
  緑の枠 = 在席とみなす人物 / 灰の点線枠 = 遠すぎて無視した人物

プレビューは設定画面が開いている間だけ描画する。映像はここでも保存しない。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core.detection_types import DetectionResult, PersonBox
from ..core.presence import PresenceSnapshot, PresenceState
from . import theme

PLACEHOLDER_TEXT = "カメラの映像を待っています…"


def _size_text(box: PersonBox) -> str:
    """しきい値と直接見比べられるよう、近さの指標を並べて出す。"""
    text = f"高さ {box.height_ratio:.2f}"
    if box.has_shoulders:
        text += f" / 肩幅 {box.shoulder_ratio:.2f}"
    return text


class CameraPreview(QWidget):
    """映像 + バウンディングボックス + 判定状況を表示する。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._frame: Optional[np.ndarray] = None
        self._result: Optional[DetectionResult] = None
        self._snapshot: Optional[PresenceSnapshot] = None
        self._message = PLACEHOLDER_TEXT

    # --- 外部から呼ぶ ---

    def update_frame(self, frame_bgr: np.ndarray, result: DetectionResult) -> None:
        self._frame = frame_bgr
        self._result = result
        self._message = ""
        self.update()

    def update_snapshot(self, snapshot: PresenceSnapshot) -> None:
        self._snapshot = snapshot
        self.update()

    def show_message(self, message: str) -> None:
        """カメラが使えないときなどの案内を出す。"""
        self._frame = None
        self._result = None
        self._message = message
        self.update()

    def clear(self) -> None:
        self._frame = None
        self._result = None
        self._message = PLACEHOLDER_TEXT
        self.update()

    # --- 描画 ---

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#1A1A1A"))

        if self._frame is None:
            self._paint_message(painter)
            painter.end()
            return

        target = self._paint_frame(painter)
        if self._result is not None:
            self._paint_boxes(painter, target)
        self._paint_status_bar(painter)
        painter.end()

    def _paint_message(self, painter: QPainter) -> None:
        painter.setPen(QColor("#B0B0B0"))
        painter.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self._message)

    def _paint_frame(self, painter: QPainter) -> QRect:
        """映像をアスペクト比を保って描き、実際に描いた矩形を返す。"""
        frame = self._frame
        height, width = frame.shape[:2]
        # BGR -> RGB。QImage は行のバイト数を明示しないと崩れることがある
        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        image = QImage(rgb.data, width, height, 3 * width, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(image)

        area = self.rect()
        scale = min(area.width() / width, area.height() / height)
        draw_w, draw_h = int(width * scale), int(height * scale)
        target = QRect(
            (area.width() - draw_w) // 2,
            (area.height() - draw_h) // 2,
            draw_w,
            draw_h,
        )
        painter.drawPixmap(target, pixmap)
        return target

    def _paint_boxes(self, painter: QPainter, target: QRect) -> None:
        frame_h, frame_w = self._frame.shape[:2]
        scale_x = target.width() / frame_w
        scale_y = target.height() / frame_h

        def to_screen(box: PersonBox) -> QRect:
            return QRect(
                target.x() + int(box.x * scale_x),
                target.y() + int(box.y * scale_y),
                int(box.width * scale_x),
                int(box.height * scale_y),
            )

        # 在席とみなす人物（緑の実線）
        for box in self._result.boxes:
            self._draw_box(
                painter, to_screen(box), QColor(theme.COLOR_PRESENT), Qt.SolidLine,
                f"人物 {box.score:.0%} / {_size_text(box)}",
            )

        # 遠すぎて無視した人物（灰の点線）
        for box in self._result.distant_boxes:
            self._draw_box(
                painter, to_screen(box), QColor("#9A9A9A"), Qt.DashLine,
                f"遠いので無視 / {_size_text(box)}",
            )

    def _draw_box(
        self, painter: QPainter, rect: QRect, color: QColor, style, label: str
    ) -> None:
        painter.setPen(QPen(color, 2, style))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)

        # ラベルは枠の上に。画面外へ出る場合は枠の内側に入れる
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text_w = metrics.horizontalAdvance(label) + 10
        text_h = metrics.height() + 4
        label_y = rect.top() - text_h
        if label_y < 0:
            label_y = rect.top() + 2
        label_rect = QRect(rect.left(), label_y, text_w, text_h)

        painter.fillRect(label_rect, color)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(label_rect, Qt.AlignCenter, label)

    def _paint_status_bar(self, painter: QPainter) -> None:
        """下端に「人物あり / なし」「離席まであと○秒」を出す。"""
        snapshot = self._snapshot
        if snapshot is None:
            return

        if snapshot.state is PresenceState.AWAY:
            text, color = "離席中", theme.COLOR_AWAY
        elif snapshot.state is PresenceState.UNKNOWN:
            text, color = "カメラエラー", theme.COLOR_ERROR
        elif snapshot.state is PresenceState.PAUSED:
            text = f"一時停止中（{snapshot.message}）" if snapshot.message else "一時停止中"
            color = theme.COLOR_PAUSED
        elif snapshot.state is PresenceState.DISABLED:
            text, color = "無効", theme.COLOR_PAUSED
        elif snapshot.person_present:
            text, color = "人物あり — 在席中", theme.COLOR_PRESENT
        else:
            remaining = int(snapshot.seconds_until_away + 0.999)
            text = f"人物なし — 離席まであと {remaining} 秒"
            color = theme.COLOR_COUNTDOWN

        bar_h = 30
        bar = QRect(0, self.height() - bar_h, self.width(), bar_h)
        painter.fillRect(bar, QColor(0, 0, 0, 170))

        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(bar, Qt.AlignCenter, text)
