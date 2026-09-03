# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import collect_all

from app._embedded_secret_payload import DEEPSEEK_SECRET_BLOB


datas = [
    ("web", "web"),
    ("猜乳贴游戏素材", "猜乳贴游戏素材"),
    ("../盲盒小游戏素材", "盲盒小游戏素材"),
    ("../塔罗牌素材", "塔罗牌素材"),
]
binaries = []
hiddenimports = []
for package in ("webview", "pythonnet", "playwright", "opencc", "socketio", "engineio"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

a = Analysis(
    ["desktop.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "tkinter.test"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DZMM群聊机器人",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
if not os.environ.get("DZMM_EXE_ONLY"):
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="DZMM群聊机器人",
    )
