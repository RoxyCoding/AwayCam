"""Windows 起動時の自動実行（レジストリ HKCU\\...\\Run）。

管理者権限を必要としない HKEY_CURRENT_USER を使う。
コンソール窓が出ないよう、起動には pythonw.exe を優先して使う。
"""
from __future__ import annotations

import sys
import winreg
from pathlib import Path
from typing import Optional

from .logging_setup import get_logger
from .paths import executable_command

log = get_logger("autostart")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "AwayCam"

def build_command() -> str:
    """レジストリに登録するコマンド文字列を組み立てる。

    起動時は必ず最小化で立ち上げたいので --minimized を付ける。
    exe 化されている場合は exe を直接登録する。
    """
    parts = executable_command() + ["--minimized"]
    return " ".join(f'"{part}"' if not part.startswith("--") else part for part in parts)


def is_enabled() -> bool:
    """自動起動が登録されているか。"""
    return get_registered_command() is not None


def get_registered_command() -> Optional[str]:
    """登録済みのコマンドを返す。未登録なら None。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, APP_NAME)
            return str(value)
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.warning("自動起動の設定を読めませんでした: %s", exc)
        return None


def enable() -> bool:
    """自動起動を登録する（既に登録済みでもコマンドを最新に更新する）。"""
    command = build_command()
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
        log.info("自動起動を有効にしました: %s", command)
        return True
    except OSError as exc:
        log.error("自動起動を登録できませんでした: %s", exc)
        return False


def disable() -> bool:
    """自動起動の登録を解除する。未登録でも成功扱い。"""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, APP_NAME)
        log.info("自動起動を無効にしました")
        return True
    except FileNotFoundError:
        return True  # もともと登録されていない
    except OSError as exc:
        log.error("自動起動を解除できませんでした: %s", exc)
        return False


def apply(enabled: bool) -> bool:
    """設定値に合わせて登録状態をそろえる。"""
    if enabled:
        return enable()
    return disable()


def sync_if_stale(enabled: bool) -> None:
    """登録済みコマンドが古い場合（Python の場所や配置が変わった等）に更新する。"""
    if not enabled:
        return
    registered = get_registered_command()
    expected = build_command()
    if registered != expected:
        log.info("自動起動のコマンドを更新します: %s -> %s", registered, expected)
        enable()
