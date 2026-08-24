"""ファイルの置き場所を一元管理する。

exe 化（PyInstaller）すると __file__ は一時展開先を指すため、
settings.json やログを __file__ 基準で置くと書き込めなかったり、
起動のたびに消えたりする。凍結状態かどうかで置き場所を切り替える。

  通常実行 … リポジトリのルート
  exe 実行 … exe と同じフォルダ
"""
from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """PyInstaller などで exe 化された状態か。"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """設定・ログ・モデルを置く基準フォルダ（読み書きする場所）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_dir() -> Path:
    """同梱された読み取り専用リソースの場所。

    PyInstaller の onefile では一時展開先 (_MEIPASS) になる。
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", app_dir()))
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """同梱リソースを探す。exe と同じフォルダ側にあればそちらを優先する。

    利用者がモデルを差し替えられるよう、書き込み可能な側を先に見る。
    """
    external = app_dir().joinpath(*parts)
    if external.exists():
        return external
    return bundle_dir().joinpath(*parts)


def executable_command() -> list[str]:
    """自分自身を起動し直すためのコマンド。自動起動の登録に使う。"""
    if is_frozen():
        return [str(Path(sys.executable).resolve())]
    # 通常実行時はコンソール窓の出ない pythonw を優先する
    current = Path(sys.executable)
    pythonw = current.with_name("pythonw.exe")
    launcher = pythonw if pythonw.exists() else current
    return [str(launcher), str(app_dir() / "run.py")]
