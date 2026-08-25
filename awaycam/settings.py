"""settings.json の読み書きと検証。

- ファイルが無ければ既定値で自動生成する
- 壊れていた場合は既定値で起動し、壊れたファイルは .bak に退避する
- 値の範囲・整合性（離席判定時間 > チェック間隔 など）をここで矯正する
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .logging_setup import get_logger
from .paths import app_dir, resource_path

log = get_logger("settings")

APP_DIR = app_dir()
SETTINGS_PATH = APP_DIR / "settings.json"
DEFAULT_YOLO_MODEL_PATH = resource_path("models", "yolo26n.pt")
DEFAULT_POSE_MODEL_PATH = resource_path("models", "yolo26n-pose.pt")
DEFAULT_MEDIAPIPE_MODEL_PATH = resource_path("models", "efficientdet_lite0.tflite")
DETECTOR_BACKENDS = ["yolo26-pose", "yolo26", "mediapipe"]

# 選択肢（GUI のプルダウンと共有する）
# 設定画面のショートカット用。秒数自体は 1〜3600 の範囲で自由に指定できる。
AWAY_SECONDS_CHOICES = [3, 5, 10, 30, 60]

# チェック間隔の下限（ミリ秒）。
# GPU 推論は 1 回 8ms 程度なので処理は追いつくが、実際の周期はカメラの
# フレームレートで頭打ちになる（30fps なら 33ms より速くはならない）。
# これ以上短くしても判定は速くならず、GPU 使用率だけが上がる。
MIN_CHECK_INTERVAL_MS = 30
DISPLAY_MODES = ["fit", "fill", "center"]          # フィット / 埋める / 原寸中央
MONITOR_TARGETS = ["all", "primary", "index"]      # 全モニター / メイン / 指定
PAUSE_DURATION_CHOICES = [5, 15, 30, 60, 0]        # 分。0 = 再開するまで
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass
class Settings:
    """AwayCam の全設定。既定値はここが唯一の情報源。"""

    # --- 有効/無効 ---
    enabled: bool = True

    # --- カメラ ---
    camera_index: int = 0
    camera_name: str = ""            # 表示用。index が変わったときの照合にも使う
    check_interval_ms: int = 1000    # 在席中の推論間隔（ミリ秒）
    # 離席中だけ使う短い推論間隔。復帰を素早くするため。
    # 離席中は画像を表示しているだけで他に何もしていないので、
    # 短い間隔で回しても体感的な負荷にならない。
    away_check_interval_ms: int = 300

    # --- 人物検出 ---
    detection_confidence: float = 0.40   # この信頼度以上を「人物あり」とみなす
    # 人物矩形の高さがフレーム高さのこの割合「以下」なら遠いとして無視する。
    # 例: 0.60 なら、フレーム高さの 60% 以下でしか写っていない人物は離席扱い。
    # 背後を通る人や離れた場所にいる人を在席と誤認しないためのしきい値。
    # 0.0 で距離フィルタ無効。設定画面の「カメラ検出テスト」で実測して調整する。
    min_person_height_ratio: float = 0.55
    # 両肩の間隔がフレーム幅のこの割合「以下」なら遠いとみなす（姿勢検出時のみ）。
    # 矩形の高さより姿勢の 変動しにくい。0.0 で無効。
    min_shoulder_width_ratio: float = 0.30
    # 離席がこの秒数を超えたら、復帰の判定を厳しくする。
    # 反応距離ギリギリ（しきい値をわずかに超えただけ）の検出では在席に戻さない。
    long_away_seconds: int = 60
    # 長時間離席後の復帰に求める、距離しきい値からの上乗せ割合。
    # 例: 0.15 なら肩幅/高さがしきい値の 1.15 倍を超えて初めて復帰する。
    long_away_return_margin: float = 0.15
    # 検出方式:
    #   yolo26-pose … 姿勢推定つき（既定）。肩幅で距離を測るので誤離席が少ない
    #   yolo26      … 人物検出のみ
    #   mediapipe   … 軽量な代替
    detector_backend: str = "yolo26-pose"
    pose_model_path: str = str(DEFAULT_POSE_MODEL_PATH)
    yolo_model_path: str = str(DEFAULT_YOLO_MODEL_PATH)
    # YOLO26 の推論解像度。小さいほど速いが、遠くの人物を取りこぼしやすい。
    yolo_imgsz: int = 480
    mediapipe_model_path: str = str(DEFAULT_MEDIAPIPE_MODEL_PATH)

    # --- 在席/離席の判定 ---
    away_seconds: int = 10           # 未検出がこの秒数続いたら離席
    return_consecutive_hits: int = 3  # 連続検出この回数で復帰確定
    return_on_user_input: bool = True  # キーボード/マウス操作で即復帰

    # --- 離席時の画像表示 ---
    # 複数指定すると、一定間隔で順番に切り替えて表示し、最後まで行くと先頭へ戻る。
    image_paths: list[str] = field(default_factory=list)
    slideshow_interval_seconds: int = 10  # 切り替え間隔（1枚だけなら使われない）
    # 旧バージョンとの互換用。読み込み時に image_paths へ移す。
    image_path: str = ""
    display_mode: str = "fit"
    monitor_target: str = "all"
    monitor_index: int = 0
    background_color: str = "#000000"

    # --- 離席時の音声 ---
    # 離席中はシステムの出力音声をミュートし、復帰したら元に戻す。
    # 自分がミュートしたときだけ解除するので、元から消音していた場合は触らない。
    mute_audio_on_away: bool = True

    # --- 解除操作 ---
    allow_escape_to_dismiss: bool = True

    # --- 起動 ---
    start_with_windows: bool = False
    start_minimized: bool = False

    # --- 一時停止 ---
    release_camera_while_paused: bool = True
    # 全画面アプリ（ゲーム・動画・プレゼン）が前面にある間は自動で一時停止する。
    # 排他フルスクリーン上では最前面表示が効かず、また動きが少ないため
    # 離席と誤判定されやすいので、そもそも判定を止めてしまう。
    pause_on_fullscreen: bool = True

    # --- ホットキー（Win32 形式の文字列。空文字で無効） ---
    hotkey_toggle_enabled: str = "Ctrl+Alt+A"
    hotkey_pause: str = "Ctrl+Alt+P"
    hotkey_show_overlay: str = "Ctrl+Alt+S"
    hotkey_dismiss_overlay: str = "Ctrl+Alt+D"

    # --- 外観 ---
    theme: str = "system"            # system / light / dark

    def validate(self) -> "Settings":
        """値を安全な範囲に矯正する。不正値でも例外を投げず既定値へ寄せる。"""
        # 旧形式（image_path 単体）から新形式（image_paths）へ移行する
        if not isinstance(self.image_paths, list):
            self.image_paths = []
        self.image_paths = [str(p) for p in self.image_paths if str(p).strip()]
        if self.image_path and self.image_path not in self.image_paths:
            self.image_paths.insert(0, self.image_path)
        self.image_path = ""  # 移行済み

        self.slideshow_interval_seconds = _clamp(
            int(self.slideshow_interval_seconds), 1, 3600
        )

        self.check_interval_ms = _clamp(
            int(self.check_interval_ms), MIN_CHECK_INTERVAL_MS, 5000
        )
        self.away_check_interval_ms = _clamp(
            int(self.away_check_interval_ms), MIN_CHECK_INTERVAL_MS, 5000
        )
        # 離席中の間隔が在席中より長いと復帰が遅くなるだけなので、上限を揃える
        self.away_check_interval_ms = min(
            self.away_check_interval_ms, self.check_interval_ms
        )
        self.detection_confidence = _clampf(float(self.detection_confidence), 0.05, 0.95)
        self.long_away_seconds = max(0, int(self.long_away_seconds))
        self.long_away_return_margin = _clampf(float(self.long_away_return_margin), 0.0, 2.0)
        self.min_person_height_ratio = _clampf(float(self.min_person_height_ratio), 0.0, 0.95)
        self.min_shoulder_width_ratio = _clampf(float(self.min_shoulder_width_ratio), 0.0, 0.95)
        self.return_consecutive_hits = _clamp(int(self.return_consecutive_hits), 1, 10)
        self.camera_index = max(0, int(self.camera_index))
        self.monitor_index = max(0, int(self.monitor_index))
        self.away_seconds = _clamp(int(self.away_seconds), 1, 3600)

        if self.detector_backend not in DETECTOR_BACKENDS:
            log.warning("未知の検出方式 %r のため yolo26-pose に戻します", self.detector_backend)
            self.detector_backend = "yolo26-pose"
        # YOLO の推論解像度は 32 の倍数である必要がある
        self.yolo_imgsz = _clamp(int(self.yolo_imgsz), 320, 1280) // 32 * 32

        if self.display_mode not in DISPLAY_MODES:
            self.display_mode = "fit"
        if self.monitor_target not in MONITOR_TARGETS:
            self.monitor_target = "all"
        if self.theme not in ("system", "light", "dark"):
            self.theme = "system"

        # 離席判定時間は必ずチェック間隔より長くする（同値・逆転を防ぐ）
        min_away = max(1, int(self.check_interval_ms / 1000) + 1)
        if self.away_seconds < min_away:
            log.warning(
                "離席判定時間 %ds はチェック間隔 %dms より短いため %ds に補正しました",
                self.away_seconds, self.check_interval_ms, min_away,
            )
            self.away_seconds = min_away
        return self

    # --- 永続化 ---

    def save(self, path: Path = SETTINGS_PATH) -> None:
        self.validate()
        try:
            path.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
            )
            log.info("設定を保存しました: %s", path)
        except OSError as exc:
            log.error("設定の保存に失敗しました: %s", exc)

    @classmethod
    def load(cls, path: Path = SETTINGS_PATH) -> "Settings":
        if not path.exists():
            log.info("settings.json が無いため既定値で作成します")
            settings = cls()
            settings.save(path)
            return settings

        try:
            raw: Any = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("トップレベルがオブジェクトではありません")
        except (OSError, ValueError) as exc:
            log.error("settings.json を読めません (%s)。既定値で起動します", exc)
            _backup_broken_file(path)
            settings = cls()
            settings.save(path)
            return settings

        # 未知のキーは無視し、欠けたキーは既定値で補う
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in raw.items() if k in known}
        try:
            settings = cls(**kwargs)
        except TypeError as exc:
            log.error("設定値の型が不正です (%s)。既定値で起動します", exc)
            settings = cls()
        return settings.validate()


def _backup_broken_file(path: Path) -> None:
    try:
        shutil.copy2(path, path.with_suffix(".json.bak"))
        log.info("壊れた設定を %s に退避しました", path.with_suffix(".json.bak"))
    except OSError:
        pass


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _clampf(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
