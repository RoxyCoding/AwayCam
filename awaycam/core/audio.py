"""離席中のシステム出力音声のミュート。

Windows Core Audio (pycaw) で既定の出力デバイスをミュートする。

重要な設計方針:
- **自分がミュートしたときだけ解除する。** 離席前からユーザーが自分で
  ミュートしていた場合、復帰時に勝手に音を出してしまわないようにする。
- pycaw が無い / 音声デバイスが無い環境でも例外を投げない。
  音が消せないことは、AwayCam の主機能を止める理由にはならない。
- COM は呼び出すスレッドごとに初期化が要るため、毎回デバイスを取り直す。
  （既定の出力デバイスが切り替わったときにも追従できる）
"""
from __future__ import annotations

from typing import Optional

from ..logging_setup import get_logger

log = get_logger("audio")


class AudioMuter:
    """既定の出力デバイスのミュートを制御する。"""

    def __init__(self) -> None:
        self.available = False
        self.last_error: str = ""
        # 自分がミュートした場合のみ True。復帰時にこれを見て解除を判断する。
        self._muted_by_us = False
        self._check_availability()

    def _check_availability(self) -> None:
        try:
            from pycaw.utils import AudioUtilities  # noqa: F401

            self.available = True
        except Exception as exc:
            self.last_error = (
                f"音声を制御できません（pycaw を読み込めません）: {exc}\n"
                "pip install pycaw を実行してください。"
            )
            log.info(self.last_error)

    # --- 内部処理 ---

    def _endpoint_volume(self):
        """既定の出力デバイスの音量インターフェースを取得する。"""
        from pycaw.utils import AudioUtilities

        speakers = AudioUtilities.GetSpeakers()
        return speakers.EndpointVolume, speakers.FriendlyName

    # --- 外部から呼ぶ ---

    @property
    def muted_by_us(self) -> bool:
        return self._muted_by_us

    def is_system_muted(self) -> Optional[bool]:
        """現在のミュート状態。取得できなければ None。"""
        if not self.available:
            return None
        try:
            volume, _name = self._endpoint_volume()
            return bool(volume.GetMute())
        except Exception as exc:
            self.last_error = f"ミュート状態を取得できません: {exc}"
            log.warning(self.last_error)
            return None

    def mute(self) -> bool:
        """ミュートする。成功したら True。"""
        if not self.available:
            return False
        try:
            volume, name = self._endpoint_volume()
            if bool(volume.GetMute()):
                # もともとミュートされていた。復帰時に触らないよう記録しない。
                log.info("既にミュートされているため、音声はそのままにします")
                self._muted_by_us = False
                return True
            volume.SetMute(1, None)
            self._muted_by_us = True
            self.last_error = ""
            log.info("出力音声をミュートしました（%s）", name)
            return True
        except Exception as exc:
            self.last_error = f"ミュートできませんでした: {exc}"
            log.warning(self.last_error)
            return False

    def unmute(self) -> bool:
        """自分がミュートしていた場合のみ解除する。"""
        if not self._muted_by_us:
            return False
        self._muted_by_us = False
        if not self.available:
            return False
        try:
            volume, name = self._endpoint_volume()
            volume.SetMute(0, None)
            self.last_error = ""
            log.info("出力音声のミュートを解除しました（%s）", name)
            return True
        except Exception as exc:
            self.last_error = f"ミュートを解除できませんでした: {exc}"
            log.warning(self.last_error)
            return False

    def forget(self) -> None:
        """ミュート状態の記憶だけを捨てる（設定で機能を切ったときなど）。"""
        self._muted_by_us = False
