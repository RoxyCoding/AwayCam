"""アプリ全体のログ設定。

映像やスクリーンショットは一切記録しない。記録するのは状態遷移とエラーのみ。
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _app_dir() -> Path:
    """exe 化されている場合は exe と同じフォルダにログを置く。

    paths モジュールと同じ判定だが、ログは最初に初期化されるため
    循環 import を避けてここに小さく持つ。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


LOG_DIR = _app_dir() / "logs"
LOG_PATH = LOG_DIR / "awaycam.log"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("awaycam")
    if root.handlers:  # 二重初期化を防ぐ
        return root
    root.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    # ログは 1MB × 3世代まで
    file_handler = RotatingFileHandler(
        LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"awaycam.{name}")
