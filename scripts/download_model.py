"""人物検出モデルをダウンロードする。初回のみ実行すればよい。

  yolo26-pose : Ultralytics YOLO26 nano 姿勢推定つき (既定)
  yolo26      : Ultralytics YOLO26 nano
  mediapipe: MediaPipe Tasks 用 EfficientDet-Lite0

    python scripts/download_model.py            # 両方
    python scripts/download_model.py yolo26     # YOLO26 だけ
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"  # 開発時のみ利用

MODELS = {
    "mediapipe": (
        "efficientdet_lite0.tflite",
        "https://storage.googleapis.com/mediapipe-models/object_detector/"
        "efficientdet_lite0/int8/1/efficientdet_lite0.tflite",
    ),
    "yolo26": (
        "yolo26n.pt",
        "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt",
    ),
    "yolo26-pose": (
        "yolo26n-pose.pt",
        "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n-pose.pt",
    ),
}


def download(name: str, force: bool = False) -> Path:
    filename, url = MODELS[name]
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    path = MODEL_DIR / filename
    if path.exists() and not force:
        print(f"[{name}] 既に存在します: {path}")
        return path
    print(f"[{name}] ダウンロード中: {url}")
    urllib.request.urlretrieve(url, path)
    print(f"[{name}] 保存しました: {path} ({path.stat().st_size:,} bytes)")
    return path


if __name__ == "__main__":
    force = "--force" in sys.argv
    wanted = [a for a in sys.argv[1:] if a in MODELS] or list(MODELS)
    for name in wanted:
        download(name, force)
