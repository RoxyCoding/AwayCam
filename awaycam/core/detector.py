"""人物検出のファクトリ。

呼び出し側はこのモジュールだけを見ればよい。実際の検出方式は
設定 (detector_backend) で切り替える。

  yolo26    : Ultralytics YOLO26 nano（既定。精度が高い）
  mediapipe : MediaPipe EfficientDet-Lite0（軽量な代替）
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..logging_setup import get_logger
from .detection_types import (
    PERSON_CATEGORY,
    BasePersonDetector,
    DetectionResult,
    PersonBox,
)

if TYPE_CHECKING:
    from ..settings import Settings

log = get_logger("detector")

BACKEND_POSE = "yolo26-pose"
BACKEND_YOLO26 = "yolo26"
BACKEND_MEDIAPIPE = "mediapipe"
BACKENDS = (BACKEND_POSE, BACKEND_YOLO26, BACKEND_MEDIAPIPE)

__all__ = [
    "BACKENDS",
    "BACKEND_MEDIAPIPE",
    "BACKEND_POSE",
    "BACKEND_YOLO26",
    "BasePersonDetector",
    "DetectionResult",
    "PERSON_CATEGORY",
    "PersonBox",
    "create_detector",
]


def create_detector(settings: "Settings") -> BasePersonDetector:
    """設定に従って検出器を作る（この時点ではまだ load() しない）。"""
    backend = settings.detector_backend
    if backend == BACKEND_MEDIAPIPE:
        from .detector_mediapipe import MediaPipePersonDetector

        return MediaPipePersonDetector(
            settings.mediapipe_model_path,
            settings.detection_confidence,
            settings.min_person_height_ratio,
        )

    if backend == BACKEND_YOLO26:
        from .detector_yolo import YoloPersonDetector

        return YoloPersonDetector(
            settings.yolo_model_path,
            settings.detection_confidence,
            settings.min_person_height_ratio,
            settings.yolo_imgsz,
        )

    if backend != BACKEND_POSE:
        log.warning("未知の検出方式 %r のため YOLO26-pose を使います", backend)

    from .detector_pose import PosePersonDetector

    return PosePersonDetector(
        settings.pose_model_path,
        settings.detection_confidence,
        settings.min_person_height_ratio,
        settings.min_shoulder_width_ratio,
        settings.yolo_imgsz,
    )


def model_path_for(settings: "Settings") -> str:
    """現在の検出方式が使うモデルファイルのパス。"""
    if settings.detector_backend == BACKEND_MEDIAPIPE:
        return settings.mediapipe_model_path
    if settings.detector_backend == BACKEND_YOLO26:
        return settings.yolo_model_path
    return settings.pose_model_path
