# Building the Biometric Attendance Agent Installer

## Prerequisites (Windows build machine)

| Tool           | Where to get                      |
| -------------- | --------------------------------- |
| Python 3.10+   | https://python.org                |
| Inno Setup 6   | https://jrsoftware.org/isinfo.php |
| Git (optional) | https://git-scm.com               |

> **Must build on Windows.** Cross-compiling from Linux with Wine is unreliable
> for packages like `pyzk` and `eventlet` that have native extensions.
> Use your Windows 10 machine, or a Windows VM, or a GitHub Actions
> `windows-latest` runner.

---

## Project structure expected before building

```
project-root/
├── assets/
│   └── icon.ico          ← your tray/installer icon
├── core/
│   └── ...               ← all core/*.py files
├── web/
│   ├── api.py
│   ├── server.py
│   └── templates/
│       └── index.html
├── config-example.json   ← copied into the installer as a reference
├── tray.py               ← new entry point (replaces main.py for packaged app)
├── main.py               ← keep for dev use
├── requirements.txt
├── build.spec
├── installer.iss
└── build.bat
```

---

## Build steps

### 1. One-click build

```bat
build.bat
```

That's it. The script:

1. Installs all Python dependencies (including `pystray`, `Pillow`, `pyinstaller`)
2. Cleans old build output
3. Runs PyInstaller → produces `dist\BiometricAgent\`
4. Runs Inno Setup → produces `installer_output\BiometricAgentSetup.exe`

---

### 2. What the installer does on the user's machine

- Installs to `C:\Program Files\Biometric Attendance Agent\`
- Creates a Start Menu shortcut
- Optionally (user can untick) adds a registry Run key so the agent
  starts automatically on Windows login
- Launches the agent immediately after installation
- Registers in Add/Remove Programs for clean uninstall

---

## What `tray.py` does

`tray.py` is the new packaged entry point. It:

- Starts ADMS server, scheduler, WebSocket client (if realtime), and web UI
  all in background threads
- Shows a system tray icon (bottom-right, click the `^` chevron)
- Right-click menu:
  - **Open Web Panel** — opens `http://127.0.0.1:5837` in the browser
  - **Status labels** — live ADMS / Scheduler / WebSocket / Web UI status,
    refreshed every 5 seconds
  - **Restart** — relaunches the process (picks up config changes)
  - **Exit** — stops everything

> `main.py` still works as-is for development. Use `tray.py` only for the
> packaged/production build.

---

## Changing the version number

Edit line 3 of `installer.iss`:

```
#define AppVersion   "1.0.0"
```

---

## GitHub Actions build (optional — no Windows machine needed)

Create `.github/workflows/build.yml`:

```yaml
name: Build Installer
on: [push]
jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install Inno Setup
        run: choco install innosetup -y
      - name: Build
        run: build.bat
      - uses: actions/upload-artifact@v4
        with:
          name: installer
          path: installer_output\BiometricAgentSetup.exe
```

---

## Troubleshooting

| Problem                             | Fix                                                                          |
| ----------------------------------- | ---------------------------------------------------------------------------- |
| `ModuleNotFoundError` after install | Add the missing module to `hiddenimports` in `build.spec`                    |
| Tray icon doesn't appear            | Make sure `assets/icon.ico` exists; fallback is a green square               |
| App crashes silently                | Temporarily set `console=True` in `build.spec` to see output                 |
| Port already in use                 | Another instance is running — check Task Manager for `BiometricAgent.exe` |
| Inno Setup not found                | Install from https://jrsoftware.org/isinfo.php — default path assumed        |
