# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all("cloakbrowser")
hiddenimports += [
    "appdirs",
    "jaraco",
    "packaging",
]
datas += [
    ("assets/cloakbrowser.png", "assets"),
    ("assets/cloakbrowser.ico", "assets"),
]

a = Analysis(
    ["main.py"],
    pathex=[],
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
    a.binaries,
    a.datas,
    [],
    name="CloakBrowser-Profile-Manager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon="assets/cloakbrowser.ico",
    disable_windowed_traceback=False,
)