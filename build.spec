# build.spec
APP_NAME = "BiometricAgent"
ENTRY    = "tray.py"
ICON     = "assets/icon.ico"

block_cipher = None

a = Analysis(
    [ENTRY],
    pathex=["."],
    binaries=[],
    datas=[
        ("assets",        "assets"),
        # Bundle templates so Flask can serve index.html at runtime.
        # Destination "web/templates" mirrors what server.py expects.
        ("web/templates", "web/templates"),
    ],
    hiddenimports=[
        "pystray._win32",
        "PIL._imagingtk",
        "PIL.Image",
        "PIL.ImageDraw",
        "flask",
        "flask.json",
        "werkzeug",
        "werkzeug.serving",
        "werkzeug.debug",
        "jinja2",
        "jinja2.ext",
        "core",
        "core.config",
        "core.database",
        "core.adms_server",
        "core.scheduler",
        "core.socket_client",
        "core.erp_sync",
        "core.sdk_device",
        "web",
        "web.server",
        "web.api",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
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
    strip=False,
    upx=True,
    console=False,
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
