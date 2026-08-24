"""YOLO26 による人物検出（Ultralytics）。

COCO の class 0 = person だけを推論対象にする。

顔検出を使わない理由:
  横を向いた・うつむいた・後ろ向きの状態で顔は検出されないため、
  在席しているのに離席と誤判定されてしまう。person 検出は上半身の
  シルエットで反応するので、姿勢に強い。

常時稼働のため、推論解像度 (imgsz) を落として CPU 負荷を抑えられるようにしてある。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import numpy as np

from ..logging_setup import get_logger
from .detection_types import BasePersonDetector, DetectionResult, PersonBox

log = get_logger("detector_yolo")

PERSON_CLASS_ID = 0  # COCO の person


class YoloPersonDetector(BasePersonDetector):
    """Ultralytics YOLO26 を使う検出器。"""

    def __init__(
        self,
        model_path: str | Path,
        confidence: float = 0.40,
        min_height_ratio: float = 0.0,
        imgsz: int = 480,
    ) -> None:
        super().__init__(model_path, confidence, min_height_ratio)
        self.imgsz = imgsz
        self._model = None

    @property
    def backend_name(self) -> str:
        return "YOLO26"

    @property
    def is_ready(self) -> bool:
        return self._model is not None

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
            from ultralytics import YOLO

            model = YOLO(str(self.model_path))
            # 初回の推論は重いので、ダミー画像で先に済ませておく
            # （起動直後の1回だけ判定が遅れるのを防ぐ）
            warmup = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
            model.predict(
                warmup,
                classes=[PERSON_CLASS_ID],
                conf=self.confidence,
                imgsz=self.imgsz,
                verbose=False,
            )
            self._model = model
            self.last_error = ""
            log.info(
                "YOLO26 を読み込みました (%s, imgsz=%d, 信頼度しきい値 %.2f)",
                self.model_path.name, self.imgsz, self.confidence,
            )
            return True
        except ImportError as exc:
            self.last_error = (
                f"ultralytics を読み込めません: {exc}\n"
                "pip install ultralytics を実行してください。"
            )
            log.error(self.last_error)
            self._model = None
            return False
        except Exception as exc:
            self.last_error = f"YOLO26 の読み込みに失敗しました: {exc}"
            log.error(self.last_error)
            self._model = None
            return False

    def detect(
        self, frame_bgr: np.ndarray, timestamp_ms: Optional[int] = None
    ) -> DetectionResult:
        if self._model is None:
            return DetectionResult(False, [])

        started = time.perf_counter()
        try:
            # classes で person 以外を推論結果から除外する
            result = self._model.predict(
                frame_bgr,
                classes=[PERSON_CLASS_ID],
                conf=self.confidence,
                imgsz=self.imgsz,
                verbose=False,
            )[0]
        except Exception as exc:
            self.last_error = f"推論中にエラーが発生しました: {exc}"
            log.error(self.last_error)
            return DetectionResult(False, [])

        frame_height = max(1, frame_bgr.shape[0])
        candidates: list[PersonBox] = []
        boxes = result.boxes
        if boxes is not None:
            for index in range(len(boxes)):
                x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[index].tolist())
                height = max(0.0, y2 - y1)
                candidates.append(
                    PersonBox(
                        x=int(x1),
                        y=int(y1),
                        width=int(max(0.0, x2 - x1)),
                        height=int(height),
                        score=float(boxes.conf[index]),
                        height_ratio=height / frame_height,
                    )
                )

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return self._split_by_distance(candidates, elapsed_ms)

    def close(self) -> None:
        self._model = None
