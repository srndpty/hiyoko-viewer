"""メニュー操作の有効状態を、ビューアの状態変更から更新する。"""

from __future__ import annotations


def sync_action_states(host: object) -> None:
    """``_sync_action_states`` を持つウィンドウだけメニューを更新する。

    ミックスインの単体テストは ``SimpleNamespace`` でメソッドを呼ぶため、
    メニューを持たないホストでは何もしない。
    """
    sync = getattr(host, "_sync_action_states", None)
    if sync is not None:
        sync()
