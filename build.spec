# build.spec
# PyInstaller spec file for Betterschool Attendance Agent
# Run with: pyinstaller build.spec

import sys
from pathlib import Path

ROOT = Path(SPECPATH)   # directory containing this .spec file

block_cipher = None

a = Analysis(
    [str(ROOT / "tray.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Web UI template
        (str(ROOT / "web" / "templates"),   "web/templates"),
        # Icon
        (str(ROOT / "assets" / "icon.ico"), "assets"),
        # Default config (so first run can seed config.json)
        (str(ROOT / "config-example.json"), "."),
    ],
    hiddenimports=[
        # Flask / Werkzeug internals sometimes missed
        "flask",
        "werkzeug",
        "werkzeug.serving",
        "werkzeug.middleware.proxy_fix",
        # pyzk
        "zk",
        "zk.base",
        "zk.attendance",
        "zk.exception",
        "zk.finger",
        "zk.user",
        "zk.utils",
        # Socket.IO / eventlet
        "socketio",
        "engineio",
        "eventlet",
        "eventlet.hubs",
        "eventlet.hubs.epolls",
        "eventlet.hubs.kqueue",
        "eventlet.hubs.selects",
        "eventlet.support",
        "dns",
        "dns.resolver",
        # PIL / pystray
        "PIL",
        "PIL.Image",
        "pystray",
        # Project modules
        "core",
        "core.config",
        "core.database",
        "core.adms_server",
        "core.scheduler",
        "core.erp_sync",
        "core.sdk_device",
        "core.socket_client",
        "web",
        "web.api",
        "web.server",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "email",
        "html",
        "http",
        "urllib",   # keep urllib3 but strip stdlib urllib
        "xmlrpc",
        "pydoc",
        "doctest",
        "difflib",
        "ftplib",
        "getpass",
        "getopt",
        "imaplib",
        "mailbox",
        "mimetypes",
        "smtplib",
    ],
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
    exclude_binaries=True,          # use COLLECT (folder mode) — more reliable than onefile
    name="BetterschoolAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,                  # no console window — it's a tray app
    icon=str(ROOT / "assets" / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="BetterschoolAgent",       # output folder: dist/BetterschoolAgent/
)
