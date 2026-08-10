# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


PROJECT_ROOT = Path(SPECPATH).resolve().parents[1]
APP_NAME = "ProjetRepondeur"

datas = [
    (str(PROJECT_ROOT / "config"), "config"),
    (str(PROJECT_ROOT / "docs"), "docs"),
    (str(PROJECT_ROOT / "ressources-originales"), "ressources-originales"),
]

for package_name in (
    "playwright",
    "dateparser",
    "faster_whisper",
):
    datas += collect_data_files(package_name)

hiddenimports = []
for package_name in (
    "playwright",
    "dateparser",
):
    hiddenimports += collect_submodules(package_name)

binaries = []
for package_name in (
    "ctranslate2",
    "tokenizers",
):
    try:
        binaries += collect_dynamic_libs(package_name)
    except Exception:
        pass

block_cipher = None

a = Analysis(
    [str(PROJECT_ROOT / "app_cli.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "notebook", "jupyter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)
