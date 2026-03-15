# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path
import site
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


PROJECT_ROOT = Path(r"D:\develop\yys_dati")
VENV_SITE_PACKAGES = PROJECT_ROOT / ".venv" / "Lib" / "site-packages"
PADDLEOCR_ROOT = VENV_SITE_PACKAGES / "paddleocr"
if VENV_SITE_PACKAGES.is_dir():
    site.addsitedir(str(VENV_SITE_PACKAGES))
if PADDLEOCR_ROOT.is_dir():
    site.addsitedir(str(PADDLEOCR_ROOT))

PYWIN32_SYSTEM32 = VENV_SITE_PACKAGES / "pywin32_system32"
if PYWIN32_SYSTEM32.is_dir():
    os.environ["PATH"] = str(PYWIN32_SYSTEM32) + os.pathsep + os.environ.get("PATH", "")

datas = [
    (str(PROJECT_ROOT / "data" / "question_bank.json"), "data"),
    (str(PROJECT_ROOT / "data" / "confirm_templates"), "data/confirm_templates"),
    (str(PROJECT_ROOT / "secrets.json.example"), "."),
]
binaries = collect_dynamic_libs("paddle")
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
    "ppocr",
    "ppocr.utils",
    "ppocr.utils.logging",
    "ppocr.utils.utility",
    "ppocr.utils.network",
    "ppstructure",
    "ppstructure.utility",
    "ppstructure.predict_system",
    "ppstructure.layout.predict_layout",
    "ppstructure.table.predict_table",
    "ppstructure.table.predict_structure",
    "ppstructure.table.matcher",
    "ppstructure.table.table_master_match",
    "tools",
    "tools.infer",
    "tools.infer.predict_cls",
    "tools.infer.predict_det",
    "tools.infer.predict_rec",
    "tools.infer.predict_system",
    "tools.infer.utility",
]

datas += collect_data_files(
    "paddleocr",
    includes=["**/*.txt", "**/*.json", "**/*.yaml", "**/*.yml", "**/*.pkl"],
    excludes=[
        "**/__pycache__/**",
        "**/tests/**",
        "**/ppstructure/docs/**",
        "**/*.pyc",
    ],
)

if PYWIN32_SYSTEM32.is_dir():
    binaries += [(str(path), ".") for path in PYWIN32_SYSTEM32.glob("*.dll")]

hiddenimports = sorted(set(hiddenimports))


a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT), str(VENV_SITE_PACKAGES), str(PADDLEOCR_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "IPython",
        "matplotlib",
        "openpyxl",
        "paddleocr.tests",
        "pandas",
        "ppstructure.kie",
        "ppstructure.pdf2word",
        "ppstructure.recovery",
        "ppstructure.table.eval_table",
        "ppstructure.table.table_metric",
        "ppstructure.table.tablepyxl",
        "pytest",
        "scipy",
        "shapely",
        "tensorflow",
    ],
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
