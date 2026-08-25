"""人物検出まわりの共通の型と基底クラス。

検出方式（YOLO26 / MediaPipe）を差し替えても、呼び出し側は
このモジュールの型だけを見ればよいようにする。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

PERSON_CATEGORY = "person"


@dataclass
class PersonBox:
    """検出された人物の矩形（フレーム座標・ピクセル）。"""

    x: int
    y: int
    width: int
    height: int
    score: float
    height_ratio: float = 0.0    # 矩形の高さ / フレーム高さ。カメラからの近さの目安
    # 両肩の間隔 / フレーム幅。姿勢検出時のみ入る、より安定した近さの指標。
    # 矩形の高さは腕を上げる・のけぞる等で変動するが、肩幅はほとんど変わらない。
    shoulder_ratio: float = 0.0
    has_shoulders: bool = False  # 両肩を確度よく検出できたか


@dataclass
class DetectionResult:
    """1フレーム分の検出結果。"""

    person_present: bool
    boxes: list[PersonBox]                      # 在席とみなす、十分近い人物
    inference_ms: float = 0.0
    distant_boxes: list[PersonBox] = field(default_factory=list)  # 遠すぎて無視した人物

    @property
    def best_score(self) -> float:
        return max((b.score for b in self.boxes), default=0.0)

    @property
    def has_distant_person(self) -> bool:
        """人物は写っているが、いずれも遠すぎて在席とみなさなかった。"""
        return not self.boxes and bool(self.distant_boxes)


class BasePersonDetector(ABC):
    """人物検出器の共通インターフェース。

    どの実装も「読み込みに失敗しても例外を投げず、is_ready と last_error で
    状態を伝える」という約束を守る。検出できないことは、離席の根拠にしない。
    """

    def __init__(
        self,
        model_path: str | Path,
        confidence: float = 0.40,
        min_height_ratio: float = 0.0,
        min_shoulder_ratio: float = 0.0,
    ) -> None:
        self.model_path = Path(model_path)
        self.confidence = confidence
        # 人物矩形の高さがフレーム高さのこの割合「以下」なら遠すぎるとして無視する。
        # 背後を通りかかった人や、離れた場所にいる人を在席と誤認しないため。
        self.min_height_ratio = min_height_ratio
        # 肩幅による近さのしきい値（姿勢検出時のみ使う）。0 で無効。
        self.min_shoulder_ratio = min_shoulder_ratio
        self.last_error: str = ""

    # --- 実装が用意するもの ---

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """ログや設定画面に出す表示名。"""

    @abstractmethod
    def load(self) -> bool:
        """モデルを読み込む。成功なら True。"""

    @abstractmethod
    def close(self) -> None:
        """リソースを解放する。"""

    @property
    @abstractmethod
    def is_ready(self) -> bool:
        """検出できる状態か。"""

    @abstractmethod
    def detect(
        self, frame_bgr: np.ndarray, timestamp_ms: Optional[int] = None
    ) -> DetectionResult:
        """BGR フレームから人物を検出する。失敗時も例外を投げない。"""

    # --- 共通処理 ---

    def set_confidence(self, confidence: float) -> None:
        self.confidence = confidence

    def set_min_height_ratio(self, ratio: float) -> None:
        """近さのしきい値を変更する（モデルの再読み込みは不要）。"""
        self.min_height_ratio = ratio

    def set_min_shoulder_ratio(self, ratio: float) -> None:
        self.min_shoulder_ratio = ratio

    def _classify(self, box: PersonBox) -> bool:
        """在席とみなせる近さかどうか。

        肩幅と矩形の高さ、どちらかが基準を満たしていれば「近い」とみなす。
        両方を要求しないのは、横を向くと肩幅が縮み、腕を上げると矩形が伸びる、
        というように片方だけが崩れる場面があるため。遠くにいる人物は
        どちらの指標も小さくなるので、これで見逃すことはない。

        しきい値ちょうどは「離席側」に倒す（例: 0.60 なら 60% 以下は離席）。
        """
        if box.has_shoulders and self.min_shoulder_ratio > 0:
            if box.shoulder_ratio > self.min_shoulder_ratio:
                return True
        return box.height_ratio > self.min_height_ratio

    def is_clearly_near(self, box: PersonBox, margin: float) -> bool:
        """しきい値ギリギリではなく、明らかに近いと言えるか。

        長時間の離席から復帰させるときに使う。反応距離ちょうどの位置に
        人物が写っただけで在席に戻ると、席にいないのに画像が消えてしまう。
        """
        if margin <= 0:
            return self._classify(box)
        scale = 1.0 + margin
        if box.has_shoulders and self.min_shoulder_ratio > 0:
            if box.shoulder_ratio > self.min_shoulder_ratio * scale:
                return True
        return box.height_ratio > self.min_height_ratio * scale

    def _split_by_distance(
        self, candidates: list[PersonBox], elapsed_ms: float
    ) -> DetectionResult:
        near = [b for b in candidates if self._classify(b)]
        far = [b for b in candidates if not self._classify(b)]
        return DetectionResult(bool(near), near, elapsed_ms, far)
