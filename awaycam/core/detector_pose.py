"""YOLO26-pose による人物検出（姿勢推定つき）。

通常の人物検出に加えて COCO 17 関節を取得し、**両肩の間隔**を
カメラからの近さの指標に使う。

矩形の高さを使う方式との違い:
  矩形の高さは、腕を上げる・のけぞる・前かがみになる といった姿勢の変化で
  大きく揺れる。肩幅はカメラとの距離にほぼ比例し、姿勢が変わっても安定する。
  そのため、しきい値を厳しめに設定しても誤離席が起きにくい。

肩が見えない場合（横向き・肩が隠れている等）は矩形の高さで判定するので、
姿勢推定が外れても在席判定が壊れることはない。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import numpy as np

from ..logging_setup import get_logger
from .detection_types import BasePersonDetector, DetectionResult, PersonBox

log = get_logger("detector_pose")

PERSON_CLASS_ID = 0  # COCO の person

# COCO 17 キーポイントの並び
KP_LEFT_SHOULDER = 5
KP_RIGHT_SHOULDER = 6

# この確度以上なら「肩が見えている」とみなす
SHOULDER_CONFIDENCE = 0.5


class PosePersonDetector(BasePersonDetector):
    """Ultralytics YOLO26-pose を使う検出器。"""

    def __init__(
        self,
        model_path: str | Path,
        confidence: float = 0.40,
        min_height_ratio: float = 0.0,
        min_shoulder_ratio: float = 0.0,
        imgsz: int = 480,
    ) -> None:
        super().__init__(model_path, confidence, min_height_ratio, min_shoulder_ratio)
        self.imgsz = imgsz
        self._model = None

    @property
    def backend_name(self) -> str:
        return "YOLO26-pose"

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    def load(self) -> bool:
        self.close()
        if not self.model_path.exists():
            self.last_error = (
                f"姿勢検出モデルが見つかりません: {self.model_path}\n"
                "scripts/download_model.py を実行してください。"
            )
            log.error(self.last_error)
            return False

        try:
            from ultralytics import YOLO

            model = YOLO(str(self.model_path))
            # 初回推論は重いので、起動時にダミー画像で済ませておく
            warmup = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
            model.predict(warmup, conf=self.confidence, imgsz=self.imgsz, verbose=False)
            self._model = model
            self.last_error = ""
            log.info(
                "YOLO26-pose を読み込みました (%s, imgsz=%d, 信頼度しきい値 %.2f)",
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
            self.last_error = f"YOLO26-pose の読み込みに失敗しました: {exc}"
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
            # pose モデルは person 専用なので classes の指定は不要
            result = self._model.predict(
                frame_bgr, conf=self.confidence, imgsz=self.imgsz, verbose=False
            )[0]
        except Exception as exc:
            self.last_error = f"推論中にエラーが発生しました: {exc}"
            log.error(self.last_error)
            return DetectionResult(False, [])

        frame_h, frame_w = frame_bgr.shape[:2]
        frame_h = max(1, frame_h)
        frame_w = max(1, frame_w)

        candidates: list[PersonBox] = []
        boxes = result.boxes
        keypoints = result.keypoints
        if boxes is not None:
            for index in range(len(boxes)):
                x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[index].tolist())
                height = max(0.0, y2 - y1)
                shoulder_ratio, has_shoulders = self._shoulder_ratio(
                    keypoints, index, frame_w
                )
                candidates.append(
                    PersonBox(
                        x=int(x1),
                        y=int(y1),
                        width=int(max(0.0, x2 - x1)),
                        height=int(height),
                        score=float(boxes.conf[index]),
                        height_ratio=height / frame_h,
                        shoulder_ratio=shoulder_ratio,
                        has_shoulders=has_shoulders,
                    )
                )

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return self._split_by_distance(candidates, elapsed_ms)

    def _shoulder_ratio(self, keypoints, index: int, frame_w: int) -> tuple[float, bool]:
        """両肩の間隔をフレーム幅で正規化して返す。取れなければ (0.0, False)。"""
        if keypoints is None or keypoints.data is None:
            return 0.0, False
        try:
            person = keypoints.data[index]
            left_x, left_y, left_conf = (float(v) for v in person[KP_LEFT_SHOULDER])
            right_x, right_y, right_conf = (float(v) for v in person[KP_RIGHT_SHOULDER])
        except (IndexError, ValueError, TypeError):
            return 0.0, False

        if left_conf < SHOULDER_CONFIDENCE or right_conf < SHOULDER_CONFIDENCE:
            return 0.0, False

        distance = ((left_x - right_x) ** 2 + (left_y - right_y) ** 2) ** 0.5
        return distance / frame_w, True

    def close(self) -> None:
        self._model = None
