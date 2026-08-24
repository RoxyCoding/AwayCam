# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller のビルド定義。

    pyinstaller AwayCam.spec --noconfirm

フォルダ形式（onedir）で出力する。常駐アプリなので起動の速さを優先し、
settings.json や logs を exe の隣に置いて利用者が触れるようにするため。

出力: dist/AwayCam/AwayCam.exe
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PROJECT_DIR = Path(SPECPATH)

# --- 同梱するデータ ---
datas = []

# 検出モデル。exe の隣の models/ に置くので、利用者が差し替えられる。
for model in ("yolo26n.pt", "yolo26n-pose.pt", "efficientdet_lite0.tflite"):
    path = PROJECT_DIR / "models" / model
    if path.exists():
        datas.append((str(path), "models"))

# ultralytics は設定 yaml を実行時に読むので同梱が要る
datas += collect_data_files("ultralytics")
# mediapipe は .binarypb / .tflite をパッケージ内から読む
datas += collect_data_files("mediapipe")

# --- 動的 import されるモジュール ---
hiddenimports = [
    "pycaw",
    "comtypes",
    "comtypes.stream",   # pycaw が実行時に読む
    "pygrabber",
    "pygrabber.dshow_graph",
]
hiddenimports += collect_submodules("ultralytics")

# --- 不要な依存を落としてサイズを抑える ---
excludes = [
    "tkinter",
    "matplotlib",     # ultralytics が描画に使うが AwayCam では未使用
    "IPython",
    "notebook",
    "pytest",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "torchvision.datasets",
    "torch.distributions",
    "torch.testing",
]

a = Analysis(
    ["run.py"],
    pathex=[str(PROJECT_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AwayCam",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX は torch の DLL を壊すことがあるので使わない
    console=False,      # 常駐アプリなのでコンソール窓は出さない
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_DIR / "assets" / "awaycam.ico")
    if (PROJECT_DIR / "assets" / "awaycam.ico").exists()
    else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AwayCam",
)
