"""距離のしきい値（min_person_height_ratio）を実測して決めるツール。

「PCの前に座っている状態」と「少し離れた状態」をそれぞれ測り、
その中間を推奨しきい値として提示する。settings.json への保存も行える。

    python scripts/calibrate_distance.py

AwayCam 本体が起動しているとカメラを取り合うため、先に終了しておくこと。
"""
from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from awaycam.core.camera import Camera
from awaycam.core.detection_types import BasePersonDetector
from awaycam.core.detector import create_detector
from awaycam.logging_setup import setup_logging
from awaycam.settings import Settings

MEASURE_SECONDS = 6.0
COUNTDOWN_SECONDS = 4

# 計測中は遠くの人も拾いたいので、距離フィルタは無効・信頼度は低めにする
MEASURE_CONFIDENCE = 0.25


def countdown(message: str) -> None:
    print(f"\n{message}")
    for remaining in range(COUNTDOWN_SECONDS, 0, -1):
        print(f"  計測開始まで {remaining} …", end="\r", flush=True)
        time.sleep(1)
    print("  計測中… " + " " * 20)


def measure(camera: Camera, detector: BasePersonDetector, label: str) -> list[float]:
    """一定時間だけ人物矩形の高さ比を集める。"""
    ratios: list[float] = []
    misses = 0
    deadline = time.monotonic() + MEASURE_SECONDS
    while time.monotonic() < deadline:
        frame = camera.read()
        if frame is None:
            misses += 1
            time.sleep(0.1)
            continue
        result = detector.detect(frame, int(time.monotonic() * 1000))
        # 距離フィルタは無効にしてあるので、検出は全て boxes に入る
        if result.boxes:
            biggest = max(result.boxes, key=lambda b: b.height_ratio)
            ratios.append(biggest.height_ratio)
            print(f"  高さ比 {biggest.height_ratio:.2f}  (信頼度 {biggest.score:.2f})", end="\r")
        else:
            print("  検出なし" + " " * 24, end="\r")
        time.sleep(0.15)

    print(" " * 50, end="\r")
    if misses:
        print(f"  ※ フレーム取得に {misses} 回失敗しました")
    if not ratios:
        print(f"  [{label}] 人物を検出できませんでした")
    else:
        print(
            f"  [{label}] 検出 {len(ratios)} 回  "
            f"最小 {min(ratios):.2f} / 中央 {sorted(ratios)[len(ratios)//2]:.2f} / "
            f"最大 {max(ratios):.2f}"
        )
    return ratios


def main() -> int:
    setup_logging()
    settings = Settings.load()

    print("=" * 60)
    print("AwayCam 距離しきい値キャリブレーション")
    print("=" * 60)
    print(f"使用カメラ: {settings.camera_index}")

    # 計測中は遠くの人も拾いたいので、信頼度を下げ距離フィルタを無効にする
    measure_settings = replace(
        settings, detection_confidence=MEASURE_CONFIDENCE, min_person_height_ratio=0.0
    )
    detector = create_detector(measure_settings)
    print(f"検出方式: {detector.backend_name}")
    if not detector.load():
        print(f"\nエラー: {detector.last_error}")
        return 1

    camera = Camera(index=settings.camera_index)
    if not camera.open():
        print(f"\nエラー: {camera.last_error}")
        print("AwayCam 本体が起動している場合は、先に終了してください。")
        return 1

    try:
        countdown("【1/2】いつもPCを使う位置に座ってください。")
        near = measure(camera, detector, "着席時")

        countdown("【2/2】在席とみなしたくない距離まで離れてください（カメラには写ったままで）。")
        far = measure(camera, detector, "離れた時")
    finally:
        camera.release()
        detector.close()

    print("\n" + "=" * 60)
    if not near:
        print("着席時に人物を検出できませんでした。")
        print("カメラの向き、明るさ、または検出信頼度の設定を確認してください。")
        return 1

    near_min = min(near)
    if not far:
        # 離れると検出そのものが消えるカメラ配置なら、距離フィルタは軽めでよい
        recommended = round(max(0.0, near_min * 0.7), 2)
        print("離れた位置では人物を検出しませんでした（フィルタなしでも誤検出しにくい配置です）。")
    else:
        far_max = max(far)
        if far_max >= near_min:
            print("警告: 着席時と離れた時の大きさが重なっています。")
            print(f"  着席時の最小 {near_min:.2f} <= 離れた時の最大 {far_max:.2f}")
            print("  この距離差では大きさだけで区別しきれません。")
            print("  カメラをもう少し手前に向ける、または離れる距離を大きくして再計測してください。")
            recommended = round((near_min + far_max) / 2, 2)
        else:
            # 両者の中間を取る。着席側に余裕を持たせるため少し低めに寄せる
            recommended = round(far_max + (near_min - far_max) * 0.4, 2)

    print(f"\n推奨しきい値 (min_person_height_ratio): {recommended:.2f}")
    print(f"現在の設定値                            : {settings.min_person_height_ratio:.2f}")

    answer = input("\nこの値を settings.json に保存しますか？ [y/N]: ").strip().lower()
    if answer == "y":
        settings.min_person_height_ratio = recommended
        settings.save()
        print("保存しました。AwayCam を再起動すると反映されます。")
    else:
        print("保存しませんでした。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
