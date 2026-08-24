"""在席 / 離席 の判定ロジック（状態機械）。

  PRESENT ──未検出が away_seconds 継続──▶ AWAY
     ▲                                      │
     └──連続 N 回検出 / キーマウス操作──────┘

安全のための重要なルール:
  カメラが使えない間 (UNKNOWN) は決して AWAY に遷移しない。
  真っ黒な映像を離席と誤認して画像を出しっぱなしにしないため。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


class PresenceState(Enum):
    PRESENT = "present"    # 在席中
    AWAY = "away"          # 離席中
    UNKNOWN = "unknown"    # カメラ不調などで判定不能
    PAUSED = "paused"      # 一時停止中
    DISABLED = "disabled"  # AwayCam 無効


@dataclass
class PresenceSnapshot:
    """UI に渡す現在の状況。"""

    state: PresenceState
    person_present: bool          # 直近フレームで人物が見えていたか
    seconds_until_away: float     # 離席確定までの残り秒（在席時のみ意味を持つ）
    consecutive_hits: int         # 復帰判定用の連続検出回数
    best_score: float = 0.0
    message: str = ""


class PresenceTracker:
    """検出結果を時系列で受け取り、在席状態を判定する。"""

    def __init__(
        self,
        away_seconds: int = 10,
        return_consecutive_hits: int = 3,
        return_on_user_input: bool = True,
        on_state_change: Optional[Callable[[PresenceState, PresenceState], None]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.away_seconds = away_seconds
        self.return_consecutive_hits = return_consecutive_hits
        self.return_on_user_input = return_on_user_input
        self.on_state_change = on_state_change
        self._clock = clock

        self.state = PresenceState.PRESENT
        self._last_seen_at = clock()      # 最後に人物を検出した時刻
        self._consecutive_hits = 0
        self._last_person_present = False
        self._last_score = 0.0
        self._manual_override = False     # 手動表示/手動解除の最中か

    # --- 設定の反映 ---

    def configure(
        self,
        away_seconds: Optional[int] = None,
        return_consecutive_hits: Optional[int] = None,
        return_on_user_input: Optional[bool] = None,
    ) -> None:
        if away_seconds is not None:
            self.away_seconds = away_seconds
        if return_consecutive_hits is not None:
            self.return_consecutive_hits = return_consecutive_hits
        if return_on_user_input is not None:
            self.return_on_user_input = return_on_user_input

    # --- 判定本体 ---

    def update(
        self,
        person_present: bool,
        camera_ok: bool,
        user_input_recent: bool = False,
        best_score: float = 0.0,
    ) -> PresenceSnapshot:
        """1回の判定サイクルを進め、現在の状況を返す。"""
        now = self._clock()
        self._last_person_present = person_present
        self._last_score = best_score

        # --- カメラが使えない: 判定を凍結する ---
        if not camera_ok:
            # 操作があれば離席は解除する（カメラ故障時の救済）
            if self.state is PresenceState.AWAY and self._user_input_returns(user_input_recent):
                self._transition(PresenceState.PRESENT)
                self._last_seen_at = now
            elif self.state is not PresenceState.AWAY:
                self._transition(PresenceState.UNKNOWN)
            # 離席中にカメラが壊れた場合はそのまま維持（Esc / 操作で解除できる）
            self._consecutive_hits = 0
            return self._snapshot(now, "カメラを利用できません")

        # カメラが復旧したら、まずは在席扱いから再開する
        if self.state is PresenceState.UNKNOWN:
            self._transition(PresenceState.PRESENT)
            self._last_seen_at = now

        # --- キーボード/マウス操作は最優先で在席とみなす ---
        if self._user_input_returns(user_input_recent):
            self._last_seen_at = now
            self._consecutive_hits = self.return_consecutive_hits
            if self.state is PresenceState.AWAY:
                self._transition(PresenceState.PRESENT)
            return self._snapshot(now, "操作を検知しました")

        # --- カメラによる判定 ---
        if person_present:
            self._consecutive_hits += 1
            self._last_seen_at = now
            # 離席中は連続 N 回の検出で初めて復帰（一瞬の誤検出で戻さない）
            if (
                self.state is PresenceState.AWAY
                and self._consecutive_hits >= self.return_consecutive_hits
            ):
                self._transition(PresenceState.PRESENT)
        else:
            self._consecutive_hits = 0
            # 未検出が away_seconds 続いたら離席
            if (
                self.state is PresenceState.PRESENT
                and (now - self._last_seen_at) >= self.away_seconds
            ):
                self._transition(PresenceState.AWAY)

        return self._snapshot(now)

    def peek(self) -> PresenceSnapshot:
        """状態を進めずに現在の状況だけを返す。

        コマ落ちで判定をスキップする周期でも、UI のカウントダウンは
        止めずに表示を更新するために使う。
        """
        return self._snapshot(self._clock())

    # --- 外部からの強制操作 ---

    def force_away(self) -> None:
        """「離席状態をテスト」やホットキーからの手動表示。"""
        self._manual_override = True
        self._last_seen_at = self._clock() - self.away_seconds
        # 離席前の検出回数を持ち越すと、次の1回の検出だけで復帰してしまう。
        # 復帰には改めて N 回の連続検出を求める。
        self._consecutive_hits = 0
        self._transition(PresenceState.AWAY)

    def force_present(self) -> None:
        """Esc / ホットキー / 「復帰」ボタンによる手動解除。"""
        self._manual_override = False
        self._last_seen_at = self._clock()
        self._consecutive_hits = self.return_consecutive_hits
        self._transition(PresenceState.PRESENT)

    def set_paused(self, paused: bool) -> None:  # noqa: D102
        if paused:
            self._transition(PresenceState.PAUSED)
        elif self.state is PresenceState.PAUSED:
            self.reset()

    def set_enabled(self, enabled: bool) -> None:
        if not enabled:
            self._transition(PresenceState.DISABLED)
        elif self.state is PresenceState.DISABLED:
            self.reset()

    def reset(self) -> None:
        """在席状態から判定をやり直す。"""
        self._last_seen_at = self._clock()
        self._consecutive_hits = 0
        self._manual_override = False
        self._transition(PresenceState.PRESENT)

    # --- 内部処理 ---

    def _user_input_returns(self, user_input_recent: bool) -> bool:
        return self.return_on_user_input and user_input_recent

    def _transition(self, new_state: PresenceState) -> None:
        if new_state is self.state:
            return
        old_state = self.state
        self.state = new_state
        if new_state is not PresenceState.AWAY:
            self._manual_override = False
        if self.on_state_change is not None:
            self.on_state_change(old_state, new_state)

    def _snapshot(self, now: float, message: str = "") -> PresenceSnapshot:
        remaining = max(0.0, self.away_seconds - (now - self._last_seen_at))
        return PresenceSnapshot(
            state=self.state,
            person_present=self._last_person_present,
            seconds_until_away=remaining,
            consecutive_hits=self._consecutive_hits,
            best_score=self._last_score,
            message=message,
        )
