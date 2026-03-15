# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path
import site
import sys

from PyInstaller.utils.hooks import collect_all


PROJECT_ROOT = Path(r"D:\develop\yys_dati")
VENV_SITE_PACKAGES = PROJECT_ROOT / ".venv" / "Lib" / "site-packages"
if VENV_SITE_PACKAGES.is_dir():
    site.addsitedir(str(VENV_SITE_PACKAGES))

PYWIN32_SYSTEM32 = VENV_SITE_PACKAGES / "pywin32_system32"
if PYWIN32_SYSTEM32.is_dir():
    os.environ["PATH"] = str(PYWIN32_SYSTEM32) + os.pathsep + os.environ.get("PATH", "")

datas = [
    (str(PROJECT_ROOT / "data" / "question_bank.json"), "data"),
    (str(PROJECT_ROOT / "data" / "confirm_templates"), "data/confirm_templates"),
]
binaries = []
hiddenimports = [
    "pythoncom",
    "pywintypes",
    "win32api",
    "win32com",
    "win32com.client",
    "win32con",
    "win32gui",
    "win32process",
    "win32ui",
]

for package_name in [
    "cv2",
    "numpy",
    "openai",
    "paddle",
    "paddleocr",
    "PIL",
    "pyautogui",
    "rapidfuzz",
    "requests",
    "shapely",
]:
    collected_datas, collected_binaries, collected_hiddenimports = collect_all(package_name)
    datas += collected_datas
    binaries += collected_binaries
    hiddenimports += collected_hiddenimports

hiddenimports = sorted(set(hiddenimports))


a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT), str(VENV_SITE_PACKAGES)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name="yys_dati",
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="yys_dati",
)
