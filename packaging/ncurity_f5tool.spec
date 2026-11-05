# PyInstaller spec — one-folder offline bundle (Windows).
# Build: scripts\build_windows.ps1
#
# Output: dist\NcurityF5Tool\NcurityF5Tool.exe + _internal\

import sys
from pathlib import Path

block_cipher = None
# SPECPATH = directory containing this .spec (packaging/)
ROOT = Path(SPECPATH).resolve().parent
VERSION_INFO = ROOT / "packaging" / "file_version_info.txt"
WIN_MANIFEST = ROOT / "packaging" / "pyinstaller_win_manifest.xml"

a = Analysis(
    [str(ROOT / "app" / "gui" / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "app" / "resources"), "app/resources"),
        (str(ROOT / "templates"), "templates"),
        (str(ROOT / "config"), "config"),
        (str(ROOT / "app" / "modules" / "vpe_viewer" / "static"), "vpe_viewer/static"),
    ],
    hiddenimports=[
        "app.runtime.paths",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtWebEngineCore",
        "PyQt6.sip",
        "httpx",
        "jinja2",
        "openpyxl",
        "pydantic",
        "yaml",
        "flask",
        "werkzeug",
        "docx",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "tkinter",
        "unittest",
        "pytest",
        "IPython",
        "paramiko",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

_version_arg = str(VERSION_INFO) if VERSION_INFO.is_file() else None
_manifest_arg = str(WIN_MANIFEST) if WIN_MANIFEST.is_file() else None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NcurityF5Tool",
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
    version=_version_arg,
    manifest=_manifest_arg,
    uac_admin=False,
    icon=str(ROOT / "app" / "resources" / "ncurity_app_icon.ico")
    if (ROOT / "app" / "resources" / "ncurity_app_icon.ico").is_file()
    else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NcurityF5Tool",
)
