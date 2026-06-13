# build.spec
# PyInstaller spec file for Biometric Attendance Agent
# Run: pyinstaller build.spec --noconfirm

import sys
from pathlib import Path

APP_NAME   = "BiometricAgent"
ENTRY      = "tray.py"
ICON       = "assets/icon.ico"

block_cipher = None

a = Analysis(
    [ENTRY],
    pathex=["."],
    binaries=[],
    datas=[
        # Bundle the assets folder (icon, etc.)
        ("assets",          "assets"),
        # Bundle any config or template files your app ships with
        # ("config.json",   "."),   # uncomment if you ship a default config
    ],
    hiddenimports=[
        # pystray backends
        "pystray._win32",
        # PIL / Pillow
        "PIL._imagingtk",
        "PIL.Image",
        "PIL.ImageDraw",
        # Flask & Werkzeug internals that get missed by the hook
        "flask",
        "werkzeug",
        "werkzeug.serving",
        "werkzeug.debug",
        "jinja2",
        "jinja2.ext",
        # SQLite / SQLAlchemy (add if you use it)
        # "sqlalchemy.dialects.sqlite",
        # APScheduler (add if you use it)
        # "apscheduler.schedulers.background",
        # "apscheduler.executors.default",
        # Your own packages — list every submodule PyInstaller might miss
        "core",
        "core.config",
        "core.database",
        "core.adms_server",
        "core.scheduler",
        "core.socket_client",
        "web",
        "web.server",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    console=False,          # ← No console window; tray app only
    icon=ICON,
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
