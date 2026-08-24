"""Windows 11 に馴染む配色とスタイルシート。

ダーク / ライト両対応。theme="system" のときは OS の設定に追従する。
"""
from __future__ import annotations

from PySide6.QtGui import QGuiApplication, QPalette

# 状態表示に使うアクセント色
COLOR_PRESENT = "#2E9E5B"   # 在席中（緑）
COLOR_COUNTDOWN = "#D98A00"  # 離席まであと○秒（橙）
COLOR_AWAY = "#0F6CBD"      # 離席中（青 / Windows 11 アクセント）
COLOR_PAUSED = "#8A8A8A"    # 一時停止中（灰）
COLOR_ERROR = "#C4314B"     # カメラエラー（赤）


def is_dark_mode(preference: str = "system") -> bool:
    """実際にダークテーマで描画すべきかを返す。"""
    if preference == "dark":
        return True
    if preference == "light":
        return False
    # system: OS のウィンドウ背景色の明度で判定する
    palette = QGuiApplication.palette()
    return palette.color(QPalette.Window).lightness() < 128


def build_stylesheet(dark: bool) -> str:
    """アプリ全体のスタイルシートを組み立てる。余白を多めに取る。"""
    if dark:
        bg = "#202020"
        surface = "#2B2B2B"
        surface_hover = "#333333"
        border = "#3D3D3D"
        text = "#F3F3F3"
        text_muted = "#A0A0A0"
        accent = "#4CC2FF"
        accent_text = "#00243D"
    else:
        bg = "#F3F3F3"
        surface = "#FFFFFF"
        surface_hover = "#F5F5F5"
        border = "#E0E0E0"
        text = "#1B1B1B"
        text_muted = "#5D5D5D"
        accent = "#0F6CBD"
        accent_text = "#FFFFFF"

    return f"""
    QWidget {{
        background-color: {bg};
        color: {text};
        font-family: "Segoe UI Variable", "Segoe UI", "Yu Gothic UI", sans-serif;
        font-size: 14px;
    }}
    /* ラベルとチェックボックスは親の地色を透かす（カードの上で浮かないように） */
    QLabel, QCheckBox, QRadioButton {{ background-color: transparent; }}
    QLabel[role="muted"] {{ color: {text_muted}; }}
    QLabel[role="heading"] {{ font-size: 20px; font-weight: 600; }}

    /* カード風のパネル */
    QFrame[role="card"] {{
        background-color: {surface};
        border: 1px solid {border};
        border-radius: 8px;
    }}

    QPushButton {{
        background-color: {surface};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 8px 18px;
        min-height: 20px;
    }}
    QPushButton:hover {{ background-color: {surface_hover}; }}
    QPushButton:disabled {{ color: {text_muted}; }}
    QPushButton[role="accent"] {{
        background-color: {accent};
        color: {accent_text};
        border: 1px solid {accent};
        font-weight: 600;
    }}

    QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
        background-color: {surface};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 6px 10px;
        min-height: 20px;
    }}
    /* drop-down / down-arrow は上書きしない。
       上書きするとスタイルシート側の簡易描画に切り替わり、Windows 11 標準の
       「⌄」矢印が消えてテキスト欄と見分けがつかなくなるため。 */
    QComboBox:disabled {{ color: {text_muted}; }}

    QGroupBox {{
        border: 1px solid {border};
        border-radius: 8px;
        margin-top: 14px;
        padding: 14px;
        background-color: {surface};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        font-weight: 600;
    }}

    QTabWidget::pane {{ border: 1px solid {border}; border-radius: 8px; top: -1px; }}
    QTabBar::tab {{
        background: transparent;
        padding: 9px 18px;
        margin-right: 4px;
        border-radius: 6px;
    }}
    QTabBar::tab:selected {{ background-color: {surface}; font-weight: 600; }}

    QSlider::groove:horizontal {{
        height: 4px; background: {border}; border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {accent}; width: 16px; height: 16px;
        margin: -6px 0; border-radius: 8px;
    }}
    """


def apply_theme(app, preference: str = "system") -> bool:
    """アプリにテーマを適用し、ダークかどうかを返す。"""
    dark = is_dark_mode(preference)
    app.setStyleSheet(build_stylesheet(dark))
    return dark
