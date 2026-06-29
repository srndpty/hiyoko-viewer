# -*- mode: python ; coding: utf-8 -*-

# JPEG XL fallback でしか imagecodecs / numpy を使わないため、collect_submodules で全コーデックを
# 取り込まず、JXL デコードに必要なモジュールだけを hidden import として明示する。
# fallback の _load_jxl_with_imagecodecs() は import_module() で動的に読み込んでおり、
# PyInstaller の静的解析では検出できないため列挙が必要（numpy も src 側に静的 import が無い）。
imagecodecs_hiddenimports = [
    'imagecodecs._jpegxl',
    'imagecodecs._shared',
    'numpy',
]


a = Analysis(
    ['main.py'],
    pathex=['src'],
    binaries=[],
    datas=[('src/hiyoko_viewer/assets/app_icon.ico', '.')],
    hiddenimports=imagecodecs_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='hiyoko-viewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['src/hiyoko_viewer/assets/app_icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='hiyoko-viewer',
)
