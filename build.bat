@echo off
setlocal EnableDelayedExpansion

:: ============================================================
::  build.bat — Build Betterschool Attendance Agent installer
::  Run this on your Windows 10/11 build machine.
::  Requires:
::    - Python 3.10+ in PATH  (with pip)
::    - Inno Setup 6 installed to default location
:: ============================================================

set INNO_COMPILER="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
set APP_NAME=BetterschoolAgent

echo.
echo ============================================================
echo  Betterschool Agent -- Build Script
echo ============================================================
echo.

:: ── Step 1: Install / upgrade Python dependencies ────────────
echo [1/4] Installing Python dependencies...
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if !ERRORLEVEL! NEQ 0 (
    echo ERROR: pip install failed. Check your Python environment.
    pause
    exit /b 1
)

:: pystray + Pillow are needed for the tray (add if not in requirements.txt)
pip install pystray Pillow pyinstaller
if !ERRORLEVEL! NEQ 0 (
    echo ERROR: Could not install pystray/Pillow/pyinstaller.
    pause
    exit /b 1
)
echo    Done.
echo.

:: ── Step 2: Clean previous build ─────────────────────────────
echo [2/4] Cleaning previous build output...
if exist dist\%APP_NAME% (
    rmdir /s /q dist\%APP_NAME%
)
if exist build (
    rmdir /s /q build
)
echo    Done.
echo.

:: ── Step 3: PyInstaller ───────────────────────────────────────
echo [3/4] Running PyInstaller...
pyinstaller build.spec --noconfirm
if !ERRORLEVEL! NEQ 0 (
    echo ERROR: PyInstaller failed. See output above.
    pause
    exit /b 1
)
echo    Done. Bundled app is in dist\%APP_NAME%\
echo.

:: ── Step 4: Inno Setup ───────────────────────────────────────
echo [4/4] Building installer with Inno Setup...
if not exist %INNO_COMPILER% (
    echo WARNING: Inno Setup not found at %INNO_COMPILER%
    echo          Download from https://jrsoftware.org/isinfo.php and install,
    echo          then re-run this script to produce the installer .exe.
    echo          The raw app bundle is ready in dist\%APP_NAME%\
    echo.
    pause
    exit /b 0
)

if not exist installer_output mkdir installer_output
%INNO_COMPILER% installer.iss
if !ERRORLEVEL! NEQ 0 (
    echo ERROR: Inno Setup compilation failed. See output above.
    pause
    exit /b 1
)
echo    Done.
echo.

echo ============================================================
echo  Build complete!
echo  Installer: installer_output\BetterschoolAgentSetup.exe
echo ============================================================
echo.
pause