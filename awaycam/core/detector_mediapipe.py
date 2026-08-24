"""MediaPipe Tasks による人物検出（EfficientDet-Lite0）。

YOLO26 が使えない環境向けの軽量な代替。CPU 負荷は YOLO26 より小さい。
COCO の "person" クラスのみを採用する。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import numpy as np

from ..logging_setup import get_logger
from .detection_types import (
    PERSON_CATEGORY,
    BasePersonDetector,
    DetectionResult,
    PersonBox,
)

log = get_logger("detector_mediapipe")


class MediaPipePersonDetector(BasePersonDetector):
    """MediaPipe Tasks の ObjectDetector を使う検出器。"""

    def __init__(
        self,
        model_path: str | Path,
        confidence: float = 0.40,
        min_height_ratio: float = 0.0,
    ) -> None:
        super().__init__(model_path, confidence, min_height_ratio)
        self._detector = None
        self._mp = None
        self._timestamp_ms = 0  # VIDEO モードは単調増加のタイムスタンプが必須

    @property
    def backend_name(self) -> str:
        return "MediaPipe"

    @property
    def is_ready(self) -> bool:
        return self._detector is not None

    def load(self) -> bool:
        self.close()
        if not self.model_path.exists():
            self.last_error = (
                f"検出モデルが見つかりません: {self.model_path}\n"
                "scripts/download_model.py を実行してください。"
            )
            log.error(self.last_error)
            return False

        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision as mp_vision

            self._mp = mp
            options = mp_vision.ObjectDetectorOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(self.model_path)),
                running_mode=mp_vision.RunningMode.VIDEO,
                score_threshold=self.confidence,
                category_allowlist=[PERSON_CATEGORY],  # person 以外は結果から除外
                max_results=5,
            )
            self._detector = mp_vision.ObjectDetector.create_from_options(options)
            self.last_error = ""
            log.info(
                "MediaPipe を読み込みました (信頼度しきい値 %.2f)", self.confidence
            )
            return True
        except Exception as exc:
            self.last_error = f"MediaPipe の読み込みに失敗しました: {exc}"
            log.error(self.last_error)
            self._detector = None
            return False

    def set_confidence(self, confidence: float) -> None:
        """しきい値はモデル生成時に焼き込まれるため、変更には再読み込みが要る。"""
        if abs(confidence - self.confidence) < 1e-6:
            return
        self.confidence = confidence
        if self.is_ready:
            self.load()

    def detect(
        self, frame_bgr: np.ndarray, timestamp_ms: Optional[int] = None
    ) -> DetectionResult:
        if self._detector is None:
            return DetectionResult(False, [])

        started = time.perf_counter()
        try:
            rgb = frame_bgr[:, :, ::-1].copy()  # MediaPipe は RGB を要求する
            mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
            # タイムスタンプは必ず前回より大きい必要がある
            if timestamp_ms is None or timestamp_ms <= self._timestamp_ms:
                timestamp_ms = self._timestamp_ms + 1
            self._timestamp_ms = timestamp_ms
            raw = self._detector.detect_for_video(mp_image, timestamp_ms)
        except Exception as exc:
            self.last_error = f"推論中にエラーが発生しました: {exc}"
            log.error(self.last_error)
            return DetectionResult(False, [])

        frame_height = max(1, frame_bgr.shape[0])
        candidates: list[PersonBox] = []
        for detection in raw.detections:
            category = detection.categories[0] if detection.categories else None
            if category is None or category.category_name != PERSON_CATEGORY:
                continue
            if category.score < self.confidence:
                continue
            bbox = detection.bounding_box
            candidates.append(
                PersonBox(
                    x=int(bbox.origin_x),
                    y=int(bbox.origin_y),
                    width=int(bbox.width),
                    height=int(bbox.height),
                    score=float(category.score),
                    height_ratio=float(bbox.height) / frame_height,
                )
            )

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return self._split_by_distance(candidates, elapsed_ms)

    def close(self) -> None:
        if self._detector is not None:
            try:
                self._detector.close()
            except Exception:
                pass
            self._detector = None
