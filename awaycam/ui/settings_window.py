"""設定画面。GUI だけで全ての設定が完結するようにする。

タブ構成:
  検出   … カメラ選択・プレビュー・検出方式・信頼度・距離しきい値
  離席判定 … 離席までの時間・復帰条件・チェック間隔
  表示   … 画像・表示モード・表示モニター
  起動   … 自動起動・最小化起動
  情報   … プライバシーと注意事項
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.camera import enumerate_cameras
from ..core.detector import BACKEND_MEDIAPIPE, BACKEND_POSE, BACKEND_YOLO26
from ..logging_setup import get_logger
from ..settings import (
    AWAY_SECONDS_CHOICES,
    SUPPORTED_IMAGE_SUFFIXES,
    Settings,
)
from .camera_preview import CameraPreview

log = get_logger("settings_window")

DISPLAY_MODE_LABELS = [
    ("fit", "アスペクト比を維持してフィット（既定）"),
    ("fill", "画面全体を埋める（はみ出しは切り抜き）"),
    ("center", "原寸を中央に表示"),
]
MONITOR_TARGET_LABELS = [
    ("all", "全モニター"),
    ("primary", "メインのみ"),
    ("index", "指定モニターのみ"),
]
DETECTOR_LABELS = [
    (BACKEND_POSE, "YOLO26-pose（姿勢推定つき・既定）"),
    (BACKEND_YOLO26, "YOLO26（人物検出のみ）"),
    (BACKEND_MEDIAPIPE, "MediaPipe（軽量）"),
]


class SettingsWindow(QDialog):
    """設定ダイアログ。適用すると即座にエンジンへ反映される。"""

    def __init__(
        self,
        settings: Settings,
        on_apply: Callable[[Settings], None],
        on_test_away: Callable[[], None],
        on_test_return: Callable[[], None],
        on_detection_test: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._settings = replace(settings)  # 編集用の複製（キャンセルで捨てられる）
        self._on_apply = on_apply
        self._on_detection_test = on_detection_test

        self.setWindowTitle("AwayCam の設定")
        self.setMinimumSize(760, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(18)

        tabs = QTabWidget()
        tabs.addTab(self._build_detection_tab(), "検出")
        tabs.addTab(self._build_presence_tab(), "離席判定")
        tabs.addTab(self._build_display_tab(), "表示")
        tabs.addTab(self._build_startup_tab(), "起動")
        tabs.addTab(self._build_about_tab(), "情報")
        root.addWidget(tabs, stretch=1)

        # --- 手動テスト ---
        test_row = QHBoxLayout()
        test_row.setSpacing(10)
        for label, handler in (
            ("離席状態をテスト", on_test_away),
            ("復帰", on_test_return),
            ("カメラ検出テスト", self._run_detection_test),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            test_row.addWidget(button)
        test_row.addStretch(1)
        root.addLayout(test_row)

        # --- 決定ボタン ---
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        apply_button = QPushButton("保存して閉じる")
        apply_button.setProperty("role", "accent")
        apply_button.clicked.connect(self._apply_and_close)
        buttons.addWidget(cancel)
        buttons.addWidget(apply_button)
        root.addLayout(buttons)

        self._load_into_widgets()

    # ------------------------------------------------------------------
    # 検出タブ
    # ------------------------------------------------------------------

    def _build_detection_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        self.preview = CameraPreview()
        layout.addWidget(self.preview, stretch=1)

        box = QGroupBox("カメラと検出")
        form = QFormLayout(box)
        form.setSpacing(12)

        camera_row = QHBoxLayout()
        self.camera_combo = QComboBox()
        refresh = QPushButton("再検出")
        refresh.clicked.connect(self._reload_cameras)
        camera_row.addWidget(self.camera_combo, stretch=1)
        camera_row.addWidget(refresh)
        form.addRow("使用するWebカメラ", camera_row)

        self.detector_combo = QComboBox()
        for _value, label in DETECTOR_LABELS:
            self.detector_combo.addItem(label)
        form.addRow("検出方式", self.detector_combo)

        # 検出信頼度
        self.confidence_slider = QSlider(Qt.Horizontal)
        self.confidence_slider.setRange(5, 95)
        self.confidence_value = QLabel()
        self.confidence_slider.valueChanged.connect(
            lambda v: self.confidence_value.setText(f"{v / 100:.2f}")
        )
        conf_row = QHBoxLayout()
        conf_row.addWidget(self.confidence_slider, stretch=1)
        conf_row.addWidget(self.confidence_value)
        form.addRow("検出信頼度（低いほど暗い部屋に強い）", conf_row)

        # 距離しきい値
        self.distance_slider = QSlider(Qt.Horizontal)
        self.distance_slider.setRange(0, 95)
        self.distance_value = QLabel()
        self.distance_slider.valueChanged.connect(self._on_distance_changed)
        dist_row = QHBoxLayout()
        dist_row.addWidget(self.distance_slider, stretch=1)
        dist_row.addWidget(self.distance_value)
        form.addRow("この大きさ以下は離席とみなす", dist_row)

        hint = QLabel(
            "画面に占める人物の高さです。プレビューの枠に出る「高さ」を見ながら、"
            "座っているときの値より少し小さい値に設定してください。0% で無効。"
        )
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        form.addRow("", hint)

        # 肩幅のしきい値（姿勢推定を使うときのみ有効）
        self.shoulder_slider = QSlider(Qt.Horizontal)
        self.shoulder_slider.setRange(0, 95)
        self.shoulder_value = QLabel()
        self.shoulder_slider.valueChanged.connect(
            lambda v: self.shoulder_value.setText("無効" if v == 0 else f"{v}%")
        )
        shoulder_row = QHBoxLayout()
        shoulder_row.addWidget(self.shoulder_slider, stretch=1)
        shoulder_row.addWidget(self.shoulder_value)
        self.shoulder_row_label = QLabel("この肩幅以下は離席とみなす")
        form.addRow(self.shoulder_row_label, shoulder_row)

        self.shoulder_hint = QLabel(
            "画面幅に占める両肩の間隔です。腕を上げたり のけぞったりしても値が変わらないため、"
            "高さより安定して距離を判定できます。高さと肩幅の"
            "どちらかが基準を満たしていれば在席とみなします。"
        )
        self.shoulder_hint.setProperty("role", "muted")
        self.shoulder_hint.setWordWrap(True)
        form.addRow("", self.shoulder_hint)

        self.detector_combo.currentIndexChanged.connect(self._update_shoulder_state)

        layout.addWidget(box)
        return page

    def _on_distance_changed(self, value: int) -> None:
        self.distance_value.setText("無効" if value == 0 else f"{value}%")

    def _update_shoulder_state(self) -> None:
        """肩幅の設定は姿勢推定を選んでいるときだけ意味を持つ。"""
        uses_pose = DETECTOR_LABELS[self.detector_combo.currentIndex()][0] == BACKEND_POSE
        for widget in (self.shoulder_slider, self.shoulder_value,
                       self.shoulder_row_label, self.shoulder_hint):
            widget.setEnabled(uses_pose)

    # ------------------------------------------------------------------
    # 離席判定タブ
    # ------------------------------------------------------------------

    def _build_presence_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        away_box = QGroupBox("離席の判定")
        away_form = QFormLayout(away_box)
        away_form.setSpacing(12)

        self.away_combo = QComboBox()
        for seconds in AWAY_SECONDS_CHOICES:
            self.away_combo.addItem(f"{seconds} 秒", seconds)
        away_form.addRow("離席判定までの時間", self.away_combo)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(200, 5000)
        self.interval_spin.setSingleStep(100)
        self.interval_spin.setSuffix(" ms")
        self.interval_spin.valueChanged.connect(self._validate_timing)
        away_form.addRow("カメラチェック間隔", self.interval_spin)

        self.timing_warning = QLabel()
        self.timing_warning.setWordWrap(True)
        self.timing_warning.setStyleSheet("color: #C4314B;")
        away_form.addRow("", self.timing_warning)

        layout.addWidget(away_box)

        return_box = QGroupBox("復帰の判定")
        return_form = QFormLayout(return_box)
        return_form.setSpacing(12)

        self.hits_spin = QSpinBox()
        self.hits_spin.setRange(1, 10)
        self.hits_spin.setSuffix(" 回")
        return_form.addRow("復帰に必要な連続検出回数", self.hits_spin)

        self.away_interval_spin = QSpinBox()
        self.away_interval_spin.setRange(100, 5000)
        self.away_interval_spin.setSingleStep(100)
        self.away_interval_spin.setSuffix(" ms")
        return_form.addRow("離席中のチェック間隔（短いほど復帰が速い）", self.away_interval_spin)

        self.input_check = QCheckBox(
            "キーボード / マウス操作があったら、カメラ判定を待たず即座に復帰する"
        )
        return_form.addRow("", self.input_check)

        hint = QLabel(
            "誤検知でうっかり離席になったときの救済手段です。無効にすることは推奨しません。"
        )
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        return_form.addRow("", hint)

        layout.addWidget(return_box)
        layout.addStretch(1)
        return page

    def _validate_timing(self) -> None:
        """離席判定時間がチェック間隔より長いことを確認して警告を出す。"""
        interval_s = self.interval_spin.value() / 1000.0
        away_s = self.away_combo.currentData()
        if away_s is not None and away_s <= interval_s:
            self.timing_warning.setText(
                f"離席判定時間（{away_s}秒）はカメラチェック間隔"
                f"（{interval_s:.1f}秒）より長くしてください。"
            )
        else:
            self.timing_warning.setText("")

    # ------------------------------------------------------------------
    # 表示タブ
    # ------------------------------------------------------------------

    def _build_display_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        image_box = QGroupBox("離席時に表示する画像")
        image_form = QFormLayout(image_box)
        image_form.setSpacing(12)

        # 複数の画像を順番に表示できるようにリストで持つ
        list_row = QHBoxLayout()
        self.image_list = QListWidget()
        self.image_list.setMinimumHeight(120)
        self.image_list.setSelectionMode(QListWidget.ExtendedSelection)
        list_row.addWidget(self.image_list, stretch=1)

        button_column = QVBoxLayout()
        button_column.setSpacing(6)
        for label, handler in (
            ("追加…", self._browse_images),
            ("削除", self._remove_selected_images),
            ("↑", lambda: self._move_selected_image(-1)),
            ("↓", lambda: self._move_selected_image(1)),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            button_column.addWidget(button)
        button_column.addStretch(1)
        list_row.addLayout(button_column)
        image_form.addRow("画像ファイル", list_row)

        self.image_status = QLabel()
        self.image_status.setProperty("role", "muted")
        self.image_status.setWordWrap(True)
        image_form.addRow("", self.image_status)

        self.slideshow_spin = QSpinBox()
        self.slideshow_spin.setRange(1, 3600)
        self.slideshow_spin.setSuffix(" 秒")
        image_form.addRow("切り替え間隔", self.slideshow_spin)

        slideshow_hint = QLabel(
            "2枚以上あるとこの間隔で順番に切り替わり、最後まで行くと先頭へ戻ります。"
            "1枚のときは切り替えを行いません。"
        )
        slideshow_hint.setProperty("role", "muted")
        slideshow_hint.setWordWrap(True)
        image_form.addRow("", slideshow_hint)

        self.display_mode_combo = QComboBox()
        for _value, label in DISPLAY_MODE_LABELS:
            self.display_mode_combo.addItem(label)
        image_form.addRow("表示モード", self.display_mode_combo)

        layout.addWidget(image_box)

        monitor_box = QGroupBox("表示先モニター")
        monitor_form = QFormLayout(monitor_box)
        monitor_form.setSpacing(12)

        self.monitor_target_combo = QComboBox()
        for _value, label in MONITOR_TARGET_LABELS:
            self.monitor_target_combo.addItem(label)
        self.monitor_target_combo.currentIndexChanged.connect(self._update_monitor_state)
        monitor_form.addRow("表示先", self.monitor_target_combo)

        self.monitor_index_combo = QComboBox()
        monitor_form.addRow("指定モニター", self.monitor_index_combo)

        self.escape_check = QCheckBox("Esc キーで離席画面をいつでも解除する")
        monitor_form.addRow("", self.escape_check)

        self.mute_check = QCheckBox("離席中はシステムの出力音声をミュートする")
        monitor_form.addRow("", self.mute_check)

        mute_hint = QLabel(
            "復帰すると元に戻します。離席する前から自分でミュートしていた場合は、"
            "復帰時に勝手に音を出さないようそのままにします。"
        )
        mute_hint.setProperty("role", "muted")
        mute_hint.setWordWrap(True)
        monitor_form.addRow("", mute_hint)

        layout.addWidget(monitor_box)
        layout.addStretch(1)
        return page

    def _update_monitor_state(self) -> None:
        is_index = self.monitor_target_combo.currentIndex() == 2
        self.monitor_index_combo.setEnabled(is_index)

    def _browse_images(self) -> None:
        patterns = " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_IMAGE_SUFFIXES))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "離席時に表示する画像を選択（複数可）", "", f"画像ファイル ({patterns})"
        )
        existing = self._image_paths()
        for path in paths:
            if path not in existing:  # 同じ画像を二重に足さない
                self.image_list.addItem(QListWidgetItem(path))
        self._refresh_image_status()

    def _remove_selected_images(self) -> None:
        for item in self.image_list.selectedItems():
            self.image_list.takeItem(self.image_list.row(item))
        self._refresh_image_status()

    def _move_selected_image(self, offset: int) -> None:
        """選択中の画像を1つ上/下へ動かして表示順を変える。"""
        row = self.image_list.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < self.image_list.count():
            return
        item = self.image_list.takeItem(row)
        self.image_list.insertItem(target, item)
        self.image_list.setCurrentRow(target)

    def _image_paths(self) -> list[str]:
        return [self.image_list.item(i).text() for i in range(self.image_list.count())]

    def _refresh_image_status(self) -> None:
        paths = self._image_paths()
        if not paths:
            self.image_status.setText("未設定の場合は「離席中」という文字だけを表示します。")
            return

        problems = []
        for text in paths:
            path = Path(text)
            if not path.exists():
                problems.append(f"見つかりません: {path.name}")
            elif path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
                problems.append(f"未対応の形式: {path.name}")

        if problems:
            self.image_status.setText("⚠ " + " / ".join(problems))
        elif len(paths) == 1:
            self.image_status.setText(f"OK — {Path(paths[0]).name}")
        else:
            self.image_status.setText(f"OK — {len(paths)} 枚を順番に表示します")

        self.slideshow_spin.setEnabled(len(paths) > 1)

    # ------------------------------------------------------------------
    # 起動タブ
    # ------------------------------------------------------------------

    def _build_startup_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        box = QGroupBox("起動と常駐")
        form = QVBoxLayout(box)
        form.setSpacing(12)

        self.enabled_check = QCheckBox("AwayCam を有効にする")
        self.autostart_check = QCheckBox("Windows 起動時に自動で開始する")
        self.minimized_check = QCheckBox("起動時は最小化する（タスクトレイに常駐）")
        self.release_camera_check = QCheckBox(
            "一時停止中はカメラを解放する（他のアプリがカメラを使えるようにする）"
        )
        self.fullscreen_check = QCheckBox(
            "全画面アプリ（ゲーム・動画・プレゼン）の使用中は自動で一時停止する"
        )
        for widget in (
            self.enabled_check,
            self.autostart_check,
            self.minimized_check,
            self.release_camera_check,
            self.fullscreen_check,
        ):
            form.addWidget(widget)

        fullscreen_hint = QLabel(
            "全画面のゲーム上では離席画像の最前面表示が効かず、また動きが少ないため"
            "離席と誤判定されやすくなります。全画面をやめると自動で再開します。"
        )
        fullscreen_hint.setProperty("role", "muted")
        fullscreen_hint.setWordWrap(True)
        form.addWidget(fullscreen_hint)

        hint = QLabel(
            "ウィンドウを閉じても終了せず、タスクトレイに常駐し続けます。"
            "完全に終了するにはトレイアイコンを右クリックして「終了」を選んでください。"
        )
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        form.addWidget(hint)

        layout.addWidget(box)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # 情報タブ
    # ------------------------------------------------------------------

    def _build_about_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        privacy = QGroupBox("プライバシー")
        privacy_layout = QVBoxLayout(privacy)
        privacy_text = QLabel(
            "カメラ映像はこのPC内でのみ処理され、保存されません。\n\n"
            "・映像の録画、静止画やスクリーンショットの保存は一切行いません\n"
            "・映像や検出結果を外部へ送信することは一切ありません\n"
            "・記録するのは状態の変化とエラー内容のログのみです"
        )
        privacy_text.setWordWrap(True)
        privacy_layout.addWidget(privacy_text)
        layout.addWidget(privacy)

        warning = QGroupBox("ご注意")
        warning_layout = QVBoxLayout(warning)
        warning_text = QLabel(
            "AwayCam は画面ロックではありません。セキュリティ機能ではないため、"
            "離席中の情報保護の目的には使用しないでください。\n\n"
            "表示される画像は通常のデスクトップアプリのウィンドウです。"
            "Esc キーで解除でき、他のアプリの操作を妨げるものではありません。"
            "重要な情報を守るには Windows の画面ロック（Win + L）を使用してください。\n\n"
            "また、排他フルスクリーンで動作するゲームの上では最前面表示が"
            "効かない場合があります。"
        )
        warning_text.setWordWrap(True)
        warning_layout.addWidget(warning_text)
        layout.addWidget(warning)

        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # 値の読み書き
    # ------------------------------------------------------------------

    def _reload_cameras(self) -> None:
        current = self.camera_combo.currentData()
        self.camera_combo.clear()
        devices = enumerate_cameras()
        if not devices:
            self.camera_combo.addItem("カメラが見つかりません", -1)
            return
        for device in devices:
            self.camera_combo.addItem(f"[{device.index}] {device.name}", device.index)
        index = self.camera_combo.findData(
            current if current is not None else self._settings.camera_index
        )
        self.camera_combo.setCurrentIndex(max(0, index))

    def _reload_monitors(self) -> None:
        self.monitor_index_combo.clear()
        for i, screen in enumerate(QGuiApplication.screens()):
            size = screen.geometry()
            self.monitor_index_combo.addItem(
                f"モニター {i + 1}: {size.width()}x{size.height()}", i
            )

    def _load_into_widgets(self) -> None:
        s = self._settings

        self._reload_cameras()
        self._reload_monitors()

        self.detector_combo.setCurrentIndex(
            next((i for i, (v, _) in enumerate(DETECTOR_LABELS) if v == s.detector_backend), 0)
        )
        self.confidence_slider.setValue(int(round(s.detection_confidence * 100)))
        self.confidence_value.setText(f"{s.detection_confidence:.2f}")
        self.distance_slider.setValue(int(round(s.min_person_height_ratio * 100)))
        self._on_distance_changed(self.distance_slider.value())
        self.shoulder_slider.setValue(int(round(s.min_shoulder_width_ratio * 100)))
        self.shoulder_value.setText(
            "無効" if self.shoulder_slider.value() == 0 else f"{self.shoulder_slider.value()}%"
        )
        self._update_shoulder_state()

        away_index = self.away_combo.findData(s.away_seconds)
        if away_index < 0:
            # 設定ファイルを手で編集した値も選べるようにしておく
            self.away_combo.addItem(f"{s.away_seconds} 秒", s.away_seconds)
            away_index = self.away_combo.count() - 1
        self.away_combo.setCurrentIndex(away_index)
        self.away_combo.currentIndexChanged.connect(self._validate_timing)

        self.interval_spin.setValue(s.check_interval_ms)
        self.away_interval_spin.setValue(s.away_check_interval_ms)
        self.hits_spin.setValue(s.return_consecutive_hits)
        self.input_check.setChecked(s.return_on_user_input)
        self._validate_timing()

        self.image_list.clear()
        for path in s.image_paths:
            self.image_list.addItem(QListWidgetItem(path))
        self.slideshow_spin.setValue(s.slideshow_interval_seconds)
        self._refresh_image_status()
        self.display_mode_combo.setCurrentIndex(
            next((i for i, (v, _) in enumerate(DISPLAY_MODE_LABELS) if v == s.display_mode), 0)
        )
        self.monitor_target_combo.setCurrentIndex(
            next((i for i, (v, _) in enumerate(MONITOR_TARGET_LABELS) if v == s.monitor_target), 0)
        )
        if 0 <= s.monitor_index < self.monitor_index_combo.count():
            self.monitor_index_combo.setCurrentIndex(s.monitor_index)
        self._update_monitor_state()
        self.escape_check.setChecked(s.allow_escape_to_dismiss)
        self.mute_check.setChecked(s.mute_audio_on_away)

        self.enabled_check.setChecked(s.enabled)
        self.autostart_check.setChecked(s.start_with_windows)
        self.minimized_check.setChecked(s.start_minimized)
        self.release_camera_check.setChecked(s.release_camera_while_paused)
        self.fullscreen_check.setChecked(s.pause_on_fullscreen)

    def _collect_from_widgets(self) -> Settings:
        s = replace(self._settings)

        camera_index = self.camera_combo.currentData()
        if camera_index is not None and camera_index >= 0:
            s.camera_index = camera_index
            s.camera_name = self.camera_combo.currentText()

        s.detector_backend = DETECTOR_LABELS[self.detector_combo.currentIndex()][0]
        s.detection_confidence = self.confidence_slider.value() / 100.0
        s.min_person_height_ratio = self.distance_slider.value() / 100.0
        s.min_shoulder_width_ratio = self.shoulder_slider.value() / 100.0

        s.away_seconds = int(self.away_combo.currentData())
        s.check_interval_ms = self.interval_spin.value()
        s.away_check_interval_ms = self.away_interval_spin.value()
        s.return_consecutive_hits = self.hits_spin.value()
        s.return_on_user_input = self.input_check.isChecked()

        s.image_paths = self._image_paths()
        s.slideshow_interval_seconds = self.slideshow_spin.value()
        s.display_mode = DISPLAY_MODE_LABELS[self.display_mode_combo.currentIndex()][0]
        s.monitor_target = MONITOR_TARGET_LABELS[self.monitor_target_combo.currentIndex()][0]
        s.monitor_index = max(0, self.monitor_index_combo.currentIndex())
        s.allow_escape_to_dismiss = self.escape_check.isChecked()
        s.mute_audio_on_away = self.mute_check.isChecked()

        s.enabled = self.enabled_check.isChecked()
        s.start_with_windows = self.autostart_check.isChecked()
        s.start_minimized = self.minimized_check.isChecked()
        s.release_camera_while_paused = self.release_camera_check.isChecked()
        s.pause_on_fullscreen = self.fullscreen_check.isChecked()
        return s.validate()

    # ------------------------------------------------------------------
    # エンジンからの更新（プレビュー）
    # ------------------------------------------------------------------

    def update_frame(self, frame, result) -> None:
        self.preview.update_frame(frame, result)

    def update_snapshot(self, snapshot) -> None:
        self.preview.update_snapshot(snapshot)

    def update_camera_error(self, message: str) -> None:
        if message:
            self.preview.show_message(message)

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------

    def _run_detection_test(self) -> None:
        self._on_detection_test()

    def _apply_and_close(self) -> None:
        new_settings = self._collect_from_widgets()

        # 補正が入った場合は黙って変えず、利用者に伝える
        if new_settings.away_seconds != int(self.away_combo.currentData()):
            QMessageBox.information(
                self,
                "設定を調整しました",
                f"離席判定時間はカメラチェック間隔より長い必要があるため、"
                f"{new_settings.away_seconds} 秒に調整しました。",
            )

        self._settings = new_settings
        self._on_apply(new_settings)
        self.accept()

    def result_settings(self) -> Settings:
        return self._settings
