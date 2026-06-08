"""ファイル名の並び替えキー。

Windows Explorer の「名前」順（StrCmpLogicalW ベースの論理順）を再現する。
DLL が使えない環境ではロケール + 簡易ナチュラルソートにフォールバックする。
"""

from __future__ import annotations

import ctypes
import functools
import locale
import os
import re
import sys

# natural_key はフォールバック用。数字を数値として扱う簡易ナチュラルソート。
_NATURAL_SPLIT_RE = re.compile(r"(\d+)")


def natural_key(path: str):
    name = os.path.basename(path)
    parts = _NATURAL_SPLIT_RE.split(name)
    return tuple(int(p) if p.isdigit() else p.casefold() for p in parts)


def _load_windows_logical_comparer():
    if not sys.platform.startswith("win"):
        return None

    try:
        shlwapi = ctypes.windll.Shlwapi
    except Exception:
        return None

    try:
        cmp_func = shlwapi.StrCmpLogicalW
        cmp_func.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        cmp_func.restype = ctypes.c_int
    except Exception:
        return None

    return cmp_func


_STRCMP_LOGICALW = _load_windows_logical_comparer()


def _create_windows_logical_key(comparer=_STRCMP_LOGICALW):
    """Windowsの論理順比較に基づくキーを生成する key 関数を返す。"""

    if comparer:

        def _cmp(a: str, b: str) -> int:
            # フォルダ内での並び順なので basename だけ比較する
            return comparer(os.path.basename(a), os.path.basename(b))

        # sorted(..., key=cmp_to_key(_cmp)) という形で使える「key」を返す
        return functools.cmp_to_key(_cmp)

    # ここから下は非 Windows や DLL が使えないときのフォールバック
    locale.setlocale(locale.LC_COLLATE, "")  # OS のロケールに合わせる
    locale_transform = locale.strxfrm

    def _fallback_key(path: str):
        name = os.path.basename(path)
        # まずロケール順、同値なら簡易ナチュラル順
        return (locale_transform(name.casefold()), natural_key(path))

    return _fallback_key


# 実際に sorted(..., key=windows_logical_key) で使うキー
windows_logical_key = _create_windows_logical_key()
